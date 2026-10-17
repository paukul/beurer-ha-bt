"""Connection handling for the Beurer WL75.

Kept free of Home Assistant imports so it can be driven from a plain script.
Rules learned from the device (docs/wl75-protocol.md):

- every connection starts with the handshake ``00 75``, otherwise the lamp drops
  the link on the first unknown frame;
- every command is answered, and commands sent faster than the answers come back
  garble the replies, so only one request is in flight at any time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
import math

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS,
    BleakClientWithServiceCache,
    establish_connection,
)

from . import protocol
from .protocol import Alarm, LightState, MoodState, Settings, SleepState

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 2.0
REQUEST_RETRIES = 1


class WL75Error(Exception):
    """Communication with the lamp failed."""


BLEAK_EXCEPTIONS = (*BLEAK_RETRY_EXCEPTIONS, BleakError, WL75Error)


@dataclass(frozen=True, slots=True)
class SleepSettings:
    """Settings applied when the sleep function starts.

    The lamp only accepts them while the sleep function runs and forgets the
    duration when it stops, so they are kept here and sent on every start.
    """

    minutes: int = 30
    light: int = 1
    brightness: int = 100
    sound: int = 0
    volume: int = 5
    fade_out: bool = True


class WL75Device:
    """A Beurer WL75 reachable over BLE."""

    def __init__(
        self,
        ble_device: BLEDevice,
        *,
        now: Callable[[], datetime] = datetime.now,
        idle_disconnect: float | None = 60.0,
    ) -> None:
        """Initialize the device.

        ``now`` returns the local time used to set the lamp clock.
        """
        self._ble_device = ble_device
        self._now = now
        self._idle_disconnect = idle_disconnect
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._pending: tuple[int, asyncio.Future[bytes]] | None = None
        self._idle_handle: asyncio.TimerHandle | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._callbacks: list[Callable[[], None]] = []
        self.settings: Settings | None = None
        self.light: LightState | None = None
        self.mood: MoodState | None = None
        self.alarms: dict[int, Alarm] = {}
        self.sleep: SleepState | None = None
        self.sleep_settings = SleepSettings()
        self.sleep_end: datetime | None = None
        self._sleep_handle: asyncio.TimerHandle | None = None

    @property
    def address(self) -> str:
        """Return the BLE address."""
        return self._ble_device.address

    @property
    def name(self) -> str:
        """Return the advertised name."""
        return self._ble_device.name or self._ble_device.address

    @property
    def mood_scene(self) -> int | None:
        """Return the running mood scene, or None for a fixed color."""
        if self.mood is None or not self.mood.is_on:
            return None
        return self.mood.scene or None

    @property
    def sleep_running(self) -> bool:
        """Return if the sleep function runs (as far as known without polling)."""
        return self.sleep is not None and self.sleep.is_on

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData | None = None
    ) -> None:
        """Update the BLE device, e.g. when another proxy sees the lamp better."""
        self._ble_device = ble_device

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for state changes; returns an unsubscribe function."""
        self._callbacks.append(callback)

        def unregister() -> None:
            self._callbacks.remove(callback)

        return unregister

    async def update(self) -> None:
        """Query the complete state (no callbacks are fired)."""
        async with self._lock:
            await self._query_state()
            for alarm_id in protocol.ALARM_IDS:
                await self._query_alarm(alarm_id)
            await self._query_sleep()

    async def turn_on_light(self, brightness: int | None = None) -> None:
        """Switch the main light on, optionally with brightness 1-100."""
        payloads = [protocol.switch_light(True)]
        if brightness is not None:
            payloads.append(protocol.set_light_brightness(brightness))
        await self._run(payloads)

    async def turn_off_light(self) -> None:
        """Switch the main light off."""
        await self._run([protocol.switch_light(False)])

    async def turn_on_mood(
        self,
        brightness: int | None = None,
        rgb: tuple[int, int, int] | None = None,
        scene: int | None = None,
    ) -> None:
        """Switch the mood light on and apply brightness 1-100, color or scene."""
        async with self._lock:
            # Only switch when really off, so changing the brightness of a lit
            # mood light never touches the running color or scene.
            self.mood = MoodState.from_payload(await self._request(protocol.query_mood()))
            if not self.mood.is_on:
                await self._command(protocol.switch_mood(True))
            if brightness is not None:
                await self._command(protocol.set_mood_brightness(brightness))
            if rgb is not None:
                await self._command(protocol.set_mood_color(*rgb))
            elif scene is not None:
                await self._command(protocol.set_mood_scene(scene))
            await self._query_state()
        self._fire_callbacks()

    async def turn_off_mood(self) -> None:
        """Switch the mood light off."""
        await self._run([protocol.switch_mood(False)])

    async def modify_alarm(self, alarm_id: int, change: Callable[[Alarm], Alarm]) -> None:
        """Change an alarm.

        The lamp only takes complete alarms, so read the current one first:
        the cached copy may be outdated (no polling, changes in the app).
        """
        async with self._lock:
            alarm = change(await self._query_alarm(alarm_id))
            await self._command(protocol.set_alarm(alarm))
            await self._query_alarm(alarm_id)
        self._fire_callbacks()

    async def start_sleep(self) -> None:
        """Start the sleep function with the current sleep settings."""
        settings = self.sleep_settings
        async with self._lock:
            try:
                await self._command(protocol.switch_sleep(True))
                await self._command(
                    protocol.set_sleep_light(settings.minutes, settings.light, settings.brightness)
                )
                await self._command(
                    protocol.set_sleep_sound(settings.sound, settings.volume, settings.fade_out)
                )
                self._set_sleep_end(settings.minutes)
            finally:
                # Also after a rejected setting: the sleep function may run anyway.
                with suppress(*BLEAK_EXCEPTIONS):
                    # The sleep light may switch the mood light.
                    await self._query_state()
                    await self._query_sleep()
                self._fire_callbacks()

    async def stop_sleep(self) -> None:
        """Stop the sleep function."""
        async with self._lock:
            await self._command(protocol.switch_sleep(False))
            await self._query_state()
            await self._query_sleep()
        self._fire_callbacks()

    def restore_sleep_settings(self, **changes: int | bool) -> None:
        """Set sleep settings without sending them (e.g. restored after a restart)."""
        self.sleep_settings = replace(self.sleep_settings, **changes)

    async def set_sleep_settings(self, **changes: int | bool) -> None:
        """Change sleep settings; a running sleep function is updated right away."""
        old = self.sleep_settings
        new = self.sleep_settings = replace(old, **changes)
        if not self.sleep_running:
            self._fire_callbacks()
            return
        payloads = []
        minutes = None
        if (old.minutes, old.light, old.brightness) != (new.minutes, new.light, new.brightness):
            # The duration sent restarts the countdown, so keep the remaining
            # time (rounded up) when only light or brightness change.
            minutes = new.minutes if old.minutes != new.minutes else self._sleep_minutes_left()
            payloads.append(protocol.set_sleep_light(minutes, new.light, new.brightness))
        if (old.sound, old.volume, old.fade_out) != (new.sound, new.volume, new.fade_out):
            payloads.append(protocol.set_sleep_sound(new.sound, new.volume, new.fade_out))
        async with self._lock:
            for payload in payloads:
                answer = await self._request(payload)
                if answer[1:2] != bytes([protocol.ACK_OK]):
                    # Rejected: the sleep function has ended in the meantime.
                    self._mark_sleep_off()
                    break
            else:
                if minutes is not None:
                    self._set_sleep_end(minutes)
            await self._query_sleep()
        self._fire_callbacks()

    def _sleep_minutes_left(self) -> int:
        if self.sleep_end is None:
            return self.sleep_settings.minutes
        seconds = (self.sleep_end - self._now()).total_seconds()
        return min(max(math.ceil(seconds / 60), 1), 60)

    async def stop(self) -> None:
        """Disconnect and stop all timers."""
        self._cancel_idle_timer()
        self._cancel_sleep_timer()
        async with self._lock:
            await self._disconnect()

    async def _run(self, payloads: list[bytes]) -> None:
        async with self._lock:
            for payload in payloads:
                await self._command(payload)
            # Main and mood light may influence each other, so refresh both.
            await self._query_state()
        self._fire_callbacks()

    async def _query_state(self) -> None:
        self.light = LightState.from_payload(await self._request(protocol.query_light()))
        self.mood = MoodState.from_payload(await self._request(protocol.query_mood()))

    async def _query_alarm(self, alarm_id: int) -> Alarm:
        alarm = Alarm.from_payload(await self._request(protocol.query_alarm(alarm_id)))
        if alarm.alarm_id != alarm_id:
            raise WL75Error(f"Asked for alarm {alarm_id}, got alarm {alarm.alarm_id}")
        self.alarms[alarm_id] = alarm
        return alarm

    async def _query_sleep(self) -> None:
        self.sleep = SleepState.from_payload(await self._request(protocol.query_sleep()))
        if not self.sleep.is_on:
            self._cancel_sleep_timer()
            self.sleep_end = None
        elif self.sleep_end is None:
            # Started on the lamp or in the app: minutes is the remaining time,
            # rounded down or up, so this may be up to a minute late.
            self._set_sleep_end(self.sleep.minutes + 1)

    async def _command(self, payload: bytes) -> None:
        _check_ack(payload, await self._request(payload))

    async def _request(self, payload: bytes) -> bytes:
        """Send one request and return the answer, reconnecting if needed."""
        self._cancel_idle_timer()
        try:
            for attempt in range(REQUEST_RETRIES + 1):
                await self._ensure_connected()
                try:
                    return await self._transact(payload)
                except BLEAK_EXCEPTIONS as err:
                    if attempt == REQUEST_RETRIES:
                        raise
                    _LOGGER.debug(
                        "%s: request %s failed (%s), retrying", self.name, payload.hex(" "), err
                    )
            raise AssertionError("unreachable")
        finally:
            self._schedule_idle_timer()

    async def _transact(self, payload: bytes) -> bytes:
        """Write one frame and wait for the matching answer."""
        client = self._client
        if client is None or not client.is_connected:
            raise WL75Error("Not connected")
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._pending = (protocol.response_code(payload[0]), future)
        try:
            frame = protocol.build_frame(payload)
            _LOGGER.debug("%s: -> %s", self.name, frame.hex(" "))
            await client.write_gatt_char(protocol.WRITE_UUID, frame, response=False)
            try:
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    return await future
            except TimeoutError as err:
                raise WL75Error(f"No answer to {payload.hex(' ')}") from err
        finally:
            self._pending = None

    async def _ensure_connected(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        _LOGGER.debug("%s: connecting", self.name)
        client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self.name,
            self._on_disconnected,
            ble_device_callback=lambda: self._ble_device,
        )
        self._client = client
        try:
            await client.start_notify(protocol.NOTIFY_UUID, self._on_notify)
            answer = await self._transact(protocol.handshake())
            if answer != protocol.HANDSHAKE_ANSWER:
                raise WL75Error(f"Unexpected handshake answer {answer.hex(' ')}")
            self.settings = Settings.from_payload(await self._transact(protocol.query_settings()))
            if self.settings.time_auto:
                payload = protocol.set_time(self._now())
                _check_ack(payload, await self._transact(payload))
        except BaseException:
            await self._disconnect()
            raise
        _LOGGER.debug("%s: connected", self.name)

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        _LOGGER.debug("%s: disconnecting", self.name)
        try:
            await client.disconnect()
        except BleakError as err:
            _LOGGER.debug("%s: disconnect failed: %s", self.name, err)

    def _on_disconnected(self, client: BleakClientWithServiceCache) -> None:
        if client is self._client:
            _LOGGER.debug("%s: connection lost", self.name)
            self._client = None
        if self._pending is not None and not self._pending[1].done():
            self._pending[1].set_exception(WL75Error("Disconnected"))

    def _on_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("%s: <- %s", self.name, data.hex(" "))
        for payload in protocol.parse_frames(bytes(data)):
            if self._pending is not None:
                code, future = self._pending
                if payload[0] == code and not future.done():
                    future.set_result(payload)
                    continue
            self._handle_unsolicited(payload)

    def _handle_unsolicited(self, payload: bytes) -> None:
        code = payload[0]
        try:
            if code == protocol.response_code(protocol.CMD_LIGHT_STATUS):
                self.light = LightState.from_payload(payload)
            elif code == protocol.response_code(protocol.CMD_MOOD_STATUS):
                self.mood = MoodState.from_payload(payload)
            elif code == protocol.CODE_TIMER_FINISHED and len(payload) > 1:
                if payload[1] == protocol.TIMER_LIGHT and self.light is not None:
                    self.light = replace(self.light, is_on=False)
                elif payload[1] == protocol.TIMER_MOOD and self.mood is not None:
                    self.mood = replace(self.mood, is_on=False)
                elif payload[1] == protocol.TIMER_SLEEP:
                    self._mark_sleep_off()
            else:
                _LOGGER.debug("%s: ignoring unsolicited %s", self.name, payload.hex(" "))
                return
        except protocol.ProtocolError as err:
            _LOGGER.debug("%s: %s", self.name, err)
            return
        self._fire_callbacks()

    def _fire_callbacks(self) -> None:
        for callback in list(self._callbacks):
            callback()

    def _set_sleep_end(self, minutes: int) -> None:
        """Remember when the sleep function ends.

        Without polling Home Assistant is usually not connected when the lamp
        finishes, so the end is tracked locally instead of opening a connection.
        """
        self._cancel_sleep_timer()
        self.sleep_end = self._now() + timedelta(minutes=minutes)
        self._sleep_handle = asyncio.get_running_loop().call_later(minutes * 60, self._on_sleep_end)

    def _on_sleep_end(self) -> None:
        self._sleep_handle = None
        self._mark_sleep_off()
        self._fire_callbacks()

    def _mark_sleep_off(self) -> None:
        self._cancel_sleep_timer()
        self.sleep_end = None
        if self.sleep is not None:
            self.sleep = replace(self.sleep, is_on=False)

    def _cancel_sleep_timer(self) -> None:
        if self._sleep_handle is not None:
            self._sleep_handle.cancel()
            self._sleep_handle = None

    def _cancel_idle_timer(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    def _schedule_idle_timer(self) -> None:
        if self._idle_disconnect is None:
            return
        self._cancel_idle_timer()
        self._idle_handle = asyncio.get_running_loop().call_later(
            self._idle_disconnect, self._start_idle_disconnect
        )

    def _start_idle_disconnect(self) -> None:
        self._idle_handle = None
        self._idle_task = asyncio.create_task(self._idle_disconnect_task())

    async def _idle_disconnect_task(self) -> None:
        async with self._lock:
            if self._idle_handle is None:
                await self._disconnect()


def _check_ack(request: bytes, answer: bytes) -> None:
    if len(answer) < 2 or answer[1] != protocol.ACK_OK:
        raise WL75Error(f"Lamp rejected {request.hex(' ')}: {answer.hex(' ')}")

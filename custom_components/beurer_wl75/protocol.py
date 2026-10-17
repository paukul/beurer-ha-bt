"""BLE protocol of the Beurer WL75 wake-up light.

Pure module without Home Assistant imports. See docs/wl75-protocol.md.

Frame: ``FE EF LEN payload... CHK`` with ``LEN = len(payload) + 1`` and
``CHK = LEN ^ payload[0] ^ ... ^ payload[-1]``. The first payload byte is the
command (request) or the response code (notification).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

SERVICE_UUID = "14839ac4-7d7e-415c-9a42-167340cf2339"
WRITE_UUID = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
NOTIFY_UUID = "0734594a-a8e7-4b1a-a6b1-cd5243059a57"

HEADER = b"\xfe\xef"
# Longest known frame is F4/F7/F8 with LEN 0x0C; allow some headroom.
MAX_LEN = 0x20

CMD_HANDSHAKE = 0x00
CMD_SETTINGS = 0x01
CMD_SET_TIME = 0x03
CMD_ALARM_STATUS = 0x04
CMD_ALARM_SET = 0x05
CMD_LIGHT_STATUS = 0x11
CMD_LIGHT_SWITCH = 0x12
CMD_LIGHT_BRIGHTNESS = 0x13
CMD_MOOD_STATUS = 0x16
CMD_MOOD_SWITCH = 0x17
CMD_MOOD_BRIGHTNESS = 0x18
CMD_MOOD_COLOR = 0x1B
CMD_MOOD_SCENE = 0x1C
CMD_SLEEP_STATUS = 0x1D
CMD_SLEEP_SWITCH = 0x1E
CMD_SLEEP_CONFIG = 0x1F

# Second byte of 1F: which half of the sleep configuration is sent
SLEEP_CONFIG_LIGHT = 1
SLEEP_CONFIG_SOUND = 2

HANDSHAKE_KEY = 0x75
HANDSHAKE_ANSWER = bytes([0xF0, HANDSHAKE_KEY])
ACK_OK = 0x01

# Unsolicited notification "timer finished": B0 <source>
CODE_TIMER_FINISHED = 0xB0
TIMER_RADIO = 1
TIMER_LIGHT = 2
TIMER_MOOD = 3
TIMER_SLEEP = 4

ALARM_IDS = (1, 2)

# Alarm days bit mask: bit 0 = Sunday ... bit 6 = Saturday
ALARM_DAY_BITS: dict[str, int] = {
    "monday": 1 << 1,
    "tuesday": 1 << 2,
    "wednesday": 1 << 3,
    "thursday": 1 << 4,
    "friday": 1 << 5,
    "saturday": 1 << 6,
    "sunday": 1 << 0,
}
ALARM_TONES: dict[int, str] = {
    1: "buzzer",
    2: "nature",
    3: "bells",
    4: "classic",
    5: "passion",
    6: "morning_lights",
    7: "joyful",
    8: "radio",
}
ALARM_WAKE_UP_LIGHTS: dict[int, str] = {0: "off", 1: "sunrise", 2: "energizing_light"}
# Snooze is sent as 1-based index into these minutes
ALARM_SNOOZE_MINUTES = (1, 2, 5, 10, 20, 30)

SLEEP_LIGHTS: dict[int, str] = {0: "off", 1: "sunset", 2: "mood", 3: "relax"}
SLEEP_SOUNDS: dict[int, str] = {
    0: "off",
    1: "radio",
    2: "harmony",
    3: "relax",
    4: "instrumental",
    5: "rain_drops",
}

MOOD_SCENES: dict[int, str] = {
    1: "Random",
    2: "Rainbow",
    3: "Rainbow Slow",
    4: "Fusion",
    5: "Pulse",
    6: "Wave",
    7: "Chill",
    8: "Action",
    9: "Forest",
    10: "Summer",
}


class ProtocolError(Exception):
    """A response could not be decoded."""


def response_code(cmd: int) -> int:
    """Return the response code the lamp answers a command with."""
    if cmd < 0x10:
        return 0xF0 | cmd
    return 0xE0 | (cmd & 0x0F)


def build_frame(payload: bytes | list[int]) -> bytes:
    """Wrap a payload into a WL75 frame."""
    length = len(payload) + 1
    checksum = length
    for b in payload:
        checksum ^= b
    return bytes([*HEADER, length, *payload, checksum])


def parse_frames(data: bytes) -> list[bytes]:
    """Extract all valid payloads from one notification.

    Under load the lamp bundles several frames into one notification and
    sometimes truncates them. Scan for the header, validate length and
    checksum, and skip garbage byte by byte.
    """
    payloads: list[bytes] = []
    i = 0
    while (i := data.find(HEADER, i)) != -1:
        if i + 2 >= len(data):
            break
        length = data[i + 2]
        end = i + 3 + length
        if length < 2 or length > MAX_LEN or end > len(data):
            i += 1
            continue
        payload = data[i + 3 : end - 1]
        checksum = length
        for b in payload:
            checksum ^= b
        if checksum != data[end - 1]:
            i += 1
            continue
        payloads.append(bytes(payload))
        i = end
    return payloads


def handshake() -> bytes:
    """Return the payload of the session handshake."""
    return bytes([CMD_HANDSHAKE, HANDSHAKE_KEY])


def query_settings() -> bytes:
    """Return the payload of the settings query."""
    return bytes([CMD_SETTINGS])


def set_time(now: datetime) -> bytes:
    """Return the payload that sets the lamp clock to ``now`` (local time)."""
    return bytes(
        [CMD_SET_TIME, now.second, now.minute, now.hour, now.day, now.month, now.year - 2000]
    )


def query_light() -> bytes:
    """Return the payload of the main light status query."""
    return bytes([CMD_LIGHT_STATUS])


def switch_light(on: bool) -> bytes:
    """Return the payload that switches the main light."""
    return bytes([CMD_LIGHT_SWITCH, int(on)])


def set_light_brightness(percent: int) -> bytes:
    """Return the payload that sets the main light brightness (1-100)."""
    return bytes([CMD_LIGHT_BRIGHTNESS, _clamp(percent, 1, 100)])


def query_mood() -> bytes:
    """Return the payload of the mood light status query."""
    return bytes([CMD_MOOD_STATUS])


def switch_mood(on: bool) -> bytes:
    """Return the payload that switches the mood light."""
    return bytes([CMD_MOOD_SWITCH, int(on)])


def set_mood_brightness(percent: int) -> bytes:
    """Return the payload that sets the mood light brightness (1-100)."""
    return bytes([CMD_MOOD_BRIGHTNESS, _clamp(percent, 1, 100)])


def set_mood_color(red: int, green: int, blue: int) -> bytes:
    """Return the payload that sets a fixed mood light color (ends a running scene)."""
    return bytes([CMD_MOOD_COLOR, *(_clamp(c, 0, 255) for c in (red, green, blue))])


def set_mood_scene(scene: int) -> bytes:
    """Return the payload that starts a mood light scene (see MOOD_SCENES)."""
    return bytes([CMD_MOOD_SCENE, _clamp(scene, 0, 10)])


def query_alarm(alarm_id: int) -> bytes:
    """Return the payload of the alarm query (alarm 1 or 2)."""
    return bytes([CMD_ALARM_STATUS, alarm_id])


def set_alarm(alarm: Alarm) -> bytes:
    """Return the payload that writes a complete alarm."""
    return bytes(
        [
            CMD_ALARM_SET,
            alarm.alarm_id,
            _clamp(alarm.minute, 0, 59),
            _clamp(alarm.hour, 0, 23),
            (0x80 if alarm.enabled else 0) | (alarm.days & 0x7F),
            _clamp(alarm.tone, 1, 8),
            _clamp(alarm.volume, 1, 10),
            _clamp(alarm.snooze, 1, len(ALARM_SNOOZE_MINUTES)),
            _clamp(alarm.wake_up_light, 0, 2),
            _clamp(alarm.sunrise_minutes, 2, 60),
            _clamp(alarm.brightness, 1, 100),
        ]
    )


def query_sleep() -> bytes:
    """Return the payload of the sleep function status query."""
    return bytes([CMD_SLEEP_STATUS])


def switch_sleep(on: bool) -> bytes:
    """Return the payload that starts or stops the sleep function."""
    return bytes([CMD_SLEEP_SWITCH, int(on)])


def set_sleep_light(minutes: int, light: int, brightness: int) -> bytes:
    """Return the payload that sets duration and light of a running sleep function."""
    return bytes(
        [
            CMD_SLEEP_CONFIG,
            SLEEP_CONFIG_LIGHT,
            _clamp(minutes, 1, 60),
            _clamp(light, 0, 3),
            _clamp(brightness, 10, 100),
        ]
    )


def set_sleep_sound(sound: int, volume: int, fade_out: bool) -> bytes:
    """Return the payload that sets the sound of a running sleep function."""
    return bytes(
        [
            CMD_SLEEP_CONFIG,
            SLEEP_CONFIG_SOUND,
            _clamp(sound, 0, 5),
            _clamp(volume, 1, 10),
            int(fade_out),
        ]
    )


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


@dataclass(frozen=True, slots=True)
class Settings:
    """Device settings (response F1)."""

    display: int
    date_format: int
    time_auto: bool
    feedback: int

    @classmethod
    def from_payload(cls, payload: bytes) -> Settings:
        data = _data(payload, response_code(CMD_SETTINGS), 4)
        return cls(display=data[0], date_format=data[1], time_auto=data[2] == 0, feedback=data[3])


@dataclass(frozen=True, slots=True)
class LightState:
    """Main light status (response E1)."""

    is_on: bool
    brightness: int
    timer_on: bool
    timer_minutes: int

    @classmethod
    def from_payload(cls, payload: bytes) -> LightState:
        data = _data(payload, response_code(CMD_LIGHT_STATUS), 4)
        return cls(
            is_on=data[0] != 0,
            brightness=data[1],
            timer_on=data[2] != 0,
            timer_minutes=data[3],
        )


@dataclass(frozen=True, slots=True)
class MoodState:
    """Mood light status (response E6).

    While a scene is running ``rgb`` is the scene's current color. A fixed
    color (1B) resets ``scene`` to 0.
    """

    is_on: bool
    brightness: int
    timer_on: bool
    timer_minutes: int
    rgb: tuple[int, int, int]
    scene: int

    @classmethod
    def from_payload(cls, payload: bytes) -> MoodState:
        data = _data(payload, response_code(CMD_MOOD_STATUS), 8)
        return cls(
            is_on=data[0] != 0,
            brightness=data[1],
            timer_on=data[2] != 0,
            timer_minutes=data[3],
            rgb=(data[4], data[5], data[6]),
            scene=data[7],
        )


@dataclass(frozen=True, slots=True)
class Alarm:
    """An alarm (response F4, request 05)."""

    alarm_id: int
    minute: int
    hour: int
    enabled: bool
    days: int
    tone: int
    volume: int
    snooze: int
    wake_up_light: int
    sunrise_minutes: int
    brightness: int

    @classmethod
    def from_payload(cls, payload: bytes) -> Alarm:
        data = _data(payload, response_code(CMD_ALARM_STATUS), 10)
        return cls(
            alarm_id=data[0] & 0x7F,
            minute=data[1],
            hour=data[2],
            enabled=bool(data[3] & 0x80),
            days=data[3] & 0x7F,
            tone=data[4],
            volume=data[5],
            snooze=data[6],
            wake_up_light=data[7],
            sunrise_minutes=data[8],
            brightness=data[9],
        )

    def with_day(self, bit: int, on: bool) -> Alarm:
        """Return a copy with one day bit set or cleared."""
        return replace(self, days=self.days | bit if on else self.days & ~bit)


@dataclass(frozen=True, slots=True)
class SleepState:
    """Sleep function status (response ED).

    While the sleep function runs, ``minutes`` is the remaining time and
    ``brightness`` the current, fading brightness. While it is off, ``minutes``
    is always 2: the lamp does not keep the duration (see docs, section 14).
    """

    is_on: bool
    minutes: int
    light: int
    brightness: int
    sound: int
    volume: int
    fade_out: bool

    @classmethod
    def from_payload(cls, payload: bytes) -> SleepState:
        data = _data(payload, response_code(CMD_SLEEP_STATUS), 7)
        return cls(
            is_on=data[0] == 1,
            minutes=data[1],
            light=data[2],
            brightness=data[3],
            sound=data[4],
            volume=data[5],
            fade_out=data[6] == 1,
        )


def _data(payload: bytes, code: int, size: int) -> bytes:
    if len(payload) < size + 1 or payload[0] != code:
        raise ProtocolError(f"Unexpected response {payload.hex(' ')}, expected 0x{code:02x}")
    return payload[1 : size + 1]

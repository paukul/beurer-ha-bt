"""A fake WL75 that answers like the real lamp, for driving WL75Device in tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from custom_components.beurer_wl75 import protocol


class FakeLamp:
    """Stands in for BleakClientWithServiceCache and answers written frames."""

    def __init__(self) -> None:
        self.is_connected = False
        self.written: list[bytes] = []
        self.light = bytearray.fromhex("00 51 00 0a")
        self.mood = bytearray.fromhex("00 64 00 00 ff a4 00 02")  # last scene: Rainbow
        self.settings = bytes.fromhex("00 00 00 01")
        # Real alarms of the test lamp: 1 = 07:00 Mo-Fr enabled, 2 = 08:45 Sunday disabled
        self.alarms = {
            1: bytearray.fromhex("01 00 07 be 05 06 03 01 0a 50"),
            2: bytearray.fromhex("02 2d 08 01 01 05 03 01 0a 50"),
        }
        # Sleep off: minutes always reads 2 while off
        self.sleep = bytearray.fromhex("00 02 01 63 00 06 01")
        self.connects = 0
        # Number of upcoming requests to leave unanswered
        self.drop_answers = 0
        self._notify: Callable[[object, bytearray], None] | None = None
        self.disconnected_callback: Callable[[FakeLamp], None] | None = None

    async def establish_connection(
        self, client_class, device, name, disconnected_callback, **kwargs
    ):
        self.connects += 1
        self.is_connected = True
        self.disconnected_callback = disconnected_callback
        return self

    async def start_notify(self, uuid: str, callback) -> None:
        assert uuid == protocol.NOTIFY_UUID
        self._notify = callback

    async def disconnect(self) -> None:
        self.is_connected = False

    def drop_link(self) -> None:
        self.is_connected = False
        assert self.disconnected_callback is not None
        self.disconnected_callback(self)

    def push(self, raw: bytes) -> None:
        assert self._notify is not None
        self._notify(None, bytearray(raw))

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool) -> None:
        assert uuid == protocol.WRITE_UUID
        assert response is False
        (payload,) = protocol.parse_frames(data)
        self.written.append(payload)
        if self.drop_answers:
            self.drop_answers -= 1
            return
        answer = self._answer(payload)
        asyncio.get_running_loop().call_soon(self.push, protocol.build_frame(answer))

    def _answer(self, payload: bytes) -> bytes:
        cmd, args = payload[0], payload[1:]
        code = protocol.response_code(cmd)
        match cmd:
            case protocol.CMD_HANDSHAKE:
                return bytes([code, *args])
            case protocol.CMD_SETTINGS:
                return bytes([code, *self.settings])
            case protocol.CMD_LIGHT_STATUS:
                return bytes([code, *self.light])
            case protocol.CMD_MOOD_STATUS:
                return bytes([code, *self.mood])
            case protocol.CMD_LIGHT_SWITCH:
                self.light[0] = args[0]
            case protocol.CMD_LIGHT_BRIGHTNESS:
                self.light[1] = args[0]
            case protocol.CMD_MOOD_SWITCH:
                self.mood[0] = args[0]
            case protocol.CMD_MOOD_BRIGHTNESS:
                self.mood[1] = args[0]
            case protocol.CMD_MOOD_COLOR:
                self.mood[4:7] = args
                self.mood[7] = 0
            case protocol.CMD_MOOD_SCENE:
                self.mood[7] = args[0]
            case protocol.CMD_ALARM_STATUS:
                return bytes([code, *self.alarms[args[0]]])
            case protocol.CMD_ALARM_SET:
                self.alarms[args[0]] = bytearray(args)
            case protocol.CMD_SLEEP_STATUS:
                return bytes([code, *self.sleep])
            case protocol.CMD_SLEEP_SWITCH:
                # Starts with the default 2 minutes (reports the remaining 1),
                # forgets the duration when stopped.
                self.sleep[0] = args[0]
                self.sleep[1] = 1 if args[0] else 2
            case protocol.CMD_SLEEP_CONFIG:
                if not self.sleep[0]:
                    return bytes([code, 0])  # only accepted while running
                if args[0] == protocol.SLEEP_CONFIG_LIGHT:
                    self.sleep[1] = args[1] - 1  # remaining minutes
                    self.sleep[2:4] = args[2:4]
                else:
                    self.sleep[4:7] = args[1:4]
        return bytes([code, protocol.ACK_OK])

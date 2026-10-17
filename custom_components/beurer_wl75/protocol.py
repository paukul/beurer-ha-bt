"""BLE protocol of the Beurer WL75 wake-up light.

Pure module without Home Assistant imports. See docs/wl75-protocol.md.

Frame: ``FE EF LEN payload... CHK`` with ``LEN = len(payload) + 1`` and
``CHK = LEN ^ payload[0] ^ ... ^ payload[-1]``. The first payload byte is the
command (request) or the response code (notification).
"""

from __future__ import annotations

from dataclasses import dataclass
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
CMD_LIGHT_STATUS = 0x11
CMD_LIGHT_SWITCH = 0x12
CMD_LIGHT_BRIGHTNESS = 0x13
CMD_MOOD_STATUS = 0x16
CMD_MOOD_SWITCH = 0x17
CMD_MOOD_BRIGHTNESS = 0x18
CMD_MOOD_COLOR = 0x1B
CMD_MOOD_SCENE = 0x1C

HANDSHAKE_KEY = 0x75
HANDSHAKE_ANSWER = bytes([0xF0, HANDSHAKE_KEY])
ACK_OK = 0x01

# Unsolicited notification "timer finished": B0 <source>
CODE_TIMER_FINISHED = 0xB0
TIMER_RADIO = 1
TIMER_LIGHT = 2
TIMER_MOOD = 3
TIMER_SLEEP = 4

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


def _data(payload: bytes, code: int, size: int) -> bytes:
    if len(payload) < size + 1 or payload[0] != code:
        raise ProtocolError(f"Unexpected response {payload.hex(' ')}, expected 0x{code:02x}")
    return payload[1 : size + 1]

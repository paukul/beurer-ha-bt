"""Protocol tests with frames recorded from a real WL75 (docs/wl75-protocol.md §10-12)."""

from datetime import datetime

import pytest

from custom_components.beurer_wl75 import protocol
from custom_components.beurer_wl75.protocol import LightState, MoodState, Settings


def h(text: str) -> bytes:
    return bytes.fromhex(text)


@pytest.mark.parametrize(
    ("payload", "frame"),
    [
        (protocol.handshake(), "fe ef 03 00 75 76"),
        (protocol.query_settings(), "fe ef 02 01 03"),
        (protocol.query_light(), "fe ef 02 11 13"),
        (protocol.query_mood(), "fe ef 02 16 14"),
        (protocol.switch_light(True), "fe ef 03 12 01 10"),
        (protocol.switch_light(False), "fe ef 03 12 00 11"),
        (protocol.set_light_brightness(0x50), "fe ef 03 13 50 40"),
        (protocol.set_light_brightness(0x51), "fe ef 03 13 51 41"),
        (protocol.switch_mood(True), "fe ef 03 17 01 15"),
        (protocol.switch_mood(False), "fe ef 03 17 00 14"),
        (protocol.set_mood_color(0xFF, 0x08, 0x00), "fe ef 05 1b ff 08 00 e9"),
        (protocol.set_mood_color(0x18, 0xFF, 0x00), "fe ef 05 1b 18 ff 00 f9"),
        (protocol.set_mood_color(0x00, 0x00, 0xFF), "fe ef 05 1b 00 00 ff e1"),
        (protocol.set_mood_scene(2), "fe ef 03 1c 02 1d"),
        # 17:45:31, 17.10.2026 and 17:48:13 as sent by the app
        (protocol.set_time(datetime(2026, 10, 17, 17, 45, 31)), "fe ef 08 03 1f 2d 11 11 0a 1a 29"),
        (protocol.set_time(datetime(2026, 10, 17, 17, 48, 13)), "fe ef 08 03 0d 30 11 11 0a 1a 26"),
    ],
)
def test_build_frame_matches_app(payload: bytes, frame: str) -> None:
    assert protocol.build_frame(payload) == h(frame)


@pytest.mark.parametrize(
    ("cmd", "code"),
    [
        (0x00, 0xF0),
        (0x01, 0xF1),
        (0x03, 0xF3),
        (0x0D, 0xFD),
        (0x11, 0xE1),
        (0x16, 0xE6),
        (0x1B, 0xEB),
        (0x1C, 0xEC),
        (0x1F, 0xEF),
    ],
)
def test_response_code(cmd: int, code: int) -> None:
    assert protocol.response_code(cmd) == code


def test_clamping() -> None:
    assert protocol.set_light_brightness(0) == h("13 01")
    assert protocol.set_light_brightness(255) == h("13 64")
    assert protocol.set_mood_scene(11) == h("1c 0a")


def test_parse_single_frames() -> None:
    assert protocol.parse_frames(h("fe ef 03 f0 75 86")) == [protocol.HANDSHAKE_ANSWER]
    assert protocol.parse_frames(h("fe ef 03 e2 01 e0")) == [h("e2 01")]
    assert protocol.parse_frames(h("fe ef 0c f4 01 00 07 be 05 06 03 01 0a 50 1b")) == [
        h("f4 01 00 07 be 05 06 03 01 0a 50")
    ]


@pytest.mark.parametrize(
    ("notification", "count"),
    [
        # Bundled and truncated answers after rapid slider writes (HCI capture)
        ("fe ef 03 e3 01 e1 fe ef 03 e3 01 e1 fe ef 03 fe ef", 2),
        ("fe ef 03 e3 01 e1 fe ef 03 e3 01 e1 fe ef 03 e3 01", 2),
        ("fe ef 03 eb 01 e9 fe ef 03 eb 01 e9 fe ef 03", 2),
        ("fe ef 03 eb 01 e9 fe ef 03 eb 01 e9 fe ef 03 fe ef", 2),
    ],
)
def test_parse_garbled_notifications(notification: str, count: int) -> None:
    payloads = protocol.parse_frames(h(notification))
    assert len(payloads) == count
    assert len(set(payloads)) == 1
    assert payloads[0][1] == protocol.ACK_OK


def test_parse_drops_bad_checksum_and_resyncs() -> None:
    assert protocol.parse_frames(h("fe ef 03 e2 01 00 fe ef 03 e2 01 e0")) == [h("e2 01")]
    assert protocol.parse_frames(h("00 fe fe ef 03 e2 01 e0 ff")) == [h("e2 01")]
    assert protocol.parse_frames(h("fe ef ff 00")) == []
    assert protocol.parse_frames(b"") == []


def test_settings() -> None:
    (payload,) = protocol.parse_frames(h("fe ef 06 f1 00 00 00 01 f6"))
    assert Settings.from_payload(payload) == Settings(
        display=0, date_format=0, time_auto=True, feedback=1
    )


def test_light_state() -> None:
    (payload,) = protocol.parse_frames(h("fe ef 06 e1 00 51 00 0a bc"))
    assert LightState.from_payload(payload) == LightState(
        is_on=False, brightness=81, timer_on=False, timer_minutes=10
    )


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (
            "fe ef 0a e6 00 64 00 00 ff a4 00 02 d1",
            MoodState(False, 100, False, 0, (255, 164, 0), 2),
        ),
        (
            "fe ef 0a e6 00 64 00 00 81 00 ef 02 e4",
            MoodState(False, 100, False, 0, (129, 0, 239), 2),
        ),
        ("fe ef 0a e6 01 64 00 00 ff 00 00 02 74", MoodState(True, 100, False, 0, (255, 0, 0), 2)),
        (
            "fe ef 0a e6 01 64 00 00 ff 6a 00 02 1e",
            MoodState(True, 100, False, 0, (255, 106, 0), 2),
        ),
    ],
)
def test_mood_state(frame: str, expected: MoodState) -> None:
    (payload,) = protocol.parse_frames(h(frame))
    assert MoodState.from_payload(payload) == expected


def test_state_rejects_wrong_code() -> None:
    with pytest.raises(protocol.ProtocolError):
        LightState.from_payload(h("e6 00 64 00 00 ff a4 00 02"))
    with pytest.raises(protocol.ProtocolError):
        MoodState.from_payload(h("e6 01"))

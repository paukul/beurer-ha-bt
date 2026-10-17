"""Tests for the connection handling against a fake lamp."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.beurer_wl75 import device as device_module, protocol
from custom_components.beurer_wl75.device import WL75Device, WL75Error

from .fake_lamp import FakeLamp

NOW = datetime(2026, 10, 17, 17, 45, 31)


@pytest.fixture
def lamp():
    lamp = FakeLamp()
    with patch.object(device_module, "establish_connection", lamp.establish_connection):
        yield lamp


@pytest.fixture
def wl75(lamp):
    ble_device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    ble_device.name = "WL75"
    return WL75Device(ble_device, now=lambda: NOW, idle_disconnect=None)


async def test_connect_sequence_and_update(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    assert [p.hex(" ") for p in lamp.written] == [
        "00 75",
        "01",
        "03 1f 2d 11 11 0a 1a",
        "11",
        "16",
    ]
    assert wl75.settings is not None and wl75.settings.time_auto
    assert wl75.light == protocol.LightState(False, 81, False, 10)
    assert wl75.mood is not None and wl75.mood.rgb == (255, 164, 0)
    assert wl75.mood_scene is None  # off


async def test_no_time_sync_when_manual(lamp: FakeLamp, wl75: WL75Device) -> None:
    lamp.settings = bytes.fromhex("00 00 01 01")
    await wl75.update()
    assert [p[0] for p in lamp.written] == [0x00, 0x01, 0x11, 0x16]


async def test_reuses_connection(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    await wl75.update()
    assert lamp.connects == 1


async def test_turn_on_light_with_brightness(lamp: FakeLamp, wl75: WL75Device) -> None:
    callback = MagicMock()
    wl75.register_callback(callback)
    await wl75.turn_on_light(30)
    assert [p.hex(" ") for p in lamp.written[3:]] == ["12 01", "13 1e", "11", "16"]
    assert wl75.light == protocol.LightState(True, 30, False, 10)
    callback.assert_called_once()


async def test_mood_color_ends_scene(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.turn_on_mood()
    assert wl75.mood_scene == 2
    lamp.written.clear()
    await wl75.turn_on_mood(rgb=(255, 0, 0), brightness=50)
    # already on: no second switch command
    assert [p.hex(" ") for p in lamp.written] == ["16", "18 32", "1b ff 00 00", "11", "16"]
    assert wl75.mood is not None and wl75.mood.rgb == (255, 0, 0)
    assert wl75.mood_scene is None
    await wl75.turn_on_mood(scene=9)
    assert wl75.mood_scene == 9


async def test_retry_after_lost_answer(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    lamp.written.clear()
    lamp.drop_answers = 1
    with patch.object(device_module, "RESPONSE_TIMEOUT", 0.05):
        await wl75.turn_off_light()
    assert [p.hex(" ") for p in lamp.written] == ["12 00", "12 00", "11", "16"]


async def test_gives_up_after_retries(lamp: FakeLamp, wl75: WL75Device) -> None:
    lamp.drop_answers = 2
    with patch.object(device_module, "RESPONSE_TIMEOUT", 0.05), pytest.raises(WL75Error):
        await wl75.update()
    assert not lamp.is_connected


async def test_reconnects_after_link_loss(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    lamp.drop_link()
    await wl75.update()
    assert lamp.connects == 2


async def test_garbled_and_unsolicited_notifications(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    callback = MagicMock()
    wl75.register_callback(callback)
    lamp.push(bytes.fromhex("fe ef 03 e3 01 e1 fe ef 03 e3 01 e1 fe ef 03 fe ef"))
    callback.assert_not_called()
    lamp.push(protocol.build_frame(bytes.fromhex("e1 01 64 00 0a")))
    assert wl75.light is not None and wl75.light.is_on and wl75.light.brightness == 100
    # B0 02: light timer finished
    lamp.push(protocol.build_frame(bytes.fromhex("b0 02")))
    assert not wl75.light.is_on
    assert callback.call_count == 2


async def test_rejected_command(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    lamp._answer = lambda payload: bytes([protocol.response_code(payload[0]), 0x00])
    with pytest.raises(WL75Error):
        await wl75.turn_off_light()


async def test_idle_disconnect(lamp: FakeLamp) -> None:
    ble_device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    wl75 = WL75Device(ble_device, now=lambda: NOW, idle_disconnect=0.01)
    await wl75.update()
    assert lamp.is_connected

    await asyncio.sleep(0.05)
    assert not lamp.is_connected
    await wl75.update()
    assert lamp.connects == 2
    await wl75.stop()

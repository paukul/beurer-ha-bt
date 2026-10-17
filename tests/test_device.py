"""Tests for the connection handling against a fake lamp."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
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
        "04 01",
        "04 02",
        "1d",
    ]
    assert wl75.settings is not None and wl75.settings.time_auto
    assert wl75.light == protocol.LightState(False, 81, False, 10)
    assert wl75.mood is not None and wl75.mood.rgb == (255, 164, 0)
    assert wl75.mood_scene is None  # off


async def test_no_time_sync_when_manual(lamp: FakeLamp, wl75: WL75Device) -> None:
    lamp.settings = bytes.fromhex("00 00 01 01")
    await wl75.update()
    assert [p[0] for p in lamp.written] == [0x00, 0x01, 0x11, 0x16, 0x04, 0x04, 0x1D]


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


async def test_update_reads_alarms_and_sleep(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    assert wl75.alarms[1] == protocol.Alarm(1, 0, 7, True, 0x3E, 5, 6, 3, 1, 10, 80)
    assert wl75.alarms[2] == protocol.Alarm(2, 45, 8, False, 0x01, 1, 5, 3, 1, 10, 80)
    assert wl75.sleep == protocol.SleepState(False, 2, 1, 99, 0, 6, True)
    assert not wl75.sleep_running and wl75.sleep_end is None


async def test_modify_alarm_starts_from_fresh_state(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    # Changed in the app meanwhile: volume 9. Must survive our change.
    lamp.alarms[1][5] = 9
    lamp.written.clear()
    callback = MagicMock()
    wl75.register_callback(callback)

    await wl75.modify_alarm(1, lambda a: replace(a, hour=6, minute=30))

    assert [p.hex(" ") for p in lamp.written] == [
        "04 01",
        "05 01 1e 06 be 05 09 03 01 0a 50",
        "04 01",
    ]
    assert wl75.alarms[1].hour == 6 and wl75.alarms[1].volume == 9
    callback.assert_called_once()


async def test_alarm_enable_and_days(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.modify_alarm(1, lambda a: replace(a, enabled=False))
    assert lamp.alarms[1][3] == 0x3E
    saturday = protocol.ALARM_DAY_BITS["saturday"]
    await wl75.modify_alarm(1, lambda a: a.with_day(saturday, True))
    assert lamp.alarms[1][3] == 0x7E
    await wl75.modify_alarm(1, lambda a: a.with_day(protocol.ALARM_DAY_BITS["monday"], False))
    assert lamp.alarms[1][3] == 0x7C


async def test_start_sleep_sends_settings(lamp: FakeLamp, wl75: WL75Device) -> None:
    wl75.restore_sleep_settings(minutes=30, light=1, brightness=80, sound=5, volume=4)
    await wl75.start_sleep()
    assert [p.hex(" ") for p in lamp.written[3:]] == [
        "1e 01",
        "1f 01 1e 01 50",
        "1f 02 05 04 01",
        "11",
        "16",
        "1d",
    ]
    assert wl75.sleep_running
    assert wl75.sleep is not None and wl75.sleep.minutes == 29
    assert wl75.sleep_end == NOW + timedelta(minutes=30)
    await wl75.stop()


async def test_sleep_settings_while_off_are_only_stored(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.update()
    lamp.written.clear()
    await wl75.set_sleep_settings(minutes=45, sound=2)
    # The lamp rejects 1F while the sleep function is off.
    assert lamp.written == []
    assert wl75.sleep_settings.minutes == 45


async def test_sleep_settings_while_running_are_sent(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.start_sleep()
    lamp.written.clear()
    await wl75.set_sleep_settings(volume=8)
    assert [p.hex(" ") for p in lamp.written] == ["1f 02 00 08 01", "1d"]
    assert wl75.sleep_end == NOW + timedelta(minutes=30)

    lamp.written.clear()
    await wl75.set_sleep_settings(minutes=10)
    assert [p.hex(" ") for p in lamp.written] == ["1f 01 0a 01 64", "1d"]
    assert wl75.sleep_end == NOW + timedelta(minutes=10)
    await wl75.stop()


async def test_sleep_settings_rejected_when_ended(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.start_sleep()
    lamp.sleep[0] = 0  # ended on the lamp without us noticing
    await wl75.set_sleep_settings(volume=8)
    assert not wl75.sleep_running and wl75.sleep_end is None
    assert wl75.sleep_settings.volume == 8


async def test_sleep_end_is_tracked_without_connection(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.start_sleep()
    handle = wl75._sleep_handle
    assert handle is not None
    assert handle.when() - asyncio.get_running_loop().time() == pytest.approx(1800, abs=1)
    callback = MagicMock()
    wl75.register_callback(callback)
    lamp.written.clear()

    # Fire the timer now instead of waiting 30 minutes.
    handle.cancel()
    wl75._on_sleep_end()

    assert not wl75.sleep_running and wl75.sleep_end is None
    callback.assert_called_once()
    assert lamp.written == []


async def test_sleep_timer_finished_notification(lamp: FakeLamp, wl75: WL75Device) -> None:
    await wl75.start_sleep()
    lamp.push(protocol.build_frame(bytes.fromhex("b0 04")))
    assert not wl75.sleep_running and wl75.sleep_end is None


async def test_sleep_started_elsewhere(lamp: FakeLamp, wl75: WL75Device) -> None:
    lamp.sleep = bytearray.fromhex("01 0a 01 50 00 06 01")  # running, 10 min left
    await wl75.update()
    assert wl75.sleep_running
    assert wl75.sleep_end == NOW + timedelta(minutes=11)
    lamp.sleep[0] = 0
    await wl75.update()
    assert wl75.sleep_end is None and wl75._sleep_handle is None


async def test_sleep_light_change_keeps_countdown(lamp: FakeLamp) -> None:
    now = NOW
    ble_device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    wl75 = WL75Device(ble_device, now=lambda: now)
    await wl75.start_sleep()
    now = NOW + timedelta(minutes=24, seconds=30)
    lamp.written.clear()

    await wl75.set_sleep_settings(brightness=50)

    # 5.5 minutes left: send 6, not the full 30. That restarts the countdown
    # on the lamp, so the end moves by half a minute.
    assert [p.hex(" ") for p in lamp.written] == ["1f 01 06 01 32", "1d"]
    assert wl75.sleep_end == now + timedelta(minutes=6)
    await wl75.stop()


async def test_start_sleep_rejected_setting(lamp: FakeLamp, wl75: WL75Device) -> None:
    original = lamp._answer

    def reject_sound(payload: bytes) -> bytes | None:
        if payload[:2] == bytes([protocol.CMD_SLEEP_CONFIG, protocol.SLEEP_CONFIG_SOUND]):
            return bytes([protocol.response_code(payload[0]), 0x00])
        return original(payload)

    lamp._answer = reject_sound
    with pytest.raises(WL75Error):
        await wl75.start_sleep()
    # Runs with the light settings: shown as on, end estimated from the lamp.
    assert wl75.sleep_running
    assert wl75.sleep_end == NOW + timedelta(minutes=30)
    await wl75.stop()

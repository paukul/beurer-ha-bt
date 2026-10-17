"""Config flow and setup tests running inside Home Assistant with a fake lamp."""

from datetime import timedelta
from unittest.mock import patch

from bleak.backends.device import BLEDevice
from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGB_COLOR
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import ATTR_ENTITY_ID, CONF_ADDRESS, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.beurer_wl75 import device as device_module
from custom_components.beurer_wl75.const import CONF_POLL_INTERVAL, DOMAIN

from .fake_lamp import FakeLamp

ADDRESS = "AA:BB:CC:DD:EE:FF"
BLE_DEVICE = BLEDevice(ADDRESS, "WL75", None)
SERVICE_INFO = BluetoothServiceInfoBleak(
    name="WL75",
    address=ADDRESS,
    rssi=-60,
    manufacturer_data={},
    service_data={},
    service_uuids=["00007336-0000-1000-8000-00805f9b34fb"],
    source="local",
    device=BLE_DEVICE,
    advertisement=None,
    connectable=True,
    time=0,
    tx_power=None,
)


@pytest.fixture
def lamp():
    lamp = FakeLamp()
    with patch.object(device_module, "establish_connection", lamp.establish_connection):
        yield lamp


@pytest.fixture(autouse=True)
def bluetooth(enable_bluetooth):
    """Start the (mocked) bluetooth stack the integration depends on."""


async def test_bluetooth_discovery_flow(hass: HomeAssistant, lamp: FakeLamp) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=SERVICE_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    with patch(
        "custom_components.beurer_wl75.bluetooth.async_ble_device_from_address",
        return_value=BLE_DEVICE,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "WL75"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["result"].unique_id == ADDRESS


async def test_user_flow_cannot_connect(hass: HomeAssistant, lamp: FakeLamp) -> None:
    with patch(
        "custom_components.beurer_wl75.config_flow.async_discovered_service_info",
        return_value=[SERVICE_INFO],
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    lamp.drop_answers = 10
    with patch.object(device_module, "RESPONSE_TIMEOUT", 0.05):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_no_devices(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.beurer_wl75.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_lights(hass: HomeAssistant, lamp: FakeLamp) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="WL75", unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.beurer_wl75.bluetooth.async_ble_device_from_address",
        return_value=BLE_DEVICE,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    main = hass.states.get("light.wl75")
    mood = hass.states.get("light.wl75_mood_light")
    assert main is not None and main.state == STATE_OFF
    assert mood is not None and mood.state == STATE_OFF

    await hass.services.async_call(
        "light", "turn_on", {ATTR_ENTITY_ID: "light.wl75", ATTR_BRIGHTNESS: 255}, blocking=True
    )
    main = hass.states.get("light.wl75")
    assert main.state == STATE_ON
    assert main.attributes[ATTR_BRIGHTNESS] == 255
    assert lamp.light[:2] == bytes([1, 100])

    await hass.services.async_call(
        "light", "turn_on", {ATTR_ENTITY_ID: "light.wl75_mood_light"}, blocking=True
    )
    mood = hass.states.get("light.wl75_mood_light")
    assert mood.state == STATE_ON
    assert mood.attributes[ATTR_EFFECT] == "Rainbow"

    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: "light.wl75_mood_light", ATTR_RGB_COLOR: (0, 0, 255)},
        blocking=True,
    )
    mood = hass.states.get("light.wl75_mood_light")
    assert mood.attributes[ATTR_RGB_COLOR] == (0, 0, 255)
    assert mood.attributes[ATTR_EFFECT] is None

    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: "light.wl75_mood_light", ATTR_EFFECT: "Forest"},
        blocking=True,
    )
    assert hass.states.get("light.wl75_mood_light").attributes[ATTR_EFFECT] == "Forest"
    assert lamp.mood[7] == 9

    await hass.services.async_call(
        "light", "turn_off", {ATTR_ENTITY_ID: "light.wl75_mood_light"}, blocking=True
    )
    assert hass.states.get("light.wl75_mood_light").state == STATE_OFF

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not lamp.is_connected


async def test_poll_interval_option(hass: HomeAssistant, lamp: FakeLamp) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="WL75", unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.beurer_wl75.bluetooth.async_ble_device_from_address",
        return_value=BLE_DEVICE,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    # Default: state is read at startup and after commands only.
    assert coordinator.update_interval is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 15}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_POLL_INTERVAL: 15}
    assert coordinator.update_interval == timedelta(minutes=15)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 0}
    )
    await hass.async_block_till_done()
    assert coordinator.update_interval is None

    await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_retry_when_not_found(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state.name == "SETUP_RETRY"


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="WL75", unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.beurer_wl75.bluetooth.async_ble_device_from_address",
        return_value=BLE_DEVICE,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_alarm_entities(hass: HomeAssistant, lamp: FakeLamp) -> None:
    entry = await _setup(hass)

    assert hass.states.get("switch.wl75_alarm_1").state == STATE_ON
    assert hass.states.get("switch.wl75_alarm_2").state == STATE_OFF
    assert hass.states.get("time.wl75_alarm_1_time").state == "07:00:00"
    assert hass.states.get("time.wl75_alarm_2_time").state == "08:45:00"
    assert hass.states.get("switch.wl75_alarm_1_monday").state == STATE_ON
    assert hass.states.get("switch.wl75_alarm_1_sunday").state == STATE_OFF
    assert hass.states.get("select.wl75_alarm_1_tone").state == "passion"
    assert hass.states.get("select.wl75_alarm_1_wake_up_light").state == "sunrise"
    assert hass.states.get("select.wl75_alarm_1_snooze").state == "5"
    assert hass.states.get("number.wl75_alarm_1_volume").state == "6"
    assert hass.states.get("number.wl75_alarm_1_sunrise_duration").state == "10"
    assert hass.states.get("number.wl75_alarm_1_light_brightness").state == "80"

    await hass.services.async_call(
        "time",
        "set_value",
        {ATTR_ENTITY_ID: "time.wl75_alarm_2_time", "time": "06:15"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.wl75_alarm_2_saturday"}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.wl75_alarm_2"}, blocking=True
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.wl75_alarm_2_tone", "option": "radio"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.wl75_alarm_2_snooze", "option": "10"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.wl75_alarm_2_sunrise_duration", "value": 30},
        blocking=True,
    )
    assert lamp.alarms[2] == bytearray.fromhex("02 0f 06 c1 08 05 04 01 1e 50")
    assert hass.states.get("time.wl75_alarm_2_time").state == "06:15:00"
    assert hass.states.get("switch.wl75_alarm_2").state == STATE_ON
    assert hass.states.get("switch.wl75_alarm_2_saturday").state == STATE_ON

    await hass.config_entries.async_unload(entry.entry_id)


async def test_sleep_entities(hass: HomeAssistant, lamp: FakeLamp) -> None:
    entry = await _setup(hass)

    # Seeded from the lamp (off), except the duration it forgets.
    assert hass.states.get("switch.wl75_sleep_function").state == STATE_OFF
    assert hass.states.get("number.wl75_sleep_duration").state == "30"
    assert hass.states.get("select.wl75_sleep_light").state == "sunset"
    assert hass.states.get("number.wl75_sleep_light_brightness").state == "99"
    assert hass.states.get("select.wl75_sleep_sound").state == "off"
    assert hass.states.get("number.wl75_sleep_volume").state == "6"
    assert hass.states.get("switch.wl75_sleep_sound_fade_out").state == STATE_ON
    assert hass.states.get("sensor.wl75_sleep_function_end").state == "unknown"

    # While off, settings are only stored.
    lamp.written.clear()
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.wl75_sleep_duration", "value": 20},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.wl75_sleep_sound", "option": "rain_drops"},
        blocking=True,
    )
    assert lamp.written == []
    assert hass.states.get("number.wl75_sleep_duration").state == "20"

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.wl75_sleep_function"}, blocking=True
    )
    assert hass.states.get("switch.wl75_sleep_function").state == STATE_ON
    assert lamp.sleep[:5] == bytearray.fromhex("01 13 01 63 05")
    assert hass.states.get("sensor.wl75_sleep_function_end").state != "unknown"

    # While running, settings go to the lamp right away.
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.wl75_sleep_volume", "value": 3},
        blocking=True,
    )
    assert lamp.sleep[5] == 3

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.wl75_sleep_function"}, blocking=True
    )
    assert hass.states.get("switch.wl75_sleep_function").state == STATE_OFF
    assert hass.states.get("sensor.wl75_sleep_function_end").state == "unknown"
    # Still 20, although the lamp reports 2 minutes when off.
    assert hass.states.get("number.wl75_sleep_duration").state == "20"

    await hass.config_entries.async_unload(entry.entry_id)


async def test_sleep_settings_restored(hass: HomeAssistant, lamp: FakeLamp) -> None:
    mock_restore_cache(
        hass,
        [
            State("number.wl75_sleep_duration", "45"),
            State("select.wl75_sleep_sound", "harmony"),
            State("switch.wl75_sleep_sound_fade_out", STATE_OFF),
            State("number.wl75_sleep_volume", "unavailable"),
        ],
    )
    entry = await _setup(hass)
    assert entry.runtime_data.device.sleep_settings == device_module.SleepSettings(
        minutes=45, light=1, brightness=99, sound=2, volume=6, fade_out=False
    )
    assert hass.states.get("number.wl75_sleep_duration").state == "45"
    await hass.config_entries.async_unload(entry.entry_id)

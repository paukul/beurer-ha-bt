"""The Beurer WL75 integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import dt as dt_util

from .const import DOMAIN, IDLE_DISCONNECT_SECONDS
from .coordinator import WL75ConfigEntry, WL75Coordinator, WL75Data, poll_interval
from .device import WL75Device

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


async def async_setup_entry(hass: HomeAssistant, entry: WL75ConfigEntry) -> bool:
    """Set up a Beurer WL75 from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address.upper(), True)
    if not ble_device:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )

    # dt_util.now() is in the time zone configured in Home Assistant, which is
    # what the lamp clock should show (the host may well run in UTC).
    device = WL75Device(ble_device, now=dt_util.now, idle_disconnect=IDLE_DISCONNECT_SECONDS)

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Keep the BLE device current, e.g. when another proxy is closer."""
        device.set_ble_device_and_advertisement_data(
            service_info.device, service_info.advertisement
        )

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    coordinator = WL75Coordinator(hass, entry, device)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await device.stop()
        raise

    # Push state changes from commands and unsolicited notifications.
    entry.async_on_unload(
        device.register_callback(lambda: coordinator.async_set_updated_data(None))
    )
    entry.runtime_data = WL75Data(entry.title, device, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def _async_stop(event: Event) -> None:
        """Close the connection."""
        await device.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: WL75ConfigEntry) -> None:
    """Apply a changed poll interval without reloading."""
    coordinator = entry.runtime_data.coordinator
    coordinator.update_interval = poll_interval(entry)
    if coordinator.update_interval is not None:
        await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: WL75ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.device.stop()
    return unload_ok

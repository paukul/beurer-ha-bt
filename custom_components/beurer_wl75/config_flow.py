"""Config flow for the Beurer WL75 integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN, LOCAL_NAME
from .device import BLEAK_EXCEPTIONS, WL75Device
from .protocol import ProtocolError

_LOGGER = logging.getLogger(__name__)


class WL75ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Beurer WL75."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WL75OptionsFlow:
        """Return the options flow."""
        return WL75OptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device found by Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user pick a discovered lamp and test the connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            await self.async_set_unique_id(discovery_info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            device = WL75Device(discovery_info.device, idle_disconnect=None)
            try:
                await device.update()
            except (*BLEAK_EXCEPTIONS, ProtocolError):
                _LOGGER.debug("Connection test failed", exc_info=True)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=discovery_info.name, data={CONF_ADDRESS: discovery_info.address}
                )
            finally:
                await device.stop()

        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids(include_ignore=False)
            for discovery in async_discovered_service_info(self.hass):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                    or not (discovery.name or "").startswith(LOCAL_NAME)
                ):
                    continue
                self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            info.address: f"{info.name} ({info.address})"
                            for info in self._discovered_devices.values()
                        }
                    )
                }
            ),
            errors=errors,
        )


class WL75OptionsFlow(OptionsFlow):
    """Options of a Beurer WL75."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit the poll interval."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL])}
            )

        current = self.config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POLL_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )

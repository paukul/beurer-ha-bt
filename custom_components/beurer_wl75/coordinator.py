"""Coordinator for the Beurer WL75 integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN
from .device import BLEAK_EXCEPTIONS, WL75Device
from .protocol import ProtocolError

_LOGGER = logging.getLogger(__name__)

type WL75ConfigEntry = ConfigEntry[WL75Data]


@dataclass
class WL75Data:
    """Runtime data of a config entry."""

    title: str
    device: WL75Device
    coordinator: WL75Coordinator


def poll_interval(entry: ConfigEntry) -> timedelta | None:
    """Return the configured poll interval, or None if polling is disabled."""
    minutes = int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
    return timedelta(minutes=minutes) if minutes > 0 else None


class WL75Coordinator(DataUpdateCoordinator[None]):
    """Reads the lamp state; the state itself lives on the device object."""

    config_entry: WL75ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WL75ConfigEntry, device: WL75Device) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=device.name,
            update_interval=poll_interval(entry),
        )
        self.device = device

    async def _async_update_data(self) -> None:
        try:
            await self.device.update()
        except (*BLEAK_EXCEPTIONS, ProtocolError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

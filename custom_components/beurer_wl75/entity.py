"""Base entity for the Beurer WL75 integration."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MANUFACTURER, MODEL
from .coordinator import WL75Coordinator


class WL75Entity(CoordinatorEntity[WL75Coordinator]):
    """Common attributes of all WL75 entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WL75Coordinator, title: str, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        device = coordinator.device
        self._device = device
        self._attr_translation_key = key
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_device_info = DeviceInfo(
            name=title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            connections={(dr.CONNECTION_BLUETOOTH, device.address)},
        )

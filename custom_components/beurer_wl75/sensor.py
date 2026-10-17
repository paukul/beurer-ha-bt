"""Sensors of the Beurer WL75: end of the sleep function."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WL75ConfigEntry, WL75Coordinator
from .entity import WL75Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WL75ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    data = entry.runtime_data
    async_add_entities([WL75SleepEndSensor(data.coordinator, data.title)])


class WL75SleepEndSensor(WL75Entity, SensorEntity):
    """When the running sleep function ends (unknown when it is off)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: WL75Coordinator, title: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, title, "sleep_end")

    @property
    def native_value(self) -> datetime | None:
        """Return the end of the sleep function."""
        return self._device.sleep_end

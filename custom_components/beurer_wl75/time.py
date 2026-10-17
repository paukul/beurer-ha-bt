"""Alarm times of the Beurer WL75."""

from __future__ import annotations

from dataclasses import replace
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WL75ConfigEntry, WL75Coordinator
from .entity import WL75AlarmEntity
from .protocol import ALARM_IDS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WL75ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the alarm times."""
    coordinator, title = entry.runtime_data.coordinator, entry.runtime_data.title
    async_add_entities(WL75AlarmTime(coordinator, title, alarm_id) for alarm_id in ALARM_IDS)


class WL75AlarmTime(WL75AlarmEntity, TimeEntity):
    """The time an alarm rings."""

    _attr_icon = "mdi:alarm"

    def __init__(self, coordinator: WL75Coordinator, title: str, alarm_id: int) -> None:
        """Initialize the time entity."""
        super().__init__(coordinator, title, alarm_id, "time")

    @property
    def native_value(self) -> time | None:
        """Return the alarm time."""
        if (alarm := self.alarm) is None:
            return None
        return time(alarm.hour, alarm.minute)

    async def async_set_value(self, value: time) -> None:
        """Set the alarm time (the lamp has no seconds)."""
        await self.modify_alarm(lambda alarm: replace(alarm, hour=value.hour, minute=value.minute))

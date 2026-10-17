"""Numbers of the Beurer WL75: alarm and sleep settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WL75ConfigEntry, WL75Coordinator
from .entity import WL75AlarmEntity, WL75SleepSettingEntity
from .protocol import ALARM_IDS, Alarm


@dataclass(frozen=True, slots=True)
class WL75NumberDescription:
    """A setting the lamp takes as a number."""

    key: str
    icon: str
    min_value: int
    max_value: int
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class AlarmNumberDescription(WL75NumberDescription):
    """An alarm setting the lamp takes as a number."""

    value: Callable[[Alarm], int] = lambda alarm: 0
    change: Callable[[Alarm, int], Alarm] = lambda alarm, value: alarm


ALARM_NUMBERS = (
    AlarmNumberDescription(
        "volume",
        "mdi:volume-high",
        1,
        10,
        value=lambda alarm: alarm.volume,
        change=lambda alarm, value: replace(alarm, volume=value),
    ),
    AlarmNumberDescription(
        "sunrise_minutes",
        "mdi:weather-sunset-up",
        2,
        60,
        UnitOfTime.MINUTES,
        value=lambda alarm: alarm.sunrise_minutes,
        change=lambda alarm, value: replace(alarm, sunrise_minutes=value),
    ),
    AlarmNumberDescription(
        "brightness",
        "mdi:brightness-6",
        1,
        100,
        PERCENTAGE,
        value=lambda alarm: alarm.brightness,
        change=lambda alarm, value: replace(alarm, brightness=value),
    ),
)

SLEEP_NUMBERS = (
    WL75NumberDescription("minutes", "mdi:timer-outline", 1, 60, UnitOfTime.MINUTES),
    WL75NumberDescription("brightness", "mdi:brightness-6", 10, 100, PERCENTAGE),
    WL75NumberDescription("volume", "mdi:volume-high", 1, 10),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WL75ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers."""
    coordinator, title = entry.runtime_data.coordinator, entry.runtime_data.title
    entities: list[NumberEntity] = [
        WL75AlarmNumber(coordinator, title, alarm_id, description)
        for alarm_id in ALARM_IDS
        for description in ALARM_NUMBERS
    ]
    entities.extend(
        WL75SleepNumber(coordinator, title, description) for description in SLEEP_NUMBERS
    )
    async_add_entities(entities)


def _apply(entity: NumberEntity, description: WL75NumberDescription) -> None:
    entity._attr_entity_category = EntityCategory.CONFIG
    entity._attr_mode = NumberMode.SLIDER
    entity._attr_icon = description.icon
    entity._attr_native_min_value = description.min_value
    entity._attr_native_max_value = description.max_value
    entity._attr_native_step = 1
    entity._attr_native_unit_of_measurement = description.unit


class WL75AlarmNumber(WL75AlarmEntity, NumberEntity):
    """An alarm setting the lamp takes as a number."""

    def __init__(
        self,
        coordinator: WL75Coordinator,
        title: str,
        alarm_id: int,
        description: AlarmNumberDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, title, alarm_id, description.key)
        self._description = description
        _apply(self, description)

    @property
    def native_value(self) -> int | None:
        """Return the setting."""
        return self._description.value(self.alarm) if self.alarm else None

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        await self.modify_alarm(lambda alarm: self._description.change(alarm, int(value)))


class WL75SleepNumber(WL75SleepSettingEntity, NumberEntity):
    """A sleep function setting the lamp takes as a number."""

    def __init__(
        self, coordinator: WL75Coordinator, title: str, description: WL75NumberDescription
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, title, description.key)
        self._description = description
        _apply(self, description)

    @property
    def native_value(self) -> int:
        """Return the setting."""
        return self.setting_value

    def parse_state(self, state: str) -> int | None:
        """Turn a stored state back into the setting (None if out of range)."""
        try:
            value = int(float(state))
        except ValueError:
            return None
        if not self._description.min_value <= value <= self._description.max_value:
            return None
        return value

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        await self.set_setting(int(value))

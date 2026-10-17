"""Selects of the Beurer WL75: alarm tone, wake-up light, snooze, sleep light and sound."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WL75ConfigEntry, WL75Coordinator
from .entity import WL75AlarmEntity, WL75SleepSettingEntity
from .protocol import (
    ALARM_IDS,
    ALARM_SNOOZE_MINUTES,
    ALARM_TONES,
    ALARM_WAKE_UP_LIGHTS,
    SLEEP_LIGHTS,
    SLEEP_SOUNDS,
    Alarm,
)


@dataclass(frozen=True, slots=True)
class AlarmSelectDescription:
    """An alarm setting that is chosen from a list."""

    key: str
    icon: str
    options: dict[int, str]  # lamp value -> option
    value: Callable[[Alarm], int]
    change: Callable[[Alarm, int], Alarm]


ALARM_SELECTS = (
    AlarmSelectDescription(
        "tone",
        "mdi:music-note",
        ALARM_TONES,
        lambda alarm: alarm.tone,
        lambda alarm, value: replace(alarm, tone=value),
    ),
    AlarmSelectDescription(
        "wake_up_light",
        "mdi:weather-sunset-up",
        ALARM_WAKE_UP_LIGHTS,
        lambda alarm: alarm.wake_up_light,
        lambda alarm, value: replace(alarm, wake_up_light=value),
    ),
    AlarmSelectDescription(
        "snooze",
        "mdi:alarm-snooze",
        # The lamp numbers the snooze times 1-6.
        {index: str(minutes) for index, minutes in enumerate(ALARM_SNOOZE_MINUTES, 1)},
        lambda alarm: alarm.snooze,
        lambda alarm, value: replace(alarm, snooze=value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WL75ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    coordinator, title = entry.runtime_data.coordinator, entry.runtime_data.title
    entities: list[SelectEntity] = [
        WL75AlarmSelect(coordinator, title, alarm_id, description)
        for alarm_id in ALARM_IDS
        for description in ALARM_SELECTS
    ]
    entities.append(
        WL75SleepSelect(coordinator, title, "light", SLEEP_LIGHTS, "mdi:lightbulb-night")
    )
    entities.append(WL75SleepSelect(coordinator, title, "sound", SLEEP_SOUNDS, "mdi:music-note"))
    async_add_entities(entities)


class WL75AlarmSelect(WL75AlarmEntity, SelectEntity):
    """An alarm setting chosen from a list."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: WL75Coordinator,
        title: str,
        alarm_id: int,
        description: AlarmSelectDescription,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, title, alarm_id, description.key)
        self._description = description
        self._attr_icon = description.icon
        self._attr_options = list(description.options.values())
        self._values = {option: value for value, option in description.options.items()}

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        if (alarm := self.alarm) is None:
            return None
        return self._description.options.get(self._description.value(alarm))

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        value = self._values[option]
        await self.modify_alarm(lambda alarm: self._description.change(alarm, value))


class WL75SleepSelect(WL75SleepSettingEntity, SelectEntity):
    """Light or sound of the sleep function."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: WL75Coordinator,
        title: str,
        setting: str,
        options: dict[int, str],
        icon: str,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, title, setting)
        self._options = options
        self._values = {option: value for value, option in options.items()}
        self._attr_options = list(options.values())
        self._attr_icon = icon

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        return self._options.get(self.setting_value)

    def parse_state(self, state: str) -> int | None:
        """Turn a stored state back into the setting."""
        return self._values.get(state)

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        await self.set_setting(self._values[option])

"""Switches of the Beurer WL75: alarms, alarm days and the sleep function."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WL75ConfigEntry, WL75Coordinator
from .entity import WL75AlarmEntity, WL75Entity, WL75SleepSettingEntity, call_device
from .protocol import ALARM_DAY_BITS, ALARM_IDS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WL75ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches."""
    coordinator, title = entry.runtime_data.coordinator, entry.runtime_data.title
    entities: list[SwitchEntity] = []
    for alarm_id in ALARM_IDS:
        entities.append(WL75AlarmSwitch(coordinator, title, alarm_id))
        entities.extend(
            WL75AlarmDaySwitch(coordinator, title, alarm_id, day) for day in ALARM_DAY_BITS
        )
    entities.append(WL75SleepSwitch(coordinator, title))
    entities.append(WL75SleepFadeOutSwitch(coordinator, title))
    async_add_entities(entities)


class WL75AlarmSwitch(WL75AlarmEntity, SwitchEntity):
    """Enables an alarm."""

    _attr_icon = "mdi:alarm"

    def __init__(self, coordinator: WL75Coordinator, title: str, alarm_id: int) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, title, alarm_id, "enabled")

    @property
    def is_on(self) -> bool | None:
        """Return if the alarm is enabled."""
        return self.alarm.enabled if self.alarm else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the alarm."""
        await self.modify_alarm(lambda alarm: replace(alarm, enabled=True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the alarm."""
        await self.modify_alarm(lambda alarm: replace(alarm, enabled=False))


class WL75AlarmDaySwitch(WL75AlarmEntity, SwitchEntity):
    """Lets an alarm ring on one weekday."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator: WL75Coordinator, title: str, alarm_id: int, day: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, title, alarm_id, day)
        self._bit = ALARM_DAY_BITS[day]

    @property
    def is_on(self) -> bool | None:
        """Return if the alarm rings on this day."""
        return bool(self.alarm.days & self._bit) if self.alarm else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Let the alarm ring on this day."""
        await self.modify_alarm(lambda alarm: alarm.with_day(self._bit, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Do not let the alarm ring on this day."""
        await self.modify_alarm(lambda alarm: alarm.with_day(self._bit, False))


class WL75SleepSwitch(WL75Entity, SwitchEntity):
    """Starts and stops the sleep function with the sleep settings."""

    _attr_icon = "mdi:weather-night"

    def __init__(self, coordinator: WL75Coordinator, title: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, title, "sleep")

    @property
    def available(self) -> bool:
        """Return if the state of the sleep function is known."""
        return super().available and self._device.sleep is not None

    @property
    def is_on(self) -> bool:
        """Return if the sleep function runs."""
        return self._device.sleep_running

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the sleep function."""
        await call_device(self._device.start_sleep())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the sleep function."""
        await call_device(self._device.stop_sleep())


class WL75SleepFadeOutSwitch(WL75SleepSettingEntity, SwitchEntity):
    """Fades out the sleep sound."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:volume-minus"

    def __init__(self, coordinator: WL75Coordinator, title: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, title, "fade_out")

    @property
    def is_on(self) -> bool:
        """Return if the sound fades out."""
        return self.setting_value

    def parse_state(self, state: str) -> bool | None:
        """Turn a stored state back into the setting."""
        return {STATE_ON: True, STATE_OFF: False}.get(state)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Fade out the sound."""
        await self.set_setting(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Do not fade out the sound."""
        await self.set_setting(False)

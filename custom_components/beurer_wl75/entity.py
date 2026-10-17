"""Base entity for the Beurer WL75 integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import WL75Coordinator
from .device import BLEAK_EXCEPTIONS
from .protocol import Alarm, ProtocolError


async def call_device(action: Awaitable[None]) -> None:
    """Await a device command and turn communication errors into a HomeAssistantError."""
    try:
        await action
    except (*BLEAK_EXCEPTIONS, ProtocolError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(err)},
        ) from err


class WL75Entity(CoordinatorEntity[WL75Coordinator]):
    """Common attributes of all WL75 entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WL75Coordinator,
        title: str,
        key: str,
        *,
        translation_key: str | None = None,
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        """Initialize the entity; ``key`` makes the unique ID."""
        super().__init__(coordinator)
        device = coordinator.device
        self._device = device
        self._attr_translation_key = translation_key or key
        if translation_placeholders:
            self._attr_translation_placeholders = translation_placeholders
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_device_info = DeviceInfo(
            name=title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            connections={(dr.CONNECTION_BLUETOOTH, device.address)},
        )


class WL75AlarmEntity(WL75Entity):
    """An entity for one setting of alarm 1 or 2."""

    def __init__(self, coordinator: WL75Coordinator, title: str, alarm_id: int, key: str) -> None:
        """Initialize the entity."""
        super().__init__(
            coordinator,
            title,
            f"alarm_{alarm_id}_{key}",
            translation_key=f"alarm_{key}",
            translation_placeholders={"alarm": str(alarm_id)},
        )
        self._alarm_id = alarm_id

    @property
    def alarm(self) -> Alarm | None:
        """Return the last known alarm."""
        return self._device.alarms.get(self._alarm_id)

    @property
    def available(self) -> bool:
        """Return if the alarm is known."""
        return super().available and self.alarm is not None

    async def modify_alarm(self, change: Callable[[Alarm], Alarm]) -> None:
        """Change the alarm on the lamp."""
        await call_device(self._device.modify_alarm(self._alarm_id, change))


class WL75SleepSettingEntity(WL75Entity, RestoreEntity):
    """A sleep function setting.

    The lamp forgets the duration and only accepts settings while the sleep
    function runs, so the value lives in Home Assistant and is restored after
    a restart. Without a stored value it starts from the lamp (when off).
    """

    setting: str

    def __init__(self, coordinator: WL75Coordinator, title: str, setting: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, title, f"sleep_{setting}")
        self.setting = setting

    @property
    def setting_value(self) -> Any:
        """Return the current value of the setting."""
        return getattr(self._device.sleep_settings, self.setting)

    def parse_state(self, state: str) -> Any:
        """Turn a stored state back into a setting value (None if invalid)."""
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        """Restore the setting."""
        await super().async_added_to_hass()
        value = None
        if (last := await self.async_get_last_state()) is not None:
            value = self.parse_state(last.state)
        sleep = self._device.sleep
        if value is None and sleep is not None and not sleep.is_on and self.setting != "minutes":
            # While running the lamp reports remaining time and fading brightness,
            # when off always 2 minutes.
            value = getattr(sleep, self.setting)
        if value is not None:
            self._device.restore_sleep_settings(**{self.setting: value})

    async def set_setting(self, value: Any) -> None:
        """Store the setting; a running sleep function gets it right away."""
        await call_device(self._device.set_sleep_settings(**{self.setting: value}))

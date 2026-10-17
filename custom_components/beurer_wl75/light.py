"""Lights of the Beurer WL75: main light and mood light."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.color import brightness_to_value, value_to_brightness

from .const import DOMAIN
from .coordinator import WL75ConfigEntry, WL75Coordinator
from .device import BLEAK_EXCEPTIONS
from .entity import WL75Entity
from .protocol import MOOD_SCENES, ProtocolError

# The lamp takes brightness in percent, 1-100.
BRIGHTNESS_SCALE = (1, 100)

SCENE_BY_NAME = {name: scene for scene, name in MOOD_SCENES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WL75ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the lights."""
    data = entry.runtime_data
    async_add_entities(
        [
            WL75MainLight(data.coordinator, data.title),
            WL75MoodLight(data.coordinator, data.title),
        ]
    )


def _to_percent(brightness: int) -> int:
    return round(brightness_to_value(BRIGHTNESS_SCALE, brightness))


async def _call(action: Awaitable[None]) -> None:
    try:
        await action
    except (*BLEAK_EXCEPTIONS, ProtocolError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(err)},
        ) from err


class WL75MainLight(WL75Entity, LightEntity):
    """The dimmable main light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_name = None

    def __init__(self, coordinator: WL75Coordinator, title: str) -> None:
        """Initialize the main light."""
        super().__init__(coordinator, title, "main_light")

    @property
    def available(self) -> bool:
        """Return if the state is known."""
        return super().available and self._device.light is not None

    @property
    def is_on(self) -> bool | None:
        """Return if the light is on."""
        light = self._device.light
        return light.is_on if light else None

    @property
    def brightness(self) -> int | None:
        """Return the brightness 0-255."""
        light = self._device.light
        return value_to_brightness(BRIGHTNESS_SCALE, light.brightness) if light else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        await _call(
            self._device.turn_on_light(_to_percent(brightness) if brightness is not None else None)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await _call(self._device.turn_off_light())


class WL75MoodLight(WL75Entity, LightEntity):
    """The RGB mood light with scenes."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(MOOD_SCENES.values())

    def __init__(self, coordinator: WL75Coordinator, title: str) -> None:
        """Initialize the mood light."""
        super().__init__(coordinator, title, "mood_light")

    @property
    def available(self) -> bool:
        """Return if the state is known."""
        return super().available and self._device.mood is not None

    @property
    def is_on(self) -> bool | None:
        """Return if the light is on."""
        mood = self._device.mood
        return mood.is_on if mood else None

    @property
    def brightness(self) -> int | None:
        """Return the brightness 0-255."""
        mood = self._device.mood
        return value_to_brightness(BRIGHTNESS_SCALE, mood.brightness) if mood else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the color (the current color of a running scene)."""
        mood = self._device.mood
        return mood.rgb if mood else None

    @property
    def effect(self) -> str | None:
        """Return the running scene."""
        scene = self._device.mood_scene
        return MOOD_SCENES.get(scene) if scene else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        effect = kwargs.get(ATTR_EFFECT)
        await _call(
            self._device.turn_on_mood(
                brightness=_to_percent(brightness) if brightness is not None else None,
                rgb=kwargs.get(ATTR_RGB_COLOR),
                scene=SCENE_BY_NAME.get(effect) if effect else None,
            )
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await _call(self._device.turn_off_mood())

"""Numbers for LG webOS: picture settings and the timer volume."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .entity import LgWebosEntity, async_add_dynamic, async_call

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LgWebosNumberDescription(NumberEntityDescription):
    """A numeric system setting."""

    category: str = "picture"


def _number(
    key: str, low: int, high: int, category: str = "picture"
) -> LgWebosNumberDescription:
    return LgWebosNumberDescription(
        key=key,
        translation_key=key.lower(),
        category=category,
        native_min_value=low,
        native_max_value=high,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
    )


# Picture keys apply to the current picture mode and input. Ranges come from
# the settings service description in the firmware.
NUMBERS = {
    d.key: d
    for d in (
        _number("backlight", 0, 100),
        _number("contrast", 0, 100),
        _number("brightness", 0, 100),
        _number("color", 0, 100),
        _number("sharpness", 0, 50),
        _number("tint", -50, 50),
        _number("colorTemperature", -50, 50),
        _number("onTimerVolume", 0, 100, "time"),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers this TV lets us read."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: (
            k for k, d in NUMBERS.items() if k in c.tv.settings.get(d.category, {})
        ),
        lambda key: LgWebosNumber(entry.runtime_data, NUMBERS[key]),
    )


class LgWebosNumber(LgWebosEntity, NumberEntity):
    """A numeric setting; changes made while the TV is off wait for it."""

    entity_description: LgWebosNumberDescription
    _needs = "nothing"

    @property
    def native_value(self) -> float | None:
        """Current value (the TV reports numbers as strings)."""
        d = self.entity_description
        value = self.tv.settings.get(d.category, {}).get(d.key)
        try:
            return float(value)
        except TypeError, ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Write the setting."""
        d = self.entity_description
        await async_call(self.tv.set_settings(d.category, {d.key: int(value)}))
        self.async_write_ha_state()

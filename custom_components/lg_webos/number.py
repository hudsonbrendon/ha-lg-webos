"""Picture numbers for LG webOS."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .entity import LgWebosEntity, async_add_dynamic, async_call

PARALLEL_UPDATES = 0

# All in the "picture" category, applied to the current picture mode and input.
# Ranges come from the settings service description in the firmware.
RANGES = {
    "backlight": (0, 100),
    "contrast": (0, 100),
    "brightness": (0, 100),
    "color": (0, 100),
    "sharpness": (0, 50),
    "tint": (-50, 50),
    "colorTemperature": (-50, 50),
}
NUMBERS = {
    key: NumberEntityDescription(
        key=key,
        translation_key=key.lower(),
        native_min_value=low,
        native_max_value=high,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
    )
    for key, (low, high) in RANGES.items()
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
        lambda c: (k for k in NUMBERS if k in c.tv.settings.get("picture", {})),
        lambda key: LgWebosNumber(entry.runtime_data, NUMBERS[key]),
    )


class LgWebosNumber(LgWebosEntity, NumberEntity):
    """A picture setting."""

    _needs = "connected"

    @property
    def native_value(self) -> float | None:
        """Current value (the TV reports numbers as strings)."""
        value = self.tv.settings.get("picture", {}).get(self.entity_description.key)
        try:
            return float(value)
        except TypeError, ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Write the setting."""
        key = self.entity_description.key
        await async_call(self.tv.set_settings("picture", {key: int(value)}))

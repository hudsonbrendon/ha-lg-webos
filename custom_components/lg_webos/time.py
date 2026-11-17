"""Times for LG webOS: when the on and off timers fire."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_add_dynamic, async_call

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the timer times once the TV has reported its timers."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: (
            prefix
            for prefix in ("onTimer", "offTimer")
            if f"{prefix}Hour" in c.tv.settings.get("time", {})
        ),
        lambda prefix: LgWebosTimerTime(entry.runtime_data, prefix),
    )


class LgWebosTimerTime(LgWebosEntity, TimeEntity):
    """Time of day of the on or off timer (changes made while off wait)."""

    _attr_entity_category = EntityCategory.CONFIG
    _needs = "nothing"

    def __init__(self, coordinator: LgWebosCoordinator, prefix: str) -> None:
        """Initialize for ``onTimer`` or ``offTimer``."""
        super().__init__(coordinator)
        self._prefix = prefix
        self._attr_translation_key = prefix.lower() + "_time"
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{prefix}_time"

    @property
    def native_value(self) -> time | None:
        """Current timer time."""
        timers = self.tv.settings.get("time", {})
        try:
            return time(
                int(timers[f"{self._prefix}Hour"]), int(timers[f"{self._prefix}Minute"])
            )
        except KeyError, TypeError, ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        """Write hour and minute (the TV stores both as strings)."""
        await async_call(
            self.tv.set_settings(
                "time",
                {
                    f"{self._prefix}Hour": str(value.hour),
                    f"{self._prefix}Minute": str(value.minute),
                },
            )
        )
        self.async_write_ha_state()

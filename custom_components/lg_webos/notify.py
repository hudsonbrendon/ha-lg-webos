"""Notify for LG webOS: toasts on the TV."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_call

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the notify entity."""
    async_add_entities([LgWebosNotify(entry.runtime_data)])


class LgWebosNotify(LgWebosEntity, NotifyEntity):
    """Shows a toast on screen."""

    _attr_translation_key = "toast"

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the notifier."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_toast"

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Show the message."""
        text = f"{title}: {message}" if title else message
        await async_call(self.client.send_message(text))

"""Image for LG webOS: what is on screen right now."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import LgWebosConfigEntry
from .const import WEBOS_EXCEPTIONS
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the screenshot image."""
    async_add_entities([LgWebosScreenImage(hass, entry.runtime_data)])


class LgWebosScreenImage(LgWebosEntity, ImageEntity):
    """A screenshot taken when someone looks.

    The TV captures on request only, so the image is fetched lazily and the
    timestamp moves on every state push to make viewers ask again.
    """

    _attr_translation_key = "screen"
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, coordinator: LgWebosCoordinator) -> None:
        """Initialize the image."""
        LgWebosEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_screen_image"

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.is_on:
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Take a screenshot."""
        try:
            return await self.tv.screenshot()
        except WEBOS_EXCEPTIONS:
            return None

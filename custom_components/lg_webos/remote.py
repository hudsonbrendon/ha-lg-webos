"""Remote for LG webOS: every key of the physical remote, apps as activities."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_ACTIVITY,
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .const import DOMAIN
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_call

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the remote."""
    async_add_entities([LgWebosRemote(entry.runtime_data)])


class LgWebosRemote(LgWebosEntity, RemoteEntity):
    """The remote control."""

    _attr_translation_key = "remote"
    _attr_supported_features = RemoteEntityFeature.ACTIVITY
    _needs = "nothing"

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the remote."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_remote"

    @property
    def is_on(self) -> bool:
        """Whether the TV is on."""
        return self.coordinator.is_on

    @property
    def _apps(self) -> dict[str, str]:
        return {app["title"]: app["id"] for app in self.client.tv_state.apps.values()}

    @property
    def activity_list(self) -> list[str] | None:
        """Installed apps."""
        return sorted(self._apps) or None

    @property
    def current_activity(self) -> str | None:
        """The app in the foreground."""
        state = self.client.tv_state
        return state.apps.get(state.current_app_id or "", {}).get("title")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake the TV, or open an app when an activity is given."""
        if (activity := kwargs.get(ATTR_ACTIVITY)) is None:
            await self.coordinator.async_wake()
        elif (app_id := self._apps.get(activity, activity)) is not None:
            await async_call(self.client.launch_app(app_id))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the TV off."""
        await async_call(self.client.power_off())

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Press remote keys (see aiowebostv.buttons for the names)."""
        if not self.coordinator.is_on:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="tv_off"
            )
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        for _ in range(kwargs.get(ATTR_NUM_REPEATS, 1)):
            for key in command:
                await async_call(self.client.button(key.upper()))
                await asyncio.sleep(delay)

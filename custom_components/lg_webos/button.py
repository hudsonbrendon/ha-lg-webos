"""Buttons for LG webOS."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .api import LgWebosTv
from .entity import LgWebosEntity, async_add_dynamic, async_call

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LgWebosButtonDescription(ButtonEntityDescription):
    """A one-shot action."""

    press_fn: Callable[[LgWebosTv], Awaitable[None]]


BUTTONS = (
    LgWebosButtonDescription(
        key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda tv: tv.reboot(),
    ),
    LgWebosButtonDescription(
        key="screen_saver",
        translation_key="screen_saver",
        press_fn=lambda tv: tv.screen_saver(),
    ),
    LgWebosButtonDescription(
        key="input_picker",
        translation_key="input_picker",
        press_fn=lambda tv: tv.input_picker(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons this TV's firmware accepts."""
    by_key = {d.key: d for d in BUTTONS}
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: (k for k in by_key if k in c.luna_allowed),
        lambda key: LgWebosButton(entry.runtime_data, by_key[key]),
    )


class LgWebosButton(LgWebosEntity, ButtonEntity):
    """A TV action."""

    entity_description: LgWebosButtonDescription

    async def async_press(self) -> None:
        """Run the action."""
        await async_call(self.entity_description.press_fn(self.tv))

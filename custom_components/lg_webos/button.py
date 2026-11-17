"""Buttons for LG webOS."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

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
from .coordinator import LgWebosCoordinator
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
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: list(c.tv.cec_devices) if "cec" in c.luna_allowed else [],
        lambda input_id: LgWebosCecPowerButton(entry.runtime_data, input_id),
    )


class LgWebosCecPowerButton(LgWebosEntity, ButtonEntity):
    """Power key of a device on an HDMI input, sent over HDMI-CEC (toggles)."""

    _attr_translation_key = "cec_power"

    def __init__(self, coordinator: LgWebosCoordinator, input_id: str) -> None:
        """Initialize for one input."""
        super().__init__(coordinator)
        self._input_id = input_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_cec_power_{input_id}"
        )
        self._attr_translation_placeholders = {"input": input_id.replace("_", " ")}

    @property
    def available(self) -> bool:
        """Needs the TV awake and the device still seen on CEC."""
        return super().available and self._input_id in self.tv.cec_devices

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which device this reaches."""
        return {"device": self.tv.cec_devices.get(self._input_id, {}).get("name")}

    async def async_press(self) -> None:
        """Send the power key."""
        await async_call(self.tv.cec_key(self._input_id, "power"))


class LgWebosButton(LgWebosEntity, ButtonEntity):
    """A TV action."""

    entity_description: LgWebosButtonDescription

    async def async_press(self) -> None:
        """Run the action."""
        await async_call(self.entity_description.press_fn(self.tv))

"""Binary sensors for LG webOS: internet, and a plug sensor per HDMI input."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_add_dynamic

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up internet plus one sensor per HDMI input (only HDMI senses a plug)."""
    coordinator = entry.runtime_data
    async_add_entities([LgWebosInternet(coordinator)])
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: (i["id"] for i in c.tv.inputs if "hdmiPlugIn" in i),
        lambda input_id: LgWebosInputPlugged(coordinator, input_id),
    )


class LgWebosInternet(LgWebosEntity, BinarySensorEntity):
    """Whether the TV itself reaches the internet."""

    _attr_translation_key = "internet"
    _needs = "nothing"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_internet"

    @property
    def is_on(self) -> bool | None:
        """Internet reachability as the connection manager sees it."""
        return self.tv.network.get("isInternetConnectionAvailable")


class LgWebosInputPlugged(LgWebosEntity, BinarySensorEntity):
    """Whether a powered device is plugged into an HDMI input."""

    _attr_translation_key = "input_plugged"
    _needs = "nothing"
    _attr_device_class = BinarySensorDeviceClass.PLUG

    def __init__(self, coordinator: LgWebosCoordinator, input_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._input_id = input_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_plugged_{input_id}"
        )
        self._attr_translation_placeholders = {"input": input_id.replace("_", " ")}

    @property
    def _device(self) -> dict[str, Any]:
        return next((i for i in self.tv.inputs if i.get("id") == self._input_id), {})

    @property
    def is_on(self) -> bool | None:
        """Plug state."""
        return self._device.get("hdmiPlugIn")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Whether this is the input on screen and whether it carries video."""
        signal = self.tv.hdmi_signal.get(self._input_id.replace("_", ""), {})
        return {
            "active": self._device.get("activate"),
            "signal": signal.get("signal") == "TRUE" if signal else None,
        }

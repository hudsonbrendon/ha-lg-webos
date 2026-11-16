"""Base entity and dynamic entity registration for LG webOS."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Hashable, Iterable
from typing import TYPE_CHECKING, Any, Literal

from aiowebostv import WebOsClient
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import LgWebosTv
from .const import CONF_MACS, DOMAIN, MANUFACTURER, WEBOS_EXCEPTIONS
from .coordinator import LgWebosCoordinator

if TYPE_CHECKING:
    from . import LgWebosConfigEntry


def device_info(coordinator: LgWebosCoordinator) -> DeviceInfo:
    """Describe the TV."""
    entry = coordinator.config_entry
    tv = coordinator.tv
    info = tv.client.tv_info
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer=MANUFACTURER,
        name=entry.title,
        model=info.system.get("modelName"),
        serial_number=tv.configs.get("tv.model.serialnumber"),
        sw_version=tv.configs.get("tv.nyx.firmwareVersion"),
        hw_version=tv.configs.get("tv.nyx.otaId"),
        connections={
            (CONNECTION_NETWORK_MAC, format_mac(mac))
            for mac in entry.data.get(CONF_MACS, [])
        },
    )


async def async_call[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a TV command, turning transport errors into a user-facing one."""
    try:
        return await coro
    except WEBOS_EXCEPTIONS as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(err) or type(err).__name__},
        ) from err


class LgWebosEntity(CoordinatorEntity[LgWebosCoordinator]):
    """Entity of a TV.

    ``_needs`` says what the entity is worth without: ``on`` (acts on what is
    on screen), ``connected`` (a setting, usable in a standby that keeps the
    network up) or ``nothing`` (shows the last value the TV reported).
    """

    _attr_has_entity_name = True
    _needs: Literal["on", "connected", "nothing"] = "on"

    def __init__(
        self,
        coordinator: LgWebosCoordinator,
        description: EntityDescription | None = None,
    ) -> None:
        """Bind the entity to its TV."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        owner = entry.unique_id or entry.entry_id
        if description is not None:
            self.entity_description = description
            self._attr_unique_id = f"{owner}_{description.key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def tv(self) -> LgWebosTv:
        """The TV wrapper."""
        return self.coordinator.tv

    @property
    def client(self) -> WebOsClient:
        """The websocket client."""
        return self.coordinator.client

    @property
    def available(self) -> bool:
        """See ``_needs``."""
        if self._needs == "on":
            return self.coordinator.is_on
        return self._needs == "nothing" or self.coordinator.is_connected


@callback
def async_add_dynamic(
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    keys_fn: Callable[[LgWebosCoordinator], Iterable[Hashable]],
    factory: Callable[[Any], Entity],
) -> None:
    """Create an entity per key now and whenever the TV reveals a new one.

    What a TV supports is only known while it is on, and it may be off when
    Home Assistant starts.
    """
    coordinator = entry.runtime_data
    known: set[Hashable] = set()

    @callback
    def add_new() -> None:
        new = [key for key in keys_fn(coordinator) if key not in known]
        if new:
            known.update(new)
            async_add_entities(factory(key) for key in new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))

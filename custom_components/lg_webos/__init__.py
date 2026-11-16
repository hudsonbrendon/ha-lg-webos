"""LG webOS integration: everything the TV exposes on the LAN, pushed."""

from __future__ import annotations

from typing import Any

from aiowebostv import WebOsClient
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import LgWebosTv
from .const import DOMAIN, PLATFORMS
from .coordinator import LgWebosCoordinator
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type LgWebosConfigEntry = ConfigEntry[LgWebosCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration-level actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LgWebosConfigEntry) -> bool:
    """Set up a TV from a config entry."""
    client = WebOsClient(
        entry.data[CONF_HOST],
        entry.data[CONF_CLIENT_SECRET],
        client_session=async_get_clientsession(hass),
    )
    coordinator = LgWebosCoordinator(hass, entry, LgWebosTv(client))

    async def close() -> None:
        client.clear_state_update_callbacks()
        await client.disconnect()

    entry.async_on_unload(close)
    await coordinator.async_load_cache()
    # A TV that is off is a normal state, not a setup failure.
    await coordinator.async_config_entry_first_refresh()
    await client.register_state_update_callback(coordinator.async_handle_update)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LgWebosConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: LgWebosConfigEntry) -> None:
    """Forget the cached TV state along with the entry."""
    await Store[dict[str, Any]](hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()

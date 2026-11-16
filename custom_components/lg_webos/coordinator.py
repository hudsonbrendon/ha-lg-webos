"""Coordinator: keeps the websocket up and fans state pushes out."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aiowebostv import WebOsTvPairError
from homeassistant.const import CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import LgWebosTv, send_magic_packet
from .const import CONF_LUNA, CONF_MACS, DOMAIN, LOGGER, WEBOS_EXCEPTIONS

if TYPE_CHECKING:
    from . import LgWebosConfigEntry

# The TV closes its sockets when it sleeps; this is how fast we notice it woke.
SCAN_INTERVAL = timedelta(seconds=10)


class LgWebosCoordinator(DataUpdateCoordinator[None]):
    """Owns one TV."""

    config_entry: LgWebosConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: LgWebosConfigEntry, tv: LgWebosTv
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=SCAN_INTERVAL,
        )
        self.tv = tv
        self.client = tv.client
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}"
        )

    async def async_load_cache(self) -> None:
        """Bring back what the TV last said, so entities have values while it is off."""
        if data := await self._store.async_load():
            self.tv.restore(data)

    @property
    def is_on(self) -> bool:
        """Whether the TV is awake and answering."""
        return self.client.is_connected() and self.client.tv_state.is_on

    @property
    def is_connected(self) -> bool:
        """Whether the socket is up: awake, or in a standby that keeps the network."""
        return self.client.is_connected()

    async def _async_update_data(self) -> None:
        """Reconnect when the socket is down (the TV being off is not an error)."""
        if self.client.is_connected():
            return
        try:
            await self.client.connect()
        except WebOsTvPairError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except (*WEBOS_EXCEPTIONS, RuntimeError):
            # RuntimeError: the shared aiohttp session closes while HA stops.
            return
        try:
            await self.tv.async_subscribe(self._async_push)
            await self._remember()
        except WEBOS_EXCEPTIONS:
            # Went back to sleep mid-setup; the next tick starts over.
            await self.client.disconnect()

    @property
    def luna_allowed(self) -> list[str]:
        """Luna-backed features this TV's firmware accepts (see api.LUNA_FEATURES)."""
        allowed: list[str] = self.config_entry.data.get(CONF_LUNA, {}).get(
            "allowed", []
        )
        return allowed

    async def _remember(self) -> None:
        """Persist what is needed while the TV is off: key, MACs, luna features."""
        entry = self.config_entry
        data: dict[str, Any] = {**entry.data}
        firmware = self.tv.configs.get("tv.nyx.firmwareVersion")
        # ponytail: probed once per firmware version, since each probe pops a
        # blank alert on screen for an instant.
        if data.get(CONF_LUNA, {}).get("firmware") != firmware:
            data[CONF_LUNA] = {
                "firmware": firmware,
                "allowed": await self.tv.probe_luna(),
            }
        if self.client.client_key:
            data[CONF_CLIENT_SECRET] = self.client.client_key
        if macs := self.tv.macs:
            data[CONF_MACS] = macs
        if data != entry.data:
            self.hass.config_entries.async_update_entry(entry, data=data)

    async def _async_push(self) -> None:
        self._store.async_delay_save(self.tv.snapshot, 30)
        self.async_set_updated_data(None)

    async def async_handle_update(self, _: Any) -> None:
        """Handle a state push from aiowebostv."""
        self.async_set_updated_data(None)

    async def async_wake(self) -> None:
        """Turn the TV on: over the socket if it is in standby, else by WoL."""
        if self.client.is_connected():
            try:
                await self.client.power_on()
            except WEBOS_EXCEPTIONS:
                LOGGER.debug("system/turnOn refused, falling back to WoL")
        if macs := self.config_entry.data.get(CONF_MACS):
            await self.hass.async_add_executor_job(send_magic_packet, macs)

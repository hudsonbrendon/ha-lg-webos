"""Coordinator: keeps the websocket up and fans state pushes out."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aiowebostv import WebOsTvCommandError, WebOsTvPairError
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import (
    LUNA_PROBE_VERSION,
    IpControl,
    LgWebosTv,
    new_ip_control_code,
    send_magic_packet,
)
from .const import (
    CONF_IP_CONTROL,
    CONF_IP_CONTROL_CODE,
    CONF_LUNA,
    CONF_MACS,
    DOMAIN,
    LOGGER,
    WEBOS_EXCEPTIONS,
)

if TYPE_CHECKING:
    from . import LgWebosConfigEntry

# The TV closes its sockets when it sleeps; this is how fast we notice it woke.
SCAN_INTERVAL = timedelta(seconds=10)
# Queued writes: wait for the TV to report it is on, let it settle, confirm.
FLUSH_WAIT_ON = 30
FLUSH_SETTLE = 8
FLUSH_CONFIRM = 3
FLUSH_ATTEMPTS = 3
IP_CONTROL_CHECKS = 5


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
            if self.tv.pending:
                self.config_entry.async_create_background_task(
                    self.hass, self._async_flush_pending(), f"{DOMAIN} flush"
                )
            await self._remember()
            self._store.async_delay_save(self.tv.snapshot, 0)
        except WEBOS_EXCEPTIONS:
            # Went back to sleep mid-setup; the next tick starts over.
            await self.client.disconnect()

    async def _async_flush_pending(self) -> None:
        """Apply writes queued while the TV was off, once it has settled.

        Right after waking, the TV accepts alerts but drops their luna calls
        and switches back to its input. So wait, send, and send again what
        its own pushes do not confirm.
        """
        for _ in range(FLUSH_WAIT_ON):
            if self.is_on:
                break
            await asyncio.sleep(1)
        for _ in range(FLUSH_ATTEMPTS):
            await asyncio.sleep(FLUSH_SETTLE)
            if not self.tv.pending or not self.client.is_connected():
                break
            try:
                sent = await self.tv.flush_pending()
            except WEBOS_EXCEPTIONS:
                continue
            await asyncio.sleep(FLUSH_CONFIRM)
            for category, settings in self.tv.not_applied(sent).items():
                self.tv.pending.setdefault(category, {}).update(settings)
            LOGGER.debug(
                "%s: queued settings sent %s, left %s", self.name, sent, self.tv.pending
            )
        self._store.async_delay_save(self.tv.snapshot, 0)
        self.async_set_updated_data(None)

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
        known = data.get(CONF_LUNA, {})
        if (known.get("firmware"), known.get("version")) != (
            firmware,
            LUNA_PROBE_VERSION,
        ):
            try:
                allowed = await self.tv.probe_luna()
            except WebOsTvCommandError:
                # Not a clear answer (TV still waking up): ask on next connect.
                LOGGER.debug("%s: luna probe inconclusive, retrying later", self.name)
            else:
                data[CONF_LUNA] = {
                    "firmware": firmware,
                    "version": LUNA_PROBE_VERSION,
                    "allowed": allowed,
                }
        await self._sync_ip_control(data)
        if self.client.client_key:
            data[CONF_CLIENT_SECRET] = self.client.client_key
        if macs := self.tv.macs:
            data[CONF_MACS] = macs
        if data != entry.data:
            self.hass.config_entries.async_update_entry(entry, data=data)

    @property
    def ip_control(self) -> IpControl | None:
        """LG IP Control client, when it is turned on for this TV."""
        if code := self.config_entry.data.get(CONF_IP_CONTROL_CODE):
            return IpControl(self.config_entry.data[CONF_HOST], code)
        return None

    def require_ip_control(self) -> IpControl:
        """The IP Control client, or a user-facing error when it is off."""
        if (ip := self.ip_control) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="ip_control_off"
            )
        return ip

    async def _sync_ip_control(self, data: dict[str, Any]) -> None:
        """Turn LG IP Control on or off on the TV to match the options."""
        options = self.config_entry.options
        wanted = options.get(CONF_IP_CONTROL, False)
        code = data.get(CONF_IP_CONTROL_CODE)
        if wanted and (given := options.get(CONF_IP_CONTROL_CODE)) and given != code:
            # A key code already generated on the TV menu: use it as is.
            data[CONF_IP_CONTROL_CODE] = given
            return
        if wanted and not code:
            if "ip_control" not in data.get(CONF_LUNA, {}).get("allowed", []):
                return
            code = new_ip_control_code()
            await self.tv.enable_ip_control(code)
            client = IpControl(data[CONF_HOST], code)
            for _ in range(IP_CONTROL_CHECKS):
                # The service takes a few seconds to come up after the ping.
                await asyncio.sleep(2)
                try:
                    await client.send("GET_IPCONTROL_STATE")
                except OSError, TimeoutError, ValueError:
                    continue
                break
            else:
                # The service was already running with another key (set on
                # the TV menu); it only rereads the key when the TV restarts.
                LOGGER.warning(
                    "%s: LG IP Control did not accept the new key; it will "
                    "after the TV restarts",
                    self.name,
                )
            data[CONF_IP_CONTROL_CODE] = code
        elif not wanted and code:
            await self.tv.disable_ip_control()
            data.pop(CONF_IP_CONTROL_CODE)

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

"""Config flow for LG webOS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from aiowebostv import WebOsTvPairError
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_CLIENT_SECRET,
    CONF_HOST,
    CONF_NAME,
    CONF_UNIQUE_ID,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_FRIENDLY_NAME,
    SsdpServiceInfo,
)
import voluptuous as vol

from .api import LgWebosClient, LgWebosTv
from .const import (
    CONF_IP_CONTROL,
    CONF_IP_CONTROL_CODE,
    CONF_MACS,
    DOMAIN,
    NATIVE_DOMAIN,
    WEBOS_EXCEPTIONS,
)

DEFAULT_NAME = "LG webOS TV"
CONF_ENTRIES = "entries"


class LgWebosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair with a TV, or reuse the pairing of the built-in integration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LgWebosOptionsFlow:
        """Options: LG IP Control."""
        return LgWebosOptionsFlow()

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host = ""
        self._name = DEFAULT_NAME
        self._key: str | None = None

    def _native_entries(self) -> dict[str, dict[str, Any]]:
        """Built-in webostv entries not yet set up here, as entry data by id."""
        mine = {entry.unique_id for entry in self._async_current_entries()}
        devices = dr.async_get(self.hass)
        found: dict[str, dict[str, Any]] = {}
        for entry in self.hass.config_entries.async_entries(NATIVE_DOMAIN):
            if entry.unique_id in mine or not entry.data.get(CONF_CLIENT_SECRET):
                continue
            device = devices.async_get_device_by_identifier(
                (NATIVE_DOMAIN, entry.unique_id or ""), entry.entry_id
            )
            found[entry.entry_id] = {
                CONF_NAME: entry.title,
                CONF_UNIQUE_ID: entry.unique_id,
                CONF_HOST: entry.data[CONF_HOST],
                CONF_CLIENT_SECRET: entry.data[CONF_CLIENT_SECRET],
                CONF_MACS: sorted(
                    mac
                    for kind, mac in (device.connections if device else ())
                    if kind == dr.CONNECTION_NETWORK_MAC
                ),
            }
        return found

    def _native_key(self, host: str) -> tuple[str, str] | None:
        """Pairing key (and title) the built-in integration holds for a host."""
        for data in self._native_entries().values():
            if data[CONF_HOST] == host:
                return data[CONF_NAME], data[CONF_CLIENT_SECRET]
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to import from the built-in integration when there is something."""
        if self._native_entries():
            return self.async_show_menu(
                step_id="user", menu_options=["import_native", "manual"]
            )
        return await self.async_step_manual()

    async def async_step_import_native(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the TVs to bring over; no prompt shows on the TV."""
        entries = self._native_entries()
        if user_input is not None:
            first, *rest = user_input[CONF_ENTRIES]
            for entry_id in rest:
                self.hass.async_create_task(
                    self.hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": SOURCE_IMPORT},
                        data=entries[entry_id],
                    )
                )
            return await self.async_step_import(entries[first])
        return self.async_show_form(
            step_id="import_native",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENTRIES, default=list(entries)): vol.All(
                        cv.multi_select(
                            {
                                entry_id: f"{data[CONF_NAME]} ({data[CONF_HOST]})"
                                for entry_id, data in entries.items()
                            }
                        ),
                        vol.Length(min=1),
                    )
                }
            ),
        )

    async def async_step_import(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create an entry from the built-in one, even with the TV off.

        The pairing key, UUID and MACs are all known already, so the TV does
        not have to be awake (or woken) for this.
        """
        await self.async_set_unique_id(data[CONF_UNIQUE_ID], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=data[CONF_NAME],
            data={
                CONF_HOST: data[CONF_HOST],
                CONF_CLIENT_SECRET: data[CONF_CLIENT_SECRET],
                CONF_MACS: data[CONF_MACS],
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the address."""
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            if native := self._native_key(self._host):
                self._name, self._key = native
            return await self.async_step_pairing()
        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema({vol.Required(CONF_HOST): str})
        )

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a TV announcing its second-screen service."""
        host = urlparse(discovery_info.ssdp_location or "").hostname
        if not host:
            return self.async_abort(reason="cannot_connect")
        self._host = host
        self._name = (
            discovery_info.upnp.get(ATTR_UPNP_FRIENDLY_NAME, DEFAULT_NAME)
            .replace("[LG]", "LG")
            .strip()
        )
        uuid = (discovery_info.ssdp_usn or "").partition("::")[0].removeprefix("uuid:")
        if uuid:
            await self.async_set_unique_id(uuid)
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._async_abort_entries_match({CONF_HOST: host})
        if native := self._native_key(host):
            self._name, self._key = native
        self.context["title_placeholders"] = {"name": self._name, "host": host}
        return await self.async_step_pairing()

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect; without a stored key the TV shows a prompt to accept."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = LgWebosClient(
                self._host, self._key, client_session=async_get_clientsession(self.hass)
            )
            try:
                await client.connect()
            except WebOsTvPairError:
                errors["base"] = "pairing_refused"
                # stored key refused: the next try asks the TV for a new one
                self._key = None
            except WEBOS_EXCEPTIONS:
                errors["base"] = "cannot_connect"
            else:
                macs = LgWebosTv(client).macs
                uuid = client.tv_info.hello.get("deviceUUID")
                key = client.client_key
                await client.disconnect()
                data = {CONF_HOST: self._host, CONF_CLIENT_SECRET: key, CONF_MACS: macs}
                await self.async_set_unique_id(uuid, raise_on_progress=False)
                if self.source == SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(), data_updates=data
                    )
                if self.source == "reauth":
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=data
                    )
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
                return self.async_create_entry(title=self._name, data=data)
        return self.async_show_form(
            step_id="pairing",
            errors=errors,
            description_placeholders={"name": self._name, "host": self._host},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Pair again after the TV dropped our key."""
        self._host = entry_data[CONF_HOST]
        self._name = self._get_reauth_entry().title
        # try the stored key first: no prompt on the TV if it still works
        self._key = entry_data.get(CONF_CLIENT_SECRET)
        self.context["title_placeholders"] = {"name": self._name, "host": self._host}
        return await self.async_step_pairing()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address of a TV."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._name = entry.title
            self._key = entry.data[CONF_CLIENT_SECRET]
            return await self.async_step_pairing({})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str}
            ),
        )


class LgWebosOptionsFlow(OptionsFlowWithReload):
    """Turn LG IP Control on or off."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IP_CONTROL,
                        default=self.config_entry.options.get(CONF_IP_CONTROL, False),
                    ): bool,
                    vol.Optional(
                        CONF_IP_CONTROL_CODE,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_IP_CONTROL_CODE
                            )
                        },
                    ): vol.All(str, vol.Upper, vol.Match(r"^[A-Z0-9]{8}$")),
                }
            ),
        )

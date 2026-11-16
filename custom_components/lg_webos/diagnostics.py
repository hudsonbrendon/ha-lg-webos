"""Diagnostics for LG webOS."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST
from homeassistant.core import HomeAssistant

from . import LgWebosConfigEntry
from .const import CONF_MACS

TO_REDACT = {
    CONF_CLIENT_SECRET,
    CONF_HOST,
    CONF_MACS,
    "macAddress",
    "deviceUUID",
    "zipcode",
    "deviceName",
    "tv.model.serialnumber",
    "ipAddress",
    "ssid",
    "displayName",
    "gateway",
    "dns1",
    "dns2",
    "ipv6",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LgWebosConfigEntry
) -> dict[str, Any]:
    """Return what the TV told us, minus identifiers."""
    coordinator = entry.runtime_data
    tv = coordinator.tv
    state = asdict(tv.client.tv_state)
    state["apps"] = sorted(state["apps"])
    state["channels"] = len(state["channels"] or [])
    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "connected": tv.client.is_connected(),
            "tv_info": asdict(tv.client.tv_info),
            "tv_state": state,
            "settings": tv.settings,
            "inputs": tv.inputs,
            "configs": tv.configs,
            "network": tv.network,
            "hdmi_signal": tv.hdmi_signal,
            "power_on_reason": tv.power_on_reason,
            "options": tv.options,
            "luna_allowed": coordinator.luna_allowed,
        },
        TO_REDACT,
    )

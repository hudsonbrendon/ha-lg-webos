"""Actions for LG webOS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .const import (
    ATTR_APP_ID,
    ATTR_BUTTON,
    ATTR_CATEGORY,
    ATTR_COMMAND,
    ATTR_CONTENT_ID,
    ATTR_FILENAME,
    ATTR_PARAMS,
    ATTR_PAYLOAD,
    ATTR_REPLACE,
    ATTR_SETTINGS,
    ATTR_TEXT,
    ATTR_URI,
    DOMAIN,
    SERVICE_BUTTON,
    SERVICE_COMMAND,
    SERVICE_LAUNCH_APP,
    SERVICE_LUNA,
    SERVICE_SCREENSHOT,
    SERVICE_SET_SETTINGS,
    SERVICE_TYPE_TEXT,
)
from .coordinator import LgWebosCoordinator
from .entity import async_call

DEVICE = {vol.Required(ATTR_DEVICE_ID): cv.string}


def _coordinator(call: ServiceCall) -> LgWebosCoordinator:
    """Resolve the TV an action targets; its socket has to be up."""
    device = dr.async_get(call.hass).async_get(call.data[ATTR_DEVICE_ID])
    for entry_id in device.config_entries if device else ():
        entry = call.hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
            coordinator: LgWebosCoordinator = entry.runtime_data
            if not coordinator.is_connected:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="tv_off"
                )
            return coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="device_not_found"
    )


async def _button(call: ServiceCall) -> None:
    await async_call(_coordinator(call).client.button(call.data[ATTR_BUTTON].upper()))


async def _command(call: ServiceCall) -> ServiceResponse:
    client = _coordinator(call).client
    return await async_call(
        client.request(call.data[ATTR_COMMAND], call.data.get(ATTR_PAYLOAD))
    )


async def _luna(call: ServiceCall) -> None:
    tv = _coordinator(call).tv
    await async_call(tv.luna(call.data[ATTR_URI], call.data.get(ATTR_PARAMS)))


async def _set_settings(call: ServiceCall) -> None:
    tv = _coordinator(call).tv
    await async_call(
        tv.set_settings(call.data[ATTR_CATEGORY], call.data[ATTR_SETTINGS])
    )


async def _launch_app(call: ServiceCall) -> None:
    client = _coordinator(call).client
    payload: dict[str, Any] = {"id": call.data[ATTR_APP_ID]}
    if content_id := call.data.get(ATTR_CONTENT_ID):
        payload["contentId"] = content_id
    if params := call.data.get(ATTR_PARAMS):
        payload["params"] = params
    await async_call(client.request("system.launcher/launch", payload))


async def _type_text(call: ServiceCall) -> None:
    tv = _coordinator(call).tv
    await async_call(
        tv.type_text(call.data[ATTR_TEXT], replace=call.data[ATTR_REPLACE])
    )


async def _screenshot(call: ServiceCall) -> None:
    hass = call.hass
    filename: str = call.data[ATTR_FILENAME]
    if not hass.config.is_allowed_path(filename):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="path_not_allowed",
            translation_placeholders={"filename": filename},
        )
    image = await async_call(_coordinator(call).tv.screenshot())
    if image is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="screenshot_failed"
        )
    await hass.async_add_executor_job(Path(filename).write_bytes, image)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""
    reg = hass.services.async_register
    reg(
        DOMAIN,
        SERVICE_BUTTON,
        _button,
        vol.Schema({**DEVICE, vol.Required(ATTR_BUTTON): cv.string}),
    )
    reg(
        DOMAIN,
        SERVICE_COMMAND,
        _command,
        vol.Schema(
            {
                **DEVICE,
                vol.Required(ATTR_COMMAND): cv.string,
                vol.Optional(ATTR_PAYLOAD): dict,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        SERVICE_LUNA,
        _luna,
        vol.Schema(
            {
                **DEVICE,
                vol.Required(ATTR_URI): vol.Match(r"^luna://"),
                vol.Optional(ATTR_PARAMS): dict,
            }
        ),
    )
    reg(
        DOMAIN,
        SERVICE_SET_SETTINGS,
        _set_settings,
        vol.Schema(
            {
                **DEVICE,
                vol.Required(ATTR_CATEGORY): cv.string,
                vol.Required(ATTR_SETTINGS): dict,
            }
        ),
    )
    reg(
        DOMAIN,
        SERVICE_LAUNCH_APP,
        _launch_app,
        vol.Schema(
            {
                **DEVICE,
                vol.Required(ATTR_APP_ID): cv.string,
                vol.Optional(ATTR_CONTENT_ID): cv.string,
                vol.Optional(ATTR_PARAMS): dict,
            }
        ),
    )
    reg(
        DOMAIN,
        SERVICE_TYPE_TEXT,
        _type_text,
        vol.Schema(
            {
                **DEVICE,
                vol.Required(ATTR_TEXT): cv.string,
                vol.Optional(ATTR_REPLACE, default=False): cv.boolean,
            }
        ),
    )
    reg(
        DOMAIN,
        SERVICE_SCREENSHOT,
        _screenshot,
        vol.Schema({**DEVICE, vol.Required(ATTR_FILENAME): cv.string}),
    )

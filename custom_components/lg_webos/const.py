"""Constants for the LG webOS integration."""

from __future__ import annotations

import logging
from typing import Final

import aiohttp
from aiowebostv import WebOsTvCommandError
from homeassistant.const import Platform

DOMAIN: Final = "lg_webos"
MANUFACTURER: Final = "LG"
LOGGER = logging.getLogger(__package__)
NATIVE_DOMAIN: Final = "webostv"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

CONF_MACS: Final = "macs"
CONF_LUNA: Final = "luna"
CONF_IP_CONTROL: Final = "ip_control"
CONF_IP_CONTROL_CODE: Final = "ip_control_code"

LIVE_TV_APP_ID: Final = "com.webos.app.livetv"

# Seen across webOS releases; the TV rejects the ones it does not have.
SOUND_OUTPUTS: Final = [
    "tv_speaker",
    "external_arc",
    "external_optical",
    "bt_soundbar",
    "mobile_phone",
    "lineout",
    "headphone",
    "external_speaker",
    "tv_external_speaker",
    "tv_speaker_headphone",
    "soundbar",
]

ATTR_BUTTON: Final = "button"
ATTR_COMMAND: Final = "command"
ATTR_PAYLOAD: Final = "payload"
ATTR_URI: Final = "uri"
ATTR_PARAMS: Final = "params"
ATTR_CATEGORY: Final = "category"
ATTR_SETTINGS: Final = "settings"
ATTR_APP_ID: Final = "app_id"
ATTR_CONTENT_ID: Final = "content_id"
ATTR_TEXT: Final = "text"
ATTR_REPLACE: Final = "replace"
ATTR_FILENAME: Final = "filename"
ATTR_INPUT: Final = "input"
ATTR_KEY: Final = "key"

SERVICE_BUTTON: Final = "button"
SERVICE_COMMAND: Final = "command"
SERVICE_LUNA: Final = "luna"
SERVICE_SET_SETTINGS: Final = "set_system_settings"
SERVICE_LAUNCH_APP: Final = "launch_app"
SERVICE_TYPE_TEXT: Final = "type_text"
SERVICE_SCREENSHOT: Final = "screenshot"
SERVICE_CEC_KEY: Final = "cec_key"
SERVICE_IP_CONTROL: Final = "ip_control"

WEBOS_EXCEPTIONS: Final = (
    OSError,
    ValueError,
    WebOsTvCommandError,
    aiohttp.ClientError,
    TimeoutError,
)

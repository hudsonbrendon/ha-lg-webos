"""Fixtures: a fake TV built from what the real ones answered."""

from unittest.mock import AsyncMock, MagicMock, patch

from aiowebostv import WebOsTvCommandError
from aiowebostv.models import WebOsTvInfo, WebOsTvState
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lg_webos.const import CONF_MACS, DOMAIN

UUID = "00000000-1111-2222-3333-444444444444"
HOST = "192.0.2.10"
INPUTS = [
    {"id": "AV_1", "label": "AV", "appId": "com.webos.app.externalinput.av1"},
    {
        "id": "HDMI_2",
        "label": "PS5",
        "appId": "com.webos.app.hdmi2",
        "hdmiPlugIn": True,
        "activate": True,
        "subList": [
            {"id": "SIMPLINK", "osdName": "PlayStation 5", "vendorId": 524358},
            {"id": "URCU", "serviceType": "game", "brandName": "PS5"},
        ],
    },
]
SETTINGS = {
    "picture": {"backlight": "100", "contrast": "100", "brightness": 50, "color": "55"},
    "sound": {"soundOutput": "tv_speaker", "eArcSupport": "off"},
    "option": {"audioGuidance": "off", "livePlus": "off"},
    "network": {"deviceName": "TV", "wolwowlOnOff": "true"},
    "other": {"simplinkEnable": "on"},
}
ABSENT: set[str] = set()
DESCRIBED = {
    "soundOutput": ["tv_speaker", "external_arc"],
    "pictureMode": ["cinema", "vivid"],
}
PUSHES = {
    "com.webos.service.eim/getAllInputStatus": {"devices": INPUTS},
    "com.webos.service.connectionmanager/getstatus": {
        "wired": {"state": "disconnected"},
        "wifi": {"state": "connected", "ssid": "CASA", "ipAddress": "192.0.2.10"},
        "isInternetConnectionAvailable": True,
    },
    "com.webos.service.eim/getHDMISignalInfo": {
        "HDMI2": {"5v": "TRUE", "signal": "TRUE"}
    },
    "com.webos.service.tvpower/power/getPowerOnReason": {"reason": "wakeOnWiFi"},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the custom integration in every test."""


def make_client(on: bool = True) -> MagicMock:
    """A WebOsClient double that behaves like the TV for the URIs we use."""
    client = MagicMock()
    client.host = HOST
    client.client_key = "key"
    client.tv_info = WebOsTvInfo(
        hello={"deviceUUID": UUID, "deviceOSReleaseVersion": "5.6.2"},
        system={"modelName": "60UN7310PSA"},
        connection={
            "wiredInfo": {"macAddress": "00:00:5E:00:53:01"},
            "wifiInfo": {"macAddress": "00:00:5E:00:53:02"},
        },
    )
    client.tv_state = WebOsTvState()
    connected = {"value": False}
    client.is_connected = lambda: connected["value"]
    client.subscriptions = {}

    async def connect() -> bool:
        if not on:
            raise TimeoutError
        connected["value"] = True
        client.tv_state = WebOsTvState(
            power_state={"state": "Active"},
            current_app_id="com.webos.app.hdmi2",
            sound_output="tv_speaker",
            muted=False,
            volume=30,
            apps={
                "netflix": {"id": "netflix", "title": "Netflix", "icon": "https://x/i"}
            },
            inputs={i["appId"]: i for i in INPUTS},
            is_on=True,
            is_screen_on=True,
        )
        return True

    async def subscribe(callback, uri, payload=None):
        if uri == "settings/getSystemSettings":
            category = payload["category"]
            known = SETTINGS.get(category, {})
            # Like webOS 24: a whitelisted key the model lacks fails the whole
            # request and the error names nothing.
            if ABSENT & set(payload["keys"]):
                raise WebOsTvCommandError("500 Application error")
            # Like the real gateway: one refused key named per error.
            if refused := [k for k in payload["keys"] if k not in known]:
                raise WebOsTvCommandError(
                    f"Some keys are not allowed for the request. ( {refused[0]} )"
                )
            client.subscriptions[category] = callback
            await callback({"settings": dict(known)})
        else:
            client.subscriptions[uri] = callback
            await callback(PUSHES[uri])
        return {"subscribed": True}

    async def request(uri, payload=None, **kwargs):
        if uri == "settings/getSystemSettings":
            (key,) = payload["keys"]
            if key in ABSENT or key not in SETTINGS.get(payload["category"], {}):
                raise WebOsTvCommandError("There is no matched result from DB")
            return {"settings": {key: SETTINGS[payload["category"]][key]}}
        if uri == "config/getConfigs":
            return {
                "configs": {
                    "tv.nyx.firmwareVersion": "04.64.00",
                    "tv.nyx.platformVersion": "5.6.2",
                }
            }
        if uri == "settings/getSystemSettingDesc":
            (key,) = payload["keys"]
            if key not in DESCRIBED:
                raise WebOsTvCommandError("Some keys are not allowed")
            return {
                "results": [
                    {
                        "values": {
                            "arrayExt": [
                                {"value": v, "active": True, "visible": True}
                                for v in DESCRIBED[key]
                            ]
                            + [{"value": "hidden", "active": True, "visible": False}]
                        }
                    }
                ]
            }
        if uri == "system.notifications/createAlert":
            # webOS 5.6: alerts may only carry the settings call.
            if (
                "tvpower" in payload["buttons"][0]["onClick"]
                or "surface" in payload["buttons"][0]["onClick"]
            ):
                raise WebOsTvCommandError(
                    "Not allowed to call method specified in the uri"
                )
            return {"returnValue": True, "alertId": "alert-1"}
        if uri == "tv/executeOneShot":
            return {"returnValue": True, "imageUri": "https://tv/capture.jpg"}
        return {"returnValue": True}

    client.connect = AsyncMock(side_effect=connect)
    client.disconnect = AsyncMock()
    client.subscribe = AsyncMock(side_effect=subscribe)
    client.request = AsyncMock(side_effect=request)
    client.register_state_update_callback = AsyncMock()
    for name in (
        "power_on",
        "power_off",
        "button",
        "set_volume",
        "set_mute",
        "launch_app",
        "set_input",
        "change_sound_output",
        "set_screen_state",
        "send_message",
    ):
        setattr(client, name, AsyncMock())
    return client


@pytest.fixture
def client():
    """Patch the client everywhere it is built."""
    fake = make_client()
    with (
        patch("custom_components.lg_webos.WebOsClient", return_value=fake),
        patch("custom_components.lg_webos.config_flow.WebOsClient", return_value=fake),
    ):
        yield fake


@pytest.fixture
def entry(hass):
    """A configured TV."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="TV da sala",
        unique_id=UUID,
        data={"host": HOST, "client_secret": "key", CONF_MACS: ["00:00:5e:00:53:01"]},
    )
    entry.add_to_hass(hass)
    return entry

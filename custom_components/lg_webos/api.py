"""What the TV offers over SSAP beyond aiowebostv's own surface.

Everything here was observed on real TVs (see REVERSE_ENGINEERING.md):
readable settings, per-input device status, screenshots, and luna calls
tunnelled through a system alert.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import suppress
import re
import socket
from typing import Any

from aiowebostv import WebOsClient, WebOsTvCommandError

CREATE_ALERT = "system.notifications/createAlert"
CLOSE_ALERT = "system.notifications/closeAlert"
GET_SETTINGS = "settings/getSystemSettings"
GET_CONFIGS = "config/getConfigs"
INPUT_STATUS = "com.webos.service.eim/getAllInputStatus"
ONE_SHOT = "tv/executeOneShot"
INSERT_TEXT = "com.webos.service.ime/insertText"
DELETE_CHARS = "com.webos.service.ime/deleteCharacters"
SEND_ENTER = "com.webos.service.ime/sendEnterKey"
LUNA_SET_SETTINGS = "luna://com.webos.settingsservice/setSystemSettings"
LUNA_REBOOT = "luna://com.webos.service.tvpower/power/reboot"
LUNA_SCREEN_SAVER = "luna://com.webos.service.tvpower/power/turnOnScreenSaver"
LUNA_INPUT_PICKER = "luna://com.webos.surfacemanager/showInputPicker"

# Settings the SSAP gateway may let a paired client read. The whitelist
# differs per webOS release, so keys the TV refuses are dropped at runtime.
READABLE_SETTINGS: dict[str, tuple[str, ...]] = {
    "picture": (
        "backlight",
        "contrast",
        "brightness",
        "color",
        "sharpness",
        "tint",
        "colorTemperature",
        "pictureMode",
        "energySaving",
        "dynamicContrast",
        "peakBrightness",
        "truMotionMode",
        "colorGamut",
        "gamma",
        "blackLevel",
        "superResolution",
        "noiseReduction",
        "smoothGradation",
        "hdrDynamicToneMapping",
        "eyeComfortMode",
        "motionEyeCare",
        "realCinema",
    ),
    "sound": (
        "soundOutput",
        "eArcSupport",
        "avSync",
        "soundOutputDigital",
        "soundMode",
    ),
    "option": ("audioGuidance", "livePlus", "quickStartMode"),
    "network": ("deviceName", "wolwowlOnOff", "bleAdvertisingOnOff"),
    "other": (
        "simplinkEnable",
        "uhdDeepColorHDMI1",
        "uhdDeepColorHDMI2",
        "uhdDeepColorHDMI3",
        "uhdDeepColorHDMI4",
    ),
    "general": (
        "alwaysOn",
        "homeAutoLaunch",
        "homePromotion",
        "tvOnScreen",
        "lifeOnScreenMode",
    ),
    "support": ("automaticUpdate",),
}

# configd has no key validation on the gateway: any key can be read.
CONFIG_NAMES = [
    "tv.nyx.*",
    "tv.model.serialnumber",
    "tv.model.moduleInchType",
    "tv.model.displayType",
    "tv.hw.panelResolution",
    "system.arcPort",
]
NETWORK_STATUS = "com.webos.service.connectionmanager/getstatus"
HDMI_SIGNAL = "com.webos.service.eim/getHDMISignalInfo"
POWER_ON_REASON = "com.webos.service.tvpower/power/getPowerOnReason"
GET_SETTING_DESC = "settings/getSystemSettingDesc"
# Keys whose description the gateway hands out (firmware whitelist).
DESCRIBED_SETTINGS = (
    ("sound", "soundOutput"),
    ("sound", "soundOutputDigital"),
    ("picture", "pictureMode"),
)

# State kept across disconnects and restarts (see LgWebosTv.snapshot).
CACHED = (
    "settings",
    "inputs",
    "configs",
    "network",
    "hdmi_signal",
    "power_on_reason",
    "options",
)

# Luna calls behind entities. Firmware decides which ones an alert may carry
# (webOS 5.6 only lets the settings one through), so they are probed.
LUNA_FEATURES: dict[str, str] = {
    "settings": LUNA_SET_SETTINGS,
    "reboot": LUNA_REBOOT,
    "screen_saver": LUNA_SCREEN_SAVER,
    "input_picker": LUNA_INPUT_PICKER,
}


def send_magic_packet(macs: list[str], broadcast: str = "255.255.255.255") -> None:
    """Wake the TV: magic packet to every known MAC (wired and Wi-Fi)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for mac in macs:
            packet = b"\xff" * 6 + bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", mac)) * 16
            for _ in range(3):
                sock.sendto(packet, (broadcast, 9))


class LgWebosTv:
    """A paired TV: aiowebostv client plus the extra state it does not track."""

    def __init__(self, client: WebOsClient) -> None:
        """Wrap a client."""
        self.client = client
        self.settings: dict[str, dict[str, Any]] = {}
        self.inputs: list[dict[str, Any]] = []
        self.configs: dict[str, Any] = {}
        self.network: dict[str, Any] = {}
        self.hdmi_signal: dict[str, Any] = {}
        self.power_on_reason: str | None = None
        self.options: dict[str, list[str]] = {}
        self._readable = {cat: list(keys) for cat, keys in READABLE_SETTINGS.items()}

    @property
    def macs(self) -> list[str]:
        """MAC addresses the TV reported (wired first)."""
        connection = self.client.tv_info.connection
        return [
            mac.lower()
            for key in ("wiredInfo", "wifiInfo")
            if (mac := connection.get(key, {}).get("macAddress"))
        ]

    @property
    def sound_outputs(self) -> list[str]:
        """Sound outputs this TV lists as usable (empty if it did not say)."""
        return self.options.get("soundOutput", [])

    def snapshot(self) -> dict[str, Any]:
        """Everything last heard from the TV, to show while it is off."""
        return {name: getattr(self, name) for name in CACHED}

    def restore(self, data: dict[str, Any]) -> None:
        """Load a snapshot saved by an earlier run."""
        for name in CACHED:
            if name in data:
                setattr(self, name, data[name])

    async def async_subscribe(self, on_update: Callable[[], Awaitable[None]]) -> None:
        """Subscribe to settings and input status; call right after connect."""

        def store(attr: str, pick: Callable[[dict[str, Any]], Any]) -> Any:
            async def handler(payload: dict[str, Any]) -> None:
                setattr(self, attr, pick(payload))
                await on_update()

            return handler

        def on_settings(category: str) -> Callable[[dict[str, Any]], Awaitable[None]]:
            async def handler(payload: dict[str, Any]) -> None:
                self.settings.setdefault(category, {}).update(
                    payload.get("settings", {})
                )
                await on_update()

            return handler

        for uri, handler in (
            (INPUT_STATUS, store("inputs", lambda p: p.get("devices", []))),
            (NETWORK_STATUS, store("network", lambda p: p)),
            (HDMI_SIGNAL, store("hdmi_signal", lambda p: p)),
            (POWER_ON_REASON, store("power_on_reason", lambda p: p.get("reason"))),
        ):
            # Not every release has every service; a missing one is not an error.
            with suppress(WebOsTvCommandError):
                await self.client.subscribe(handler, uri)
        for category, keys in self._readable.items():
            await self._subscribe_settings(category, keys, on_settings(category))
        with suppress(WebOsTvCommandError):
            res = await self.client.request(GET_CONFIGS, {"configNames": CONFIG_NAMES})
            self.configs = res.get("configs", {})
        for category, key in DESCRIBED_SETTINGS:
            # The description lists what this model offers right now (HDR
            # picture modes only show up while HDR content plays).
            with suppress(WebOsTvCommandError, LookupError):
                res = await self.client.request(
                    GET_SETTING_DESC, {"category": category, "keys": [key]}
                )
                self.options[key] = [
                    v["value"]
                    for v in res["results"][0]["values"]["arrayExt"]
                    if v.get("active") and v.get("visible")
                ]
        await on_update()

    async def _subscribe_settings(
        self,
        category: str,
        keys: list[str],
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Subscribe to a category, dropping the keys this TV refuses."""
        while keys:
            try:
                await self.client.subscribe(
                    handler, GET_SETTINGS, {"category": category, "keys": keys}
                )
            except WebOsTvCommandError as err:
                refused = [key for key in keys if re.search(rf"\b{key}\b", str(err))]
                if not refused:
                    # webOS 24 fails the whole request without naming anything
                    # when a key is whitelisted but absent on the model
                    # (truMotionMode on a 60 Hz panel): ask one by one.
                    refused = [
                        key
                        for key in keys
                        if not await self._has_setting(category, key)
                    ]
                if not refused:
                    return
                for key in refused:
                    keys.remove(key)
            else:
                return

    async def _has_setting(self, category: str, key: str) -> bool:
        try:
            await self.client.request(
                GET_SETTINGS, {"category": category, "keys": [key]}
            )
        except WebOsTvCommandError:
            return False
        return True

    async def luna(self, uri: str, params: dict[str, Any] | None = None) -> None:
        """Call a luna method the gateway does not expose.

        A system alert may carry a luna call for its close event, and alerts
        run with system privileges: create one, close it, the call fires.
        There is no return path, so only the alert result is known.
        """
        call = {"uri": uri, "params": params or {}}
        res = await self.client.request(
            CREATE_ALERT,
            {
                "message": " ",
                "buttons": [{"label": "", "onClick": uri, "params": params or {}}],
                "onclose": call,
                "onfail": call,
            },
        )
        if (alert_id := res.get("alertId")) is None:
            raise WebOsTvCommandError(f"Alert was not created: {res}")
        await self.client.request(CLOSE_ALERT, {"alertId": alert_id})

    async def luna_allowed(self, uri: str) -> bool:
        """Whether an alert may carry this luna call, without making it.

        The TV validates the URI when the alert is created. Here it sits only
        in a button nobody presses, so closing the alert fires nothing.
        """
        try:
            res = await self.client.request(
                CREATE_ALERT,
                {"message": " ", "buttons": [{"label": "", "onClick": uri}]},
            )
        except WebOsTvCommandError:
            return False
        if alert_id := res.get("alertId"):
            await self.client.request(CLOSE_ALERT, {"alertId": alert_id})
        return True

    async def probe_luna(self) -> list[str]:
        """Names of the LUNA_FEATURES this firmware accepts."""
        return [
            name for name, uri in LUNA_FEATURES.items() if await self.luna_allowed(uri)
        ]

    async def set_settings(self, category: str, settings: dict[str, Any]) -> None:
        """Write system settings (any category/key the settings service has)."""
        await self.luna(LUNA_SET_SETTINGS, {"category": category, "settings": settings})

    async def screenshot(self) -> bytes | None:
        """Capture what is on screen as JPEG (protected content comes out black)."""
        res = await self.client.request(
            ONE_SHOT, {"path": "/tmp/capture.jpg", "method": "DISPLAY", "format": "JPG"}
        )
        if not (uri := res.get("imageUri")):
            return None
        session = self.client.client_session
        assert session is not None
        # The TV serves its resources with a self-signed certificate.
        async with session.get(uri, ssl=False) as response:
            return await response.read() if response.status == 200 else None

    async def type_text(self, text: str, *, replace: bool = False) -> None:
        """Type into the focused text field (the on-screen keyboard must be up)."""
        await self.client.request(INSERT_TEXT, {"text": text, "replace": replace})

    async def reboot(self) -> None:
        """Restart the TV."""
        await self.luna(LUNA_REBOOT, {"reason": "reset"})

    async def screen_saver(self) -> None:
        """Start the screen saver."""
        await self.luna(LUNA_SCREEN_SAVER, {"reason": "1"})

    async def input_picker(self) -> None:
        """Show the input picker on screen."""
        await self.luna(LUNA_INPUT_PICKER)

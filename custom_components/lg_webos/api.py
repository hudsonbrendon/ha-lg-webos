"""What the TV offers over SSAP beyond aiowebostv's own surface.

Everything here was observed on real TVs (see REVERSE_ENGINEERING.md):
readable settings, per-input device status, screenshots, and luna calls
tunnelled through a system alert.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
import copy
import hashlib
import os
import re
import secrets
import socket
import string
from typing import Any

from aiowebostv import WebOsClient, WebOsTvCommandError
from aiowebostv.handshake import REGISTRATION_MESSAGE
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

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

# Permissions an unsigned manifest may ask for that aiowebostv does not.
# Re-registering with the existing client key grants them silently.
EXTRA_PERMISSIONS = (
    "CONTROL_TIMER_INFO",
    "READ_TV_CONTENT_STATE",
    "READ_STORAGE_DEVICE_LIST",
    "CHECK_BLUETOOTH_DEVICE",
    "CONTROL_INPUT_JOYSTICK",
    "READ_RECORDING_STATE",
    "CONTROL_RECORDING",
    "READ_RECORDING_SCHEDULE",
    "CONTROL_TV_POWER",
    "CONTROL_USER_INFO",
    "READ_TV_PROGRAM_INFO",
)

TIMER_SETTINGS = "timer/getSettings"
TIMER_KEYS = [
    "onTimerEnable",
    "offTimerEnable",
    "onTimerHour",
    "onTimerMinute",
    "offTimerHour",
    "offTimerMinute",
    "onTimerVolume",
]
STORAGE_LIST = "com.webos.service.attachedstoragemanager/listDevices"
BLUETOOTH_RADIO = "com.webos.service.bluetooth/gap/isRadioOn"

LUNA_CEC_TARGET = "luna://com.webos.service.eim/cec/setCECUniqueId"
LUNA_CEC_KEY = "luna://com.webos.service.eim/cec/sendKeyEvent"
LUNA_IP_CONTROL_START = "luna://com.webos.tnp/com/palm/luna/private/ping"

# Key name -> TV key code that the EIM service turns into a CEC UI command
# (CKeyCode table recovered from the firmware).
CEC_KEYS: dict[str, int] = {
    "select": 0x1000004,
    "up": 0x1000013,
    "down": 0x1000015,
    "left": 0x1000012,
    "right": 0x1000014,
    "home": 0x1000053,
    "setup_menu": 0x1200004,
    "contents_menu": 0x1202002,
    "options": 0x1202004,
    "exit": 0x1000000,
    "info": 0x1200002,
    "guide": 0x1200056,
    "power": 0x1202000,
    "channel_up": 0x1200021,
    "channel_down": 0x1200022,
    "previous_channel": 0x1200024,
    "volume_up": 0x1000072,
    "volume_down": 0x1000070,
    "mute": 0x1000071,
    "play": 0x1000080,
    "pause": 0x1000085,
    "stop": 0x1000081,
    "record": 0x1000084,
    "rewind": 0x10000C5,
    "fast_forward": 0x1000102,
    "next": 0x1000083,
    "previous": 0x1000082,
    "red": 0x1200011,
    "green": 0x1200012,
    "yellow": 0x1200013,
    "blue": 0x1200014,
    **{str(n): 0x30 + n for n in range(10)},
}

IP_CONTROL_PORT = 9761
IP_CONTROL_TIMEOUT = 5
# PBKDF2 salt of tvlink-network-proxy (same in webOS 5 and 24 firmware).
IP_CONTROL_SALT = bytes.fromhex("6361b80e9bdca6638d0720f2cc568fb9")


class LgWebosClient(WebOsClient):
    """aiowebostv client that pairs with the extra permissions."""

    def registration_msg(self) -> dict[str, Any]:
        """Registration message with EXTRA_PERMISSIONS added."""
        msg: dict[str, Any] = copy.deepcopy(REGISTRATION_MESSAGE)
        permissions = msg["payload"]["manifest"]["permissions"]
        permissions.extend(p for p in EXTRA_PERMISSIONS if p not in permissions)
        if self.client_key:
            msg["payload"]["client-key"] = self.client_key
        return msg


def new_ip_control_code() -> str:
    """A key code like the TV generates: 8 upper-case letters and digits."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


class IpControl:
    """LG IP Control (TCP 9761): AES-128, one command per connection."""

    def __init__(self, host: str, code: str) -> None:
        """Derive the AES key from the 8-character key code."""
        self.host = host
        self._key = hashlib.pbkdf2_hmac(
            "sha256", code.encode(), IP_CONTROL_SALT, 16384, 16
        )

    def encrypt(self, command: str, iv: bytes | None = None) -> bytes:
        """IV encrypted with ECB, then the CR-terminated command with CBC."""
        iv = iv or os.urandom(16)
        data = (command + "\r").encode()
        pad = 16 - len(data) % 16
        data += bytes([pad]) * pad
        ecb = Cipher(algorithms.AES(self._key), modes.ECB()).encryptor()
        cbc = Cipher(algorithms.AES(self._key), modes.CBC(iv)).encryptor()
        return ecb.update(iv) + ecb.finalize() + cbc.update(data) + cbc.finalize()

    def decrypt(self, blob: bytes) -> str:
        """Inverse of encrypt; the answer ends at the first newline."""
        ecb = Cipher(algorithms.AES(self._key), modes.ECB()).decryptor()
        iv = ecb.update(blob[:16]) + ecb.finalize()
        cbc = Cipher(algorithms.AES(self._key), modes.CBC(iv)).decryptor()
        data = cbc.update(blob[16:]) + cbc.finalize()
        # The answer ends with a newline; padding bytes are all below 0x20.
        line = data.split(b"\n")[0].rstrip(bytes(range(0x20)))
        return line.decode(errors="replace").strip()

    async def send(self, command: str) -> str:
        """Send one command and return the answer (OK, VOL:30, ...)."""
        # An incomplete command gets no answer at all: the timeout is the error.
        async with asyncio.timeout(IP_CONTROL_TIMEOUT):
            reader, writer = await asyncio.open_connection(self.host, IP_CONTROL_PORT)
            try:
                writer.write(self.encrypt(command))
                await writer.drain()
                blob = await reader.read(4096)
            finally:
                writer.close()
                with suppress(OSError):
                    await writer.wait_closed()
        return self.decrypt(blob)


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
    "storage",
    "bluetooth_on",
    "unreadable",
    "pending",
)

# Luna calls behind entities. Firmware decides which ones an alert may carry
# (webOS 5.6 only lets the settings one through), so they are probed.
LUNA_FEATURES: dict[str, str] = {
    "settings": LUNA_SET_SETTINGS,
    "reboot": LUNA_REBOOT,
    "screen_saver": LUNA_SCREEN_SAVER,
    "input_picker": LUNA_INPUT_PICKER,
    "cec": LUNA_CEC_KEY,
    "ip_control": LUNA_IP_CONTROL_START,
}
# Bump when LUNA_FEATURES changes, so existing entries probe again.
LUNA_PROBE_VERSION = 3


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
        self.storage: list[dict[str, Any]] = []
        self.bluetooth_on: bool | None = None
        # Keys this TV refused to hand out (candidates for write-only entities).
        self.unreadable: dict[str, list[str]] = {}
        # Setting writes made while the TV was unreachable, applied on connect.
        self.pending: dict[str, dict[str, Any]] = {}
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
            (STORAGE_LIST, store("storage", lambda p: p.get("devices", []))),
            (BLUETOOTH_RADIO, store("bluetooth_on", lambda p: p.get("radioOn"))),
        ):
            # Not every release has every service; a missing one is not an error.
            with suppress(WebOsTvCommandError):
                await self.client.subscribe(handler, uri)
        for category, keys in self._readable.items():
            await self._subscribe_settings(category, keys, on_settings(category))
        self.unreadable = {
            category: [k for k in READABLE_SETTINGS[category] if k not in keys]
            for category, keys in self._readable.items()
        }
        # Timers live in the "time" category, only reachable through this URI
        # (CONTROL_TIMER_INFO). It never answers a plain request: subscribe.
        with suppress(WebOsTvCommandError):
            await self.client.subscribe(
                on_settings("time"), TIMER_SETTINGS, {"keys": TIMER_KEYS}
            )
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
        except WebOsTvCommandError as err:
            # Only an explicit refusal counts. Anything else (TV still waking
            # up, alert service busy) leaves the question open: raise, so the
            # probe is not stored and runs again on the next connect.
            if "Not allowed" in str(err):
                return False
            raise
        if alert_id := res.get("alertId"):
            await self.client.request(CLOSE_ALERT, {"alertId": alert_id})
        return True

    async def probe_luna(self) -> list[str]:
        """Names of the LUNA_FEATURES this firmware accepts."""
        return [
            name for name, uri in LUNA_FEATURES.items() if await self.luna_allowed(uri)
        ]

    async def set_settings(self, category: str, settings: dict[str, Any]) -> bool:
        """Write system settings (any category/key the settings service has).

        With the TV unreachable the write is queued (see flush_pending) and
        shown right away. Returns True when it went out now.
        """
        self.settings.setdefault(category, {}).update(settings)
        if not self.client.is_connected():
            self.pending.setdefault(category, {}).update(settings)
            return False
        await self.luna(LUNA_SET_SETTINGS, {"category": category, "settings": settings})
        return True

    async def flush_pending(self) -> dict[str, dict[str, Any]]:
        """Apply the writes queued while the TV was off; returns what was sent."""
        sent: dict[str, dict[str, Any]] = {}
        for category in list(self.pending):
            settings = self.pending[category]
            await self.luna(
                LUNA_SET_SETTINGS, {"category": category, "settings": settings}
            )
            # Dropped only once sent; the TV's own push confirms the value.
            del self.pending[category]
            sent[category] = settings
        return sent

    def not_applied(self, sent: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Readable keys whose value the TV did not confirm after a flush."""
        missing: dict[str, dict[str, Any]] = {}
        for category, settings in sent.items():
            reported = self.settings.get(category, {})
            for key, value in settings.items():
                readable = key in self._readable.get(category, []) or (
                    category == "time" and key in TIMER_KEYS
                )
                if readable and str(reported.get(key)) != str(value):
                    missing.setdefault(category, {})[key] = value
        return missing

    @property
    def cec_devices(self) -> dict[str, dict[str, Any]]:
        """CEC devices by input id: name, unique id and HDMI port."""
        found: dict[str, dict[str, Any]] = {}
        for device in self.inputs:
            for sub in device.get("subList", []):
                if sub.get("id") == "SIMPLINK" and sub.get("uniqueId") is not None:
                    found[device["id"]] = {
                        "name": sub.get("osdName") or device.get("label"),
                        "unique_id": sub["uniqueId"],
                        "port": device.get("port"),
                    }
        return found

    async def cec_key(self, input_id: str, key: str) -> None:
        """Press a remote key on the device behind an input, over HDMI-CEC."""
        device = self.cec_devices.get(input_id)
        if device is None:
            raise WebOsTvCommandError(f"No CEC device on {input_id}")
        if key not in CEC_KEYS:
            raise WebOsTvCommandError(f"Unknown CEC key {key}")
        target = {"uniqueId": device["unique_id"]}
        if device["port"] is not None:
            target["hdmiPort"] = device["port"]
        await self.luna(LUNA_CEC_TARGET, target)
        await self.luna(LUNA_CEC_KEY, {"key": CEC_KEYS[key]})

    async def enable_ip_control(self, code: str) -> None:
        """Turn LG IP Control on with our own key code and start the service.

        The service reads the key from the settings when it starts, so the
        key goes in first. It keeps running across reboots once enabled.
        """
        await self.luna(
            LUNA_SET_SETTINGS,
            {
                "category": "option",
                "settings": {"IPControlSecureKey": code, "enableIpControl": "on"},
            },
        )
        await asyncio.sleep(1)
        await self.luna(LUNA_IP_CONTROL_START)

    async def disable_ip_control(self) -> None:
        """Turn LG IP Control off (the running service stops at the next boot)."""
        await self.luna(
            LUNA_SET_SETTINGS,
            {"category": "option", "settings": {"enableIpControl": "off"}},
        )

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

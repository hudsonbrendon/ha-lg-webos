"""Sensors for LG webOS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .const import LIVE_TV_APP_ID
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_add_dynamic

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LgWebosSensorDescription(SensorEntityDescription):
    """A sensor read from the coordinator."""

    value_fn: Callable[[LgWebosCoordinator], Any]
    attributes_fn: Callable[[LgWebosCoordinator], dict[str, Any]] | None = None


def _input(c: LgWebosCoordinator) -> dict[str, Any]:
    app_id = c.client.tv_state.current_app_id
    return next((i for i in c.tv.inputs if i.get("appId") == app_id), {})


def _app(c: LgWebosCoordinator) -> str | None:
    """Foreground app title; inputs are apps too but only carry a label."""
    state = c.client.tv_state
    app_id = state.current_app_id
    title = state.apps.get(app_id or "", {}).get("title")
    return title or _input(c).get("label") or app_id or None


def _channel(c: LgWebosCoordinator) -> dict[str, Any]:
    state = c.client.tv_state
    if state.current_app_id != LIVE_TV_APP_ID:
        return {}
    return state.current_channel or {}


def _link(c: LgWebosCoordinator) -> dict[str, Any]:
    """The connected interface (wired wins), as the connection manager reports it."""
    for kind in ("wired", "wifi"):
        link: dict[str, Any] = c.tv.network.get(kind, {})
        if link.get("state") == "connected":
            return {"kind": kind, **link}
    return {}


def _network(c: LgWebosCoordinator) -> str | None:
    """Wi-Fi network name, or "wired"."""
    link = _link(c)
    return link.get("ssid") or link.get("kind")


def _usb(c: LgWebosCoordinator) -> list[dict[str, Any]]:
    """Storage the user plugged in (the list also has built-in sample folders)."""
    return [
        d
        for d in c.tv.storage
        if not str(d.get("deviceType", "")).startswith("internal")
    ]


SENSORS = (
    LgWebosSensorDescription(
        key="usb_storage",
        translation_key="usb_storage",
        value_fn=lambda c: len(_usb(c)),
        attributes_fn=lambda c: {
            "devices": [d.get("deviceName") for d in _usb(c)],
        },
    ),
    LgWebosSensorDescription(
        key="power_state",
        translation_key="power_state",
        value_fn=lambda c: c.client.tv_state.power_state.get("state"),
        attributes_fn=lambda c: {
            k: v
            for k, v in c.client.tv_state.power_state.items()
            if k not in ("state", "returnValue", "subscribed")
        },
    ),
    LgWebosSensorDescription(
        key="app",
        translation_key="app",
        value_fn=_app,
        attributes_fn=lambda c: {"app_id": c.client.tv_state.current_app_id},
    ),
    LgWebosSensorDescription(
        key="input",
        translation_key="input",
        value_fn=lambda c: _input(c).get("label"),
        attributes_fn=lambda c: {"input_id": _input(c).get("id")},
    ),
    LgWebosSensorDescription(
        key="channel",
        translation_key="channel",
        # Channels found without a name (antenna, no guide) still have a number.
        value_fn=lambda c: (
            _channel(c).get("channelName") or _channel(c).get("channelNumber")
        ),
        attributes_fn=lambda c: {
            "number": _channel(c).get("channelNumber"),
            "channel_id": _channel(c).get("channelId"),
        },
    ),
    LgWebosSensorDescription(
        key="power_on_reason",
        translation_key="power_on_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.tv.power_on_reason,
    ),
    LgWebosSensorDescription(
        key="network",
        translation_key="network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_network,
        attributes_fn=lambda c: {
            k: v
            for k, v in _link(c).items()
            if k in ("ipAddress", "gateway", "dns1", "method", "connectedChannel")
        },
    ),
    LgWebosSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _link(c).get("ipAddress"),
    ),
    LgWebosSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.tv.configs.get("tv.nyx.firmwareVersion"),
    ),
    LgWebosSensorDescription(
        key="webos_version",
        translation_key="webos_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (
            c.tv.configs.get("tv.nyx.platformVersion")
            or c.client.tv_info.hello.get("deviceOSReleaseVersion")
        ),
    ),
)


def input_device(device: dict[str, Any]) -> dict[str, Any]:
    """What is plugged into an input, from CEC and LG's device detection."""
    info: dict[str, Any] = {"input_id": device.get("id")}
    for sub in device.get("subList", []):
        if sub.get("id") == "SIMPLINK":
            info["cec_name"] = sub.get("osdName")
            info["cec_vendor_id"] = sub.get("vendorId")
        elif sub.get("id") == "URCU":
            info["detected_type"] = sub.get("serviceType")
            info["detected_brand"] = sub.get("brandName")
    return info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up fixed sensors plus one per input once the TV lists them."""
    coordinator = entry.runtime_data
    async_add_entities(LgWebosSensor(coordinator, d) for d in SENSORS)
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: (i["id"] for i in c.tv.inputs if "id" in i),
        lambda input_id: LgWebosInputSensor(coordinator, input_id),
    )


class LgWebosSensor(LgWebosEntity, SensorEntity):
    """A TV sensor."""

    entity_description: LgWebosSensorDescription
    _needs = "nothing"

    @property
    def native_value(self) -> Any:
        """Current value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra details."""
        fn = self.entity_description.attributes_fn
        return fn(self.coordinator) if fn else None


class LgWebosInputSensor(LgWebosEntity, SensorEntity):
    """The device on an input: its label, plus what CEC says about it."""

    _attr_translation_key = "input_device"
    _needs = "nothing"

    def __init__(self, coordinator: LgWebosCoordinator, input_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._input_id = input_id
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_input_{input_id}"
        self._attr_translation_placeholders = {"input": input_id.replace("_", " ")}

    @property
    def _device(self) -> dict[str, Any]:
        return next((i for i in self.tv.inputs if i.get("id") == self._input_id), {})

    @property
    def native_value(self) -> str | None:
        """Label shown on the TV for this input."""
        return self._device.get("label")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """CEC and detection details."""
        return input_device(self._device)

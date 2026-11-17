"""Switches for LG webOS: screen and on/off system settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LgWebosConfigEntry
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_add_dynamic, async_call

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LgWebosSwitchDescription(SwitchEntityDescription):
    """A boolean system setting."""

    category: str
    on: str = "on"
    off: str = "off"


SWITCHES = {
    d.key: d
    for d in (
        LgWebosSwitchDescription(key="simplinkEnable", category="other"),
        LgWebosSwitchDescription(
            key="wolwowlOnOff", category="network", on="true", off="false"
        ),
        LgWebosSwitchDescription(key="bleAdvertisingOnOff", category="network"),
        LgWebosSwitchDescription(key="audioGuidance", category="option"),
        LgWebosSwitchDescription(key="livePlus", category="option"),
        LgWebosSwitchDescription(key="eArcSupport", category="sound"),
        LgWebosSwitchDescription(key="avSync", category="sound"),
        LgWebosSwitchDescription(key="quickStartMode", category="option"),
        LgWebosSwitchDescription(key="eyeComfortMode", category="picture"),
        LgWebosSwitchDescription(key="motionEyeCare", category="picture"),
        LgWebosSwitchDescription(key="realCinema", category="picture"),
        LgWebosSwitchDescription(key="alwaysOn", category="general"),
        LgWebosSwitchDescription(key="homeAutoLaunch", category="general"),
        LgWebosSwitchDescription(key="homePromotion", category="general"),
        LgWebosSwitchDescription(key="automaticUpdate", category="support"),
        LgWebosSwitchDescription(key="onTimerEnable", category="time"),
        LgWebosSwitchDescription(key="offTimerEnable", category="time"),
        *(
            LgWebosSwitchDescription(
                key=f"uhdDeepColorHDMI{n}",
                category="other",
                translation_key="uhd_deep_color",
                translation_placeholders={"input": f"HDMI {n}"},
            )
            for n in range(1, 5)
        ),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the screen switch and the setting switches this TV exposes."""
    coordinator = entry.runtime_data
    async_add_entities([LgWebosScreenSwitch(coordinator)])
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: ["remote_lock"] if c.ip_control is not None else [],
        lambda _: LgWebosRemoteLockSwitch(coordinator),
    )
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: (
            k for k, d in SWITCHES.items() if k in c.tv.settings.get(d.category, {})
        ),
        lambda key: LgWebosSettingSwitch(entry.runtime_data, SWITCHES[key]),
    )


class LgWebosScreenSwitch(LgWebosEntity, SwitchEntity):
    """Panel on/off while the TV keeps running (sound stays)."""

    _attr_translation_key = "screen"

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_screen"

    @property
    def is_on(self) -> bool:
        """Whether the panel is lit."""
        return self.client.tv_state.is_screen_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Light the panel."""
        await async_call(self.client.set_screen_state(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Blank the panel."""
        await async_call(self.client.set_screen_state(False))


class LgWebosSettingSwitch(LgWebosEntity, SwitchEntity):
    """A boolean system setting."""

    entity_description: LgWebosSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG
    # Changes made while the TV is off are queued and applied when it wakes.
    _needs = "nothing"

    def __init__(
        self, coordinator: LgWebosCoordinator, description: LgWebosSwitchDescription
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, description)
        if description.translation_key is None:
            self._attr_translation_key = description.key.lower()

    @property
    def is_on(self) -> bool | None:
        """Current value."""
        d = self.entity_description
        value = self.tv.settings.get(d.category, {}).get(d.key)
        return None if value is None else str(value).lower() == d.on

    async def _set(self, value: str) -> None:
        d = self.entity_description
        await async_call(self.tv.set_settings(d.category, {d.key: value}))
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self._set(self.entity_description.on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self._set(self.entity_description.off)


class LgWebosRemoteLockSwitch(LgWebosEntity, SwitchEntity, RestoreEntity):
    """Lock the physical remote and front keys (LG IP Control).

    The TV has no way to read this back: the state is the last one set.
    """

    _attr_translation_key = "remote_lock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_assumed_state = True

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_remote_lock"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Bring back the last state set."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"

    async def _set(self, on: bool) -> None:
        ip = self.coordinator.require_ip_control()
        await async_call(ip.send(f"REMOTECONTROLLER_LOCK {'on' if on else 'off'}"))
        self._attr_is_on = on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock the remote."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unlock the remote."""
        await self._set(False)

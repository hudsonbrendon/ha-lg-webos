"""Selects for LG webOS: sound output and the enumerated settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LgWebosConfigEntry
from .const import SOUND_OUTPUTS
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_add_dynamic, async_call

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LgWebosSelectDescription(SelectEntityDescription):
    """An enumerated system setting; options as listed by the firmware."""

    category: str
    values: tuple[str, ...]


def _select(category: str, key: str, values: str) -> LgWebosSelectDescription:
    return LgWebosSelectDescription(
        key=key,
        translation_key=key.lower(),
        category=category,
        values=tuple(values.split()),
        entity_category=EntityCategory.CONFIG,
    )


# LG IP Control names (ipc_mapping_table.json); the TV ignores what it lacks.
ASPECT_RATIOS = ["16by9", "setbyoriginal", "4by3", "justscan", "zoom", "21by9"]
# Settings webOS 5 refuses to hand out but accepts as writes.
ASSUMED = ("pictureMode", "energySaving", "soundMode")

# The value lists are the union across models; the TV refuses what it lacks.
SELECTS = {
    d.key: d
    for d in (
        _select(
            "picture",
            "pictureMode",
            "vivid normal eco cinema sports game photo filmMaker expert1 expert2 "
            "personalized hdrVivid hdrStandard hdrEco hdrCinema hdrCinemaBright "
            "hdrGame hdrFilmMaker hdrPersonalized dolbyHdrVivid dolbyHdrStandard "
            "dolbyHdrCinema dolbyHdrCinemaBright dolbyHdrGame dolbyHdrPersonalized",
        ),
        _select("picture", "energySaving", "auto off min med max screen_off"),
        _select("picture", "dynamicContrast", "off low medium high"),
        _select("picture", "peakBrightness", "off low medium high"),
        _select(
            "picture", "truMotionMode", "off cinemaClear natural smooth clear user"
        ),
        _select(
            "picture", "colorGamut", "auto native wide extended dynamic adobeRGB dci-p3"
        ),
        _select("picture", "gamma", "low medium high1 high2 mediumHavingLevel"),
        _select("picture", "blackLevel", "auto low high"),
        _select("picture", "superResolution", "off low medium high"),
        _select("picture", "noiseReduction", "off low medium high auto"),
        _select("picture", "smoothGradation", "off low medium high"),
        _select("picture", "hdrDynamicToneMapping", "on off HGIG"),
        _select(
            "sound",
            "soundMode",
            "aiSoundPlus aiSound standard movie news sports music game bass asc "
            "aiSound_soundbar game_rts game_fps dtsVirtualX custom bassBlast "
            "voiceEnhance bassBoost customEq personalized precision",
        ),
        _select("sound", "soundOutputDigital", "pcm auto passThrough"),
        _select("general", "tvOnScreen", "effect liveTV"),
        _select(
            "general",
            "lifeOnScreenMode",
            "none off lifeOnScreen alwaysReady allEnabled",
        ),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sound output, readable settings and write-only ones."""
    coordinator = entry.runtime_data
    async_add_entities([LgWebosSoundOutputSelect(coordinator)])
    if coordinator.ip_control is not None:
        async_add_entities([LgWebosAspectRatioSelect(coordinator)])
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda c: (
            k
            for k in ASSUMED
            if "settings" in c.luna_allowed
            and k in c.tv.unreadable.get(SELECTS[k].category, [])
        ),
        lambda key: LgWebosAssumedSelect(entry.runtime_data, SELECTS[key]),
    )
    async_add_dynamic(
        entry,
        async_add_entities,
        # Some keys are a value per signal type on newer firmware (blackLevel):
        # only plain values make a select.
        lambda c: (
            k
            for k, d in SELECTS.items()
            if isinstance(c.tv.settings.get(d.category, {}).get(k), str)
        ),
        lambda key: LgWebosSettingSelect(entry.runtime_data, SELECTS[key]),
    )


class LgWebosSoundOutputSelect(LgWebosEntity, SelectEntity):
    """Where the sound goes."""

    _attr_translation_key = "sound_output"

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_sound_output"

    @property
    def options(self) -> list[str]:
        """Outputs this TV lists as usable, else every known one."""
        return self.tv.sound_outputs or SOUND_OUTPUTS

    @property
    def current_option(self) -> str | None:
        """Current output."""
        output = self.client.tv_state.sound_output
        return output if output in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Route the sound."""
        await async_call(self.client.change_sound_output(option))


class LgWebosSettingSelect(LgWebosEntity, SelectEntity):
    """An enumerated system setting; changes made while off wait for the TV."""

    entity_description: LgWebosSelectDescription
    _needs = "nothing"
    _needs = "connected"

    @property
    def current_option(self) -> str | None:
        """Current value."""
        d = self.entity_description
        value = self.tv.settings.get(d.category, {}).get(d.key)
        return None if value is None else str(value)

    @property
    def options(self) -> list[str]:
        """What the TV says it offers, else every value the firmware knows.

        The current value is always included (it may be outside the list the
        TV describes, like an HDR mode read while SDR is described).
        """
        d = self.entity_description
        values = list(self.tv.options.get(d.key) or d.values)
        if (current := self.current_option) and current not in values:
            values.append(current)
        return values

    async def async_select_option(self, option: str) -> None:
        """Write the setting."""
        d = self.entity_description
        await async_call(self.tv.set_settings(d.category, {d.key: option}))
        self.async_write_ha_state()


class LgWebosAssumedSelect(LgWebosEntity, SelectEntity, RestoreEntity):
    """A setting this firmware lets us write but not read (webOS 5).

    Shows the last value sent from Home Assistant; a change made with the
    remote is not seen.
    """

    entity_description: LgWebosSelectDescription
    _attr_assumed_state = True
    _needs = "nothing"

    def __init__(
        self, coordinator: LgWebosCoordinator, description: LgWebosSelectDescription
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, description)
        # Own id: the readable select of the same key may exist on other models.
        self._attr_unique_id = f"{self._attr_unique_id}_assumed"
        self._attr_options = list(description.values)
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        """Bring back the last value sent."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        """Write the setting."""
        d = self.entity_description
        await async_call(self.tv.set_settings(d.category, {d.key: option}))
        self._attr_current_option = option
        self.async_write_ha_state()


class LgWebosAspectRatioSelect(LgWebosEntity, SelectEntity, RestoreEntity):
    """Aspect ratio through LG IP Control (write only)."""

    _attr_translation_key = "aspect_ratio"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_assumed_state = True
    _attr_options = ASPECT_RATIOS

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_aspect_ratio"
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        """Bring back the last value sent."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ASPECT_RATIOS:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        """Send the aspect ratio."""
        ip = self.coordinator.require_ip_control()
        await async_call(ip.send(f"ASPECT_RATIO {option}"))
        self._attr_current_option = option
        self.async_write_ha_state()

"""Selects for LG webOS: sound output and the enumerated settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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
    """Set up sound output plus the setting selects this TV lets us read."""
    async_add_entities([LgWebosSoundOutputSelect(entry.runtime_data)])
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
    """An enumerated system setting."""

    entity_description: LgWebosSelectDescription
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

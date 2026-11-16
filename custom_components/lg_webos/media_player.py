"""Media player for LG webOS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature as Feature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosConfigEntry
from .const import DOMAIN, LIVE_TV_APP_ID, SOUND_OUTPUTS
from .coordinator import LgWebosCoordinator
from .entity import LgWebosEntity, async_call

PARALLEL_UPDATES = 0

BASE_FEATURES = (
    Feature.TURN_ON
    | Feature.TURN_OFF
    | Feature.NEXT_TRACK
    | Feature.PREVIOUS_TRACK
    | Feature.PLAY
    | Feature.PAUSE
    | Feature.STOP
    | Feature.SELECT_SOURCE
    | Feature.SELECT_SOUND_MODE
    | Feature.PLAY_MEDIA
    | Feature.BROWSE_MEDIA
    | Feature.VOLUME_MUTE
    | Feature.VOLUME_STEP
)
MEDIA_TYPE_INPUT = "input"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player."""
    async_add_entities([LgWebosMediaPlayer(entry.runtime_data)])


class LgWebosMediaPlayer(LgWebosEntity, MediaPlayerEntity):
    """The TV itself."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    _needs = "nothing"

    def __init__(self, coordinator: LgWebosCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.unique_id
        # ponytail: sources survive in memory only; after a restart with the
        # TV off the list is empty until it wakes.
        self._sources: dict[str, dict[str, Any]] = {}
        self._attr_sound_mode_list = SOUND_OUTPUTS
        self._update()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update()
        super()._handle_coordinator_update()

    def _update(self) -> None:
        state = self.client.tv_state
        if not self.coordinator.is_on:
            self._attr_state = MediaPlayerState.OFF
            return
        self._attr_state = MediaPlayerState.ON
        for media in state.media_state:
            self._attr_state = {
                "playing": MediaPlayerState.PLAYING,
                "paused": MediaPlayerState.PAUSED,
                "unloaded": MediaPlayerState.IDLE,
            }.get(media.get("playState"), self._attr_state)
        self._attr_is_volume_muted = state.muted
        self._attr_volume_level = None if state.volume is None else state.volume / 100
        self._attr_sound_mode = state.sound_output
        self._attr_sound_mode_list = self.tv.sound_outputs or SOUND_OUTPUTS
        sources = {app["title"]: app for app in state.apps.values()}
        sources |= {source["label"]: source for source in state.inputs.values()}
        if sources:
            self._sources = sources
        app_id = state.current_app_id
        self._attr_app_id = app_id
        self._attr_source = next(
            (
                name
                for name, source in self._sources.items()
                if app_id in (source.get("appId"), source["id"])
            ),
            None,
        )
        self._attr_source_list = sorted(self._sources)
        app = state.apps.get(app_id or "", {})
        self._attr_app_name = app.get("title")
        icon = app.get("largeIcon", "")
        self._attr_media_image_url = (
            icon if icon.startswith("http") else app.get("icon")
        )
        live = app_id == LIVE_TV_APP_ID
        channel = state.current_channel or {}
        self._attr_media_content_type = MediaType.CHANNEL if live else None
        self._attr_media_title = (
            channel.get("channelName") or channel.get("channelNumber") if live else None
        )
        self._attr_media_channel = channel.get("channelNumber") if live else None

    @property
    def supported_features(self) -> Feature:
        """Volume can only be set when the TV drives the speakers."""
        if self.client.tv_state.sound_output in ("external_speaker", "lineout"):
            return BASE_FEATURES
        return BASE_FEATURES | Feature.VOLUME_SET

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Icons live on the TV behind a self-signed certificate: proxy them."""
        return False

    async def _async_fetch_image(self, url: str) -> tuple[bytes | None, str | None]:
        session = self.client.client_session
        assert session is not None
        try:
            async with session.get(url, ssl=False) as response:
                if response.status == 200:
                    return await response.read(), response.content_type
        except TimeoutError, OSError:
            pass
        return None, None

    async def async_turn_on(self) -> None:
        """Wake the TV (no automation needed, unlike the built-in integration)."""
        await self.coordinator.async_wake()

    async def async_turn_off(self) -> None:
        """Turn the TV off."""
        await async_call(self.client.power_off())

    async def async_volume_up(self) -> None:
        """Volume up."""
        await async_call(self.client.volume_up())

    async def async_volume_down(self) -> None:
        """Volume down."""
        await async_call(self.client.volume_down())

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume."""
        await async_call(self.client.set_volume(round(volume * 100)))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await async_call(self.client.set_mute(mute))

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Route the sound to another output."""
        await async_call(self.client.change_sound_output(sound_mode))

    async def async_select_source(self, source: str) -> None:
        """Open an app or switch to an input."""
        if (target := self._sources.get(source)) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="source_not_found",
                translation_placeholders={"source": source},
            )
        if "label" in target:
            await async_call(self.client.set_input(target["id"]))
        else:
            await async_call(self.client.launch_app(target["id"]))

    async def async_media_play(self) -> None:
        """Play."""
        await async_call(self.client.play())

    async def async_media_pause(self) -> None:
        """Pause."""
        await async_call(self.client.pause())

    async def async_media_stop(self) -> None:
        """Stop."""
        await async_call(self.client.stop())

    async def async_media_next_track(self) -> None:
        """Channel up on live TV, fast forward elsewhere."""
        if self.client.tv_state.current_app_id == LIVE_TV_APP_ID:
            await async_call(self.client.channel_up())
        else:
            await async_call(self.client.fast_forward())

    async def async_media_previous_track(self) -> None:
        """Channel down on live TV, rewind elsewhere."""
        if self.client.tv_state.current_app_id == LIVE_TV_APP_ID:
            await async_call(self.client.channel_down())
        else:
            await async_call(self.client.rewind())

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Open a channel, an app, an input or a URL."""
        if media_type == MediaType.APP:
            await async_call(self.client.launch_app(media_id))
        elif media_type == MEDIA_TYPE_INPUT:
            await async_call(self.client.set_input(media_id))
        elif media_type == MediaType.URL:
            await async_call(
                self.client.request("system.launcher/open", {"target": media_id})
            )
        elif media_type == MediaType.CHANNEL:
            channels = self.client.tv_state.channels or []
            wanted = media_id.lower()
            match = next(
                (
                    c
                    for c in channels
                    if wanted in (c["channelName"].lower(), c["channelNumber"])
                ),
                None,
            ) or next((c for c in channels if wanted in c["channelName"].lower()), None)
            if match is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="channel_not_found",
                    translation_placeholders={"channel": media_id},
                )
            await async_call(self.client.set_channel(match["channelId"]))
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="media_type_not_supported",
                translation_placeholders={"media_type": str(media_type)},
            )

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Apps, inputs and channels as a browsable tree."""
        state = self.client.tv_state

        def node(
            title: str, kind: str, ident: str, image: str | None = None
        ) -> BrowseMedia:
            return BrowseMedia(
                title=title,
                media_class=MediaClass.CHANNEL
                if kind == MediaType.CHANNEL
                else MediaClass.APP,
                media_content_type=kind,
                media_content_id=ident,
                can_play=True,
                can_expand=False,
                thumbnail=self.get_browse_image_url(kind, ident) if image else None,
            )

        children = [
            node(s["label"], MEDIA_TYPE_INPUT, s["id"], s.get("icon"))
            for s in state.inputs.values()
        ]
        children += [
            node(a["title"], MediaType.APP, a["id"], a.get("icon"))
            for a in sorted(state.apps.values(), key=lambda a: a["title"].lower())
        ]
        children += [
            node(
                f"{c['channelNumber']} {c['channelName']}",
                MediaType.CHANNEL,
                c["channelNumber"],
            )
            for c in state.channels or []
        ]
        return BrowseMedia(
            title=self.coordinator.config_entry.title,
            media_class=MediaClass.DIRECTORY,
            media_content_type="root",
            media_content_id="root",
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.APP,
        )

    async def async_get_browse_image(
        self,
        media_content_type: MediaType | str,
        media_content_id: str,
        media_image_id: str | None = None,
    ) -> tuple[bytes | None, str | None]:
        """Proxy an app or input icon from the TV."""
        state = self.client.tv_state
        items = (
            state.inputs if media_content_type == MEDIA_TYPE_INPUT else state.apps
        ).values()
        item = next((i for i in items if i["id"] == media_content_id), None)
        url = (item or {}).get("icon", "")
        return (
            await self._async_fetch_image(url)
            if url.startswith("http")
            else (None, None)
        )

"""Setup, entities and actions against the fake TV."""

from unittest.mock import patch

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest

from custom_components.lg_webos.api import LUNA_SET_SETTINGS, send_magic_packet
from custom_components.lg_webos.const import DOMAIN

from .conftest import UUID, make_client


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def luna_calls(client):
    """Luna calls that went out through the alert trick."""
    return [
        (c.args[1]["onclose"]["uri"], c.args[1]["onclose"]["params"])
        for c in client.request.call_args_list
        if c.args[0] == "system.notifications/createAlert" and "onclose" in c.args[1]
    ]


async def test_entities(hass, client, entry):
    """A TV that is on yields the whole entity set with real values."""
    await setup(hass, entry)
    ids = {
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    state = lambda entity_id: hass.states.get(entity_id).state  # noqa: E731

    assert state("media_player.tv_da_sala") == "on"
    assert hass.states.get("media_player.tv_da_sala").attributes["source"] == "PS5"
    assert state("number.tv_da_sala_brightness") == "50.0"
    assert state("switch.tv_da_sala_simplink_hdmi_cec") == "on"
    assert state("switch.tv_da_sala_wake_on_lan") == "on"
    assert state("select.tv_da_sala_sound_output") == "tv_speaker"
    assert state("sensor.tv_da_sala_firmware") == "04.64.00"
    assert state("sensor.tv_da_sala_input") == "PS5"
    assert state("sensor.tv_da_sala_hdmi_2_device") == "PS5"
    assert (
        hass.states.get("sensor.tv_da_sala_hdmi_2_device").attributes["cec_name"]
        == "PlayStation 5"
    )
    assert state("binary_sensor.tv_da_sala_hdmi_2_plugged") == "on"
    assert hass.states.get("binary_sensor.tv_da_sala_hdmi_2_plugged").attributes[
        "signal"
    ]
    assert state("binary_sensor.tv_da_sala_internet") == "on"
    assert state("sensor.tv_da_sala_network") == "CASA"
    assert state("sensor.tv_da_sala_power_on_reason") == "wakeOnWiFi"
    assert hass.states.get("select.tv_da_sala_sound_output").attributes["options"] == [
        "tv_speaker",
        "external_arc",
    ]
    # AV has no plug sensing; refused settings create nothing.
    assert "binary_sensor.tv_da_sala_av_1_plugged" not in ids
    assert not any("picture_mode" in i for i in ids)
    # This firmware refuses the power luna calls: no buttons for them.
    assert entry.data["luna"] == {"firmware": "04.64.00", "allowed": ["settings"]}
    assert not any(i.startswith("button.") for i in ids)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, UUID), entry.entry_id
    )
    assert device.model == "60UN7310PSA"
    assert device.sw_version == "04.64.00"


async def test_settings_write_and_push(hass, client, entry):
    """Writes go out as luna calls; pushes from the TV update the entity."""
    await setup(hass, entry)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.tv_da_sala_brightness", "value": 51},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.tv_da_sala_wake_on_lan"},
        blocking=True,
    )
    assert luna_calls(client) == [
        (LUNA_SET_SETTINGS, {"category": "picture", "settings": {"brightness": 51}}),
        (
            LUNA_SET_SETTINGS,
            {"category": "network", "settings": {"wolwowlOnOff": "false"}},
        ),
    ]
    assert client.request.call_args.args == (
        "system.notifications/closeAlert",
        {"alertId": "alert-1"},
    )
    await client.subscriptions["picture"]({"settings": {"brightness": 51}})
    await hass.async_block_till_done()
    assert hass.states.get("number.tv_da_sala_brightness").state == "51.0"


async def test_tv_off(hass, entry, hass_storage):
    """A TV that is off shows its last known values and wakes by magic packet."""
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "data": {
            "settings": {"picture": {"brightness": "50"}},
            "configs": {"tv.nyx.firmwareVersion": "04.64.00"},
            "inputs": [{"id": "HDMI_2", "label": "PS5", "hdmiPlugIn": True}],
            "network": {"isInternetConnectionAvailable": True},
        },
    }
    fake = make_client(on=False)
    with patch("custom_components.lg_webos.WebOsClient", return_value=fake):
        await setup(hass, entry)
    assert hass.states.get("media_player.tv_da_sala").state == "off"
    # Read-only entities keep the last value; controls need the TV.
    assert hass.states.get("sensor.tv_da_sala_firmware").state == "04.64.00"
    assert hass.states.get("sensor.tv_da_sala_hdmi_2_device").state == "PS5"
    assert hass.states.get("binary_sensor.tv_da_sala_internet").state == "on"
    assert hass.states.get("sensor.tv_da_sala_power_state").state == "unknown"
    assert hass.states.get("number.tv_da_sala_brightness").state == "unavailable"
    assert hass.states.get("switch.tv_da_sala_screen").state == "unavailable"
    with patch("custom_components.lg_webos.coordinator.send_magic_packet") as wol:
        await hass.services.async_call(
            "media_player",
            "turn_on",
            {"entity_id": "media_player.tv_da_sala"},
            blocking=True,
        )
    wol.assert_called_once_with(["00:00:5e:00:53:01"])
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, UUID), entry.entry_id
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "button", {"device_id": device.id, "button": "home"}, blocking=True
        )


async def test_actions(hass, client, entry):
    """Integration actions reach the TV."""
    await setup(hass, entry)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, UUID), entry.entry_id
    )
    call = lambda name, **data: hass.services.async_call(  # noqa: E731
        DOMAIN,
        name,
        {"device_id": device.id, **data},
        blocking=True,
        return_response=name == "command",
    )
    await call("button", button="home")
    client.button.assert_awaited_with("HOME")
    assert await call("command", command="audio/getStatus") == {"returnValue": True}
    await call(
        "set_system_settings", category="picture", settings={"pictureMode": "cinema"}
    )
    assert luna_calls(client)[-1][1]["settings"] == {"pictureMode": "cinema"}
    await call("launch_app", app_id="netflix", content_id="x")
    client.request.assert_awaited_with(
        "system.launcher/launch", {"id": "netflix", "contentId": "x"}
    )
    await hass.services.async_call(
        "remote",
        "send_command",
        {
            "entity_id": "remote.tv_da_sala_remote",
            "command": ["up", "enter"],
            "delay_secs": 0,
        },
        blocking=True,
    )
    assert [c.args[0] for c in client.button.await_args_list[-2:]] == ["UP", "ENTER"]


def test_magic_packet():
    """The packet is 6 x FF then the MAC 16 times, to port 9."""
    with patch("custom_components.lg_webos.api.socket.socket") as sock:
        send_magic_packet(["00:00:5e:00:53:01"])
    packet, address = sock.return_value.__enter__.return_value.sendto.call_args.args
    assert packet == b"\xff" * 6 + bytes.fromhex("00005e005301") * 16
    assert address == ("255.255.255.255", 9)


async def test_newer_firmware_settings(hass, client, entry, monkeypatch):
    """A TV that lets more settings be read (webOS 24) grows more entities."""
    from . import conftest

    monkeypatch.setitem(
        conftest.SETTINGS,
        "picture",
        {**conftest.SETTINGS["picture"], "pictureMode": "filmMaker", "sharpness": "10"},
    )
    monkeypatch.setitem(conftest.SETTINGS, "general", {"homePromotion": "on"})
    # 60 Hz panel: truMotionMode is whitelisted but not there; blackLevel is a
    # value per signal type, not something a select can show.
    monkeypatch.setattr(conftest, "ABSENT", {"truMotionMode"})
    conftest.SETTINGS["picture"]["blackLevel"] = {"ntsc": "auto", "pal": "auto"}
    await setup(hass, entry)
    picture_mode = hass.states.get("select.tv_da_sala_picture_mode")
    assert picture_mode.state == "filmMaker"
    # Options come from the TV's own description, current value appended.
    assert picture_mode.attributes["options"] == ["cinema", "vivid", "filmMaker"]
    assert hass.states.get("number.tv_da_sala_sharpness").state == "10.0"
    assert hass.states.get("switch.tv_da_sala_home_promotions").state == "on"
    assert hass.states.get("select.tv_da_sala_black_level") is None
    assert hass.states.get("select.tv_da_sala_trumotion") is None
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.tv_da_sala_picture_mode", "option": "cinema"},
        blocking=True,
    )
    assert luna_calls(client)[-1] == (
        LUNA_SET_SETTINGS,
        {"category": "picture", "settings": {"pictureMode": "cinema"}},
    )


async def test_network_standby(hass, client, entry):
    """A TV that keeps its socket in standby still takes settings."""
    await setup(hass, entry)
    client.tv_state.is_on = False
    client.tv_state.power_state = {"state": "Active Standby"}
    entry.runtime_data.async_set_updated_data(None)
    await hass.async_block_till_done()
    assert hass.states.get("media_player.tv_da_sala").state == "off"
    assert hass.states.get("sensor.tv_da_sala_power_state").state == "Active Standby"
    assert hass.states.get("switch.tv_da_sala_screen").state == "unavailable"
    assert hass.states.get("number.tv_da_sala_brightness").state == "50.0"
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.tv_da_sala_brightness", "value": 40},
        blocking=True,
    )
    assert luna_calls(client)[-1][1]["settings"] == {"brightness": 40}

"""Config flow: manual pairing and import from the built-in integration."""

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lg_webos.const import CONF_MACS, DOMAIN

from .conftest import HOST, UUID


async def test_manual(hass, client):
    """Without built-in entries the flow asks for the host and pairs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST}
    )
    assert result["step_id"] == "pairing"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == UUID
    assert result["data"] == {
        "host": HOST,
        "client_secret": "key",
        CONF_MACS: ["00:00:5e:00:53:01", "00:00:5e:00:53:02"],
    }


async def test_import_native(hass, client):
    """Built-in entries import without touching the TV, MACs included."""
    for n, uuid in enumerate((UUID, "other-uuid")):
        native = MockConfigEntry(
            domain="webostv",
            title=f"TV {n}",
            unique_id=uuid,
            data={"host": f"192.0.2.{n}", "client_secret": f"key{n}"},
        )
        native.add_to_hass(hass)
        dr.async_get(hass).async_get_or_create(
            config_entry_id=native.entry_id,
            identifiers={("webostv", uuid)},
            connections={(dr.CONNECTION_NETWORK_MAC, f"aa:bb:cc:dd:ee:0{n}")},
        )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_native"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Straight from the built-in entry: the TV was not asked for anything yet.
    assert result["data"] == {
        "host": "192.0.2.0",
        "client_secret": "key0",
        CONF_MACS: ["aa:bb:cc:dd:ee:00"],
    }
    await hass.async_block_till_done()
    entries = hass.config_entries.async_entries(DOMAIN)
    assert {e.unique_id for e in entries} == {UUID, "other-uuid"}

"""Registration message keeps the library's unsigned fallback."""

from custom_components.lg_webos.api import EXTRA_PERMISSIONS, LgWebosClient


async def test_registration_msg_signed_and_unsigned() -> None:
    """Extra permissions ride on both the signed and the unsigned manifest."""
    client = LgWebosClient("192.0.2.1", "key")
    signed = client.registration_msg()["payload"]
    assert signed["client-key"] == "key"
    assert set(EXTRA_PERMISSIONS) <= set(signed["manifest"]["permissions"])

    client.signed_manifest = False  # what aiowebostv sets after a rejection
    unsigned = client.registration_msg()["payload"]["manifest"]
    assert "signatures" not in unsigned
    assert "signed" not in unsigned
    assert set(EXTRA_PERMISSIONS) <= set(unsigned["permissions"])

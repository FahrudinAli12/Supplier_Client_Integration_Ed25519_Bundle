import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.client_package_gateway import ClientPackageGateway, canonical_payload_bytes


class DummyAsyncClient:
    """Async client mock that avoids OS socket/threadpool event loop deadlocks."""

    def __init__(self, response: httpx.Response):
        self.response = response
        self.last_call = None

    async def post(self, url, content=None, headers=None, timeout=None):
        self.last_call = {"url": url, "content": content, "headers": headers}
        return self.response

    async def aclose(self):
        pass


def _run_async(coro):
    try:
        coro.send(None)
    except StopIteration:
        pass


def test_gateway_signs_canonical_payload_and_returns_cloud_receipt():
    async def _run():
        private_key = Ed25519PrivateKey.generate()
        private_hex = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()
        public_key = private_key.public_key()

        mock_resp = httpx.Response(201, json={
            "success": True,
            "status": "INGESTED",
            "package_id": 501,
            "package_code": "VRF-ABC123",
            "verification_code": "VC-1234ABCD",
            "manifest_hash": "a" * 64,
            "item_count": 1,
        })
        client = DummyAsyncClient(mock_resp)
        gateway = ClientPackageGateway(client=client)
        gateway.settings = SimpleNamespace(
            CLIENT_SUPABASE_URL="https://client-project.supabase.co",
            CLIENT_SUPABASE_PUBLISHABLE_KEY="client-publishable-key",
            CLIENT_SUPPLIER_DEVICE_ID="DEVICE-01",
            CLIENT_SUPPLIER_PRIVATE_KEY_HEX=private_hex,
        )

        result = await gateway.upload_package(
            hospital_code="RS001",
            package_code="vrf-abc123",
            items=[{"epc": "3000E280116060000204DE84B501", "nama_linen": " Sprei ", "kategori": " Linen "}],
            idempotency_key="DEVICE-01:10:VRF-ABC123",
            catatan=" Test paket ",
        )
        await client.aclose()

        assert result is not None
        assert result["verification_code"] == "VC-1234ABCD"

        body = json.loads(client.last_call["content"].decode("utf-8"))
        assert body["items"] == [{
            "epc": "E280116060000204DE84B501",
            "kategori": "Linen",
            "nama_linen": "Sprei",
        }]

        canonical = canonical_payload_bytes(
            package_code=body["package_code"],
            hospital_code=body["hospital_code"],
            idempotency_key=body["idempotency_key"],
            catatan=body["catatan"],
            items=body["items"],
        )
        digest = hashlib.sha256(canonical).hexdigest()
        assert digest == body["payload_digest"]

        headers = client.last_call["headers"]
        message = f"DEVICE-01:{headers['X-Supplier-Timestamp']}:{headers['X-Supplier-Nonce']}:{digest}".encode()
        public_key.verify(bytes.fromhex(headers["X-Supplier-Signature"]), message)

    _run_async(_run())


def test_gateway_rejects_duplicate_epc_before_network_call():
    async def _run():
        private_key = Ed25519PrivateKey.generate()
        private_hex = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()

        mock_resp = httpx.Response(500)
        client = DummyAsyncClient(mock_resp)
        gateway = ClientPackageGateway(client=client)
        gateway.settings = SimpleNamespace(
            CLIENT_SUPABASE_URL="https://client-project.supabase.co",
            CLIENT_SUPABASE_PUBLISHABLE_KEY="client-publishable-key",
            CLIENT_SUPPLIER_DEVICE_ID="DEVICE-01",
            CLIENT_SUPPLIER_PRIVATE_KEY_HEX=private_hex,
        )
        result = await gateway.upload_package(
            hospital_code="RS001",
            package_code="VRF-ABC123",
            items=[
                {"epc": "E280116060000204DE84B501", "nama_linen": "Sprei", "kategori": "Linen"},
                {"epc": "3000E280116060000204DE84B501", "nama_linen": "Sprei", "kategori": "Linen"},
            ],
            idempotency_key="DEVICE-01:10:VRF-ABC123",
        )
        await client.aclose()
        assert result is None
        assert client.last_call is None

    _run_async(_run())

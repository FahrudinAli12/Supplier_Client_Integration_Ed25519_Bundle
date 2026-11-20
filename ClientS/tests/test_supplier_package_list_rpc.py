import httpx
import pytest

from app.services.supabase_cloud_adapter import (
    SupabaseAuthorizationError,
    SupabaseCloudPackageAdapter,
)


@pytest.mark.asyncio
async def test_hospital_package_list_uses_tenant_scoped_rpc_without_verification_code():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = await request.aread()
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={
            "status": "ok",
            "hospital_id": 101,
            "total": 1,
            "packages": [{
                "id": 501,
                "kode_pengiriman": "VRF-LOCAL-01",
                "hospital_id": 101,
                "status": "pending",
                "manifest_hash": "a" * 64,
            }],
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = SupabaseCloudPackageAdapter(
        supabase_url="https://client-project.supabase.co",
        publishable_key="publishable-key",
        client=client,
    )
    packages = await adapter.get_hospital_packages(
        token="user-access-token",
        hospital_id=101,
        status_filter="pending",
        limit=25,
    )
    await client.aclose()

    assert packages[0]["id"] == 501
    assert "verification_code" not in packages[0]
    assert captured["url"].endswith("/rest/v1/rpc/list_hospital_packages")
    assert b'"p_status_filter":"pending"' in captured["payload"]
    assert b'"p_limit":25' in captured["payload"]
    assert captured["headers"]["authorization"] == "Bearer user-access-token"


@pytest.mark.asyncio
async def test_hospital_package_list_rejects_mismatched_hospital_id():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",
            "hospital_id": 202,
            "packages": [],
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = SupabaseCloudPackageAdapter(
        supabase_url="https://client-project.supabase.co",
        publishable_key="publishable-key",
        client=client,
    )
    with pytest.raises(SupabaseAuthorizationError):
        await adapter.get_hospital_packages("user-access-token", hospital_id=101)
    await client.aclose()

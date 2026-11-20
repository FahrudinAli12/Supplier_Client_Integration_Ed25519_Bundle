"""PostgREST and Supabase Auth client for the single Supplier/Client Supabase project.

Supports both:
1. Trusted Local Backend Admin: Uses SUPABASE_SERVICE_ROLE_KEY (backend only) to
   manage rumah_sakit master data, provision Supabase Auth users, and assign single-tenant
   hospital_memberships.
2. Authenticated user JWT (when provided).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.services.supabase_config import resolve_project_url, resolve_publishable_key

logger = logging.getLogger(__name__)
settings = get_settings()

RS_SELECT = "id,kode_rs,nama_rs,alamat,is_active,created_at,updated_at"


class SupabaseClient:
    def __init__(self):
        self._base_url = ""
        try:
            self._base_url = resolve_project_url(settings).rstrip("/")
        except Exception as exc:
            logger.error("Supabase project configuration is invalid: %s", exc)
        self._sync_timeout = httpx.Timeout(float(settings.HTTPX_TIMEOUT_SYNC_SECONDS))
        self._admin_timeout = httpx.Timeout(float(settings.HTTPX_TIMEOUT_ADMIN_SECONDS))
        self._client: Optional[httpx.AsyncClient] = None

    def _get_service_role_key(self) -> str:
        import os
        key = (getattr(get_settings(), "SUPABASE_SERVICE_ROLE_KEY", "") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
        return key

    def _admin_headers(self) -> dict[str, str]:
        """Headers for backend administrative operations using service_role or publishable key."""
        service_role_key = self._get_service_role_key()
        key = service_role_key if service_role_key else resolve_publishable_key(settings)
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _headers(self, access_token: Optional[str] = None) -> dict[str, str]:
        if access_token and access_token.strip():
            return {
                "apikey": resolve_publishable_key(settings),
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            }
        return self._admin_headers()

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._base_url:
            self._base_url = resolve_project_url(settings).rstrip("/")
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{self._base_url}/rest/v1",
                timeout=self._admin_timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def health_check(self) -> bool:
        """Check Supabase Auth availability without reading protected table data."""
        try:
            base = resolve_project_url(settings)
            headers = {"apikey": resolve_publishable_key(settings)}
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{base}/auth/v1/health", headers=headers)
            return response.status_code == 200
        except Exception as exc:
            logger.debug("Supabase health check failed: %s", exc)
            return False

    async def get_rumah_sakit(self, access_token: Optional[str] = None) -> Optional[list[dict[str, Any]]]:
        try:
            client = await self._get_client()
            response = await client.get(
                "/rumah_sakit",
                params={"select": RS_SELECT, "order": "nama_rs.asc"},
                headers=self._headers(access_token),
                timeout=self._admin_timeout,
            )
            response.raise_for_status()
            rows = response.json()
            return rows if isinstance(rows, list) else None
        except httpx.HTTPStatusError as exc:
            logger.warning("Supabase HTTP error while fetching rumah_sakit (HTTP %s): %s", exc.response.status_code, exc)
            return None
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning("Supabase unavailable while fetching rumah_sakit: %s", exc)
            return None

    async def get_rumah_sakit_full(self, access_token: Optional[str] = None) -> Optional[list[dict[str, Any]]]:
        return await self.get_rumah_sakit(access_token)

    async def create_rumah_sakit(
        self, data: dict[str, Any], access_token: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        client = await self._get_client()
        headers = dict(self._headers(access_token))
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        response = await client.post(
            "/rumah_sakit",
            params={"select": RS_SELECT},
            json=data,
            headers=headers,
            timeout=self._admin_timeout,
        )
        response.raise_for_status()
        result = response.json()
        return result[0] if isinstance(result, list) and result else None

    async def update_rumah_sakit(
        self, rs_id: str | int, data: dict[str, Any], access_token: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        try:
            numeric_id = int(rs_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("ID rumah sakit harus berupa BIGINT.") from exc
        client = await self._get_client()
        response = await client.patch(
            "/rumah_sakit",
            params={"id": f"eq.{numeric_id}", "select": RS_SELECT},
            json=data,
            headers=self._headers(access_token),
            timeout=self._admin_timeout,
        )
        response.raise_for_status()
        result = response.json()
        return result[0] if isinstance(result, list) and result else None

    async def signup_auth_user(self, email: str, password: str) -> Optional[dict[str, Any]]:
        """Sign up or admin-create a user in Supabase Auth."""
        base = resolve_project_url(settings).rstrip("/")
        service_role_key = self._get_service_role_key()
        clean_email = email.strip().lower()

        # 1. Prefer GoTrue Admin API when service role key is configured
        if service_role_key:
            try:
                admin_headers = {
                    "apikey": service_role_key,
                    "Authorization": f"Bearer {service_role_key}",
                    "Content-Type": "application/json",
                }
                admin_payload = {
                    "email": clean_email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {"role": "client_operator"},
                }
                async with httpx.AsyncClient(timeout=self._admin_timeout) as client:
                    resp = await client.post(f"{base}/auth/v1/admin/users", headers=admin_headers, json=admin_payload)
                    if resp.status_code in (200, 201):
                        return resp.json()
                    if resp.status_code == 422:
                        # User might already exist, find user ID
                        user_obj = await self.find_auth_user_by_email(clean_email)
                        if user_obj:
                            # Update password for existing user
                            user_id = user_obj.get("id")
                            if user_id:
                                await self.admin_update_client_password(user_id, password)
                            return user_obj
                    logger.warning("GoTrue Admin user create returned HTTP %s: %s", resp.status_code, resp.text)
            except Exception as exc:
                logger.error("GoTrue Admin create user error: %s", exc)

        # 2. Fallback to public GoTrue signup endpoint
        try:
            headers = {
                "apikey": resolve_publishable_key(settings),
                "Content-Type": "application/json",
            }
            payload = {"email": clean_email, "password": password}
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.post(f"{base}/auth/v1/signup", headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    return resp.json()
                logger.warning("Supabase Auth signup returned HTTP %s: %s", resp.status_code, resp.text)
                return None
        except Exception as exc:
            logger.error("Supabase Auth signup error for %s: %s", clean_email, exc)
            return None

    async def admin_update_client_password(self, user_id: str, new_password: str) -> bool:
        """Update a Client account's password using GoTrue Admin API."""
        service_role_key = self._get_service_role_key()
        if not service_role_key:
            logger.warning("SUPABASE_SERVICE_ROLE_KEY not configured; cannot reset password via admin API")
            return False
        try:
            base = resolve_project_url(settings).rstrip("/")
            admin_headers = {
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=self._admin_timeout) as client:
                resp = await client.put(
                    f"{base}/auth/v1/admin/users/{user_id}",
                    headers=admin_headers,
                    json={"password": new_password},
                )
                return resp.status_code in (200, 204)
        except Exception as exc:
            logger.error("Failed to update password for user %s: %s", user_id, exc)
            return False

    async def find_auth_user_by_email(self, email: str) -> Optional[dict[str, Any]]:
        """Find an auth.users record by email via GoTrue Admin API or PostgREST."""
        service_role_key = self._get_service_role_key()
        if not service_role_key:
            return None
        try:
            base = resolve_project_url(settings).rstrip("/")
            clean_email = email.strip().lower()
            admin_headers = {
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
            }
            async with httpx.AsyncClient(timeout=self._admin_timeout) as client:
                # GoTrue admin list users with filter
                resp = await client.get(f"{base}/auth/v1/admin/users", headers=admin_headers)
                if resp.status_code == 200:
                    data = resp.json()
                    users = data.get("users", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for u in users:
                        if (u.get("email") or "").strip().lower() == clean_email:
                            return u
        except Exception as exc:
            logger.debug("find_auth_user_by_email error: %s", exc)
        return None

    async def provision_hospital_client(
        self,
        hospital_id: int,
        client_email: str,
        role: str = "admin",
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Provision or update single-tenant membership connecting Client user to hospital."""
        clean_email = client_email.strip().lower()

        # 1. Try calling the consolidated RPC if access_token or admin headers available
        try:
            client = await self._get_client()
            headers = self._headers(access_token)
            response = await client.post(
                "/rpc/provision_hospital_client_account",
                json={
                    "p_hospital_id": hospital_id,
                    "p_user_email": clean_email,
                    "p_role": role,
                },
                headers=headers,
                timeout=self._admin_timeout,
            )
            if response.status_code == 200:
                logger.info("Successfully provisioned hospital client via RPC for hospital %s, email %s", hospital_id, clean_email)
                return response.json()
            logger.warning("provision_hospital_client RPC returned HTTP %s: %s", response.status_code, response.text)
        except Exception as exc:
            logger.warning("provision_hospital_client RPC exception: %s", exc)

        # 2. Manage hospital_memberships directly via PostgREST
        try:
            target_user_id = user_id
            if not target_user_id:
                user_data = await self.find_auth_user_by_email(clean_email)
                if user_data:
                    target_user_id = user_data.get("id")

            if target_user_id:
                client = await self._get_client()
                admin_hdr = self._admin_headers()
                # Enforce single-tenant: deactivate any other active memberships for this user
                try:
                    await client.patch(
                        "/hospital_memberships",
                        params={"user_id": f"eq.{target_user_id}", "is_active": "eq.true", "hospital_id": f"neq.{hospital_id}"},
                        json={"is_active": False},
                        headers=admin_hdr,
                    )
                except Exception as p_err:
                    logger.debug("Deactivate existing memberships notice: %s", p_err)

                # Upsert current hospital membership
                upsert_resp = await client.post(
                    "/hospital_memberships",
                    json={
                        "user_id": target_user_id,
                        "hospital_id": hospital_id,
                        "role": role,
                        "is_active": True,
                    },
                    headers={**admin_hdr, "Prefer": "resolution=merge-duplicates,return=representation"},
                )
                if upsert_resp.status_code in (200, 201):
                    logger.info("Directly provisioned hospital_memberships for user %s -> hospital %s", target_user_id, hospital_id)
                    return {"success": True, "user_id": target_user_id, "hospital_id": hospital_id}
                logger.warning("Direct hospital_memberships provisioning returned HTTP %s: %s", upsert_resp.status_code, upsert_resp.text)
        except Exception as direct_exc:
            logger.error("Direct hospital_memberships provisioning error: %s", direct_exc)

        return None

    async def provision_supplier_contract(
        self,
        hospital_id: int,
        supplier_id: str = "a0000000-0000-0000-0000-000000000001",
    ) -> Optional[dict[str, Any]]:
        """Provision an active supplier contract linking supplier and hospital."""
        try:
            import uuid
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            valid_from = (now - timedelta(days=1)).isoformat()
            valid_until = (now + timedelta(days=365 * 5)).isoformat()
            contract_data = {
                "contract_id": str(uuid.uuid4()),
                "contract_number": f"KTR-2026-LPN-{hospital_id}",
                "supplier_id": supplier_id,
                "hospital_id": hospital_id,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "is_active": True,
            }
            client = await self._get_client()
            admin_hdr = self._admin_headers()
            resp = await client.post(
                "/supplier_hospital_contracts",
                json=contract_data,
                headers={**admin_hdr, "Prefer": "return=representation"},
            )
            if resp.status_code in (200, 201):
                logger.info("Successfully provisioned supplier contract for hospital_id=%s", hospital_id)
                data = resp.json()
                return data[0] if isinstance(data, list) and data else data
            logger.warning("Supplier contract provisioning returned HTTP %s: %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.error("Failed to provision supplier contract for hospital %s: %s", hospital_id, exc)
        return None


supabase_client = SupabaseClient()

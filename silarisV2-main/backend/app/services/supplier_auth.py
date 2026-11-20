"""Supabase Auth sessions and Supplier membership authorization.

The browser receives only an opaque HttpOnly session cookie. Supabase access and
refresh tokens remain in this backend process and are forwarded to PostgREST so
RLS evaluates the real authenticated user.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.services.supabase_config import resolve_project_url, resolve_publishable_key

logger = logging.getLogger(__name__)
settings = get_settings()


class SupplierAuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


class SupplierAuthNetworkError(SupplierAuthError):
    """Transport failure. A still-valid local session may use read-only cache."""


@dataclass
class SupplierSession:
    session_id: str
    user_id: str
    email: str
    supplier_id: str
    role: str
    access_token: str
    refresh_token: str
    access_expires_at: float
    absolute_expires_at: float


class SupplierAuthService:
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client
        self._sessions: dict[str, SupplierSession] = {}

    def _base_url(self) -> str:
        try:
            return resolve_project_url(settings)
        except Exception as exc:
            raise SupplierAuthError(
                "Konfigurasi satu project Supabase belum benar. Samakan SUPABASE_URL dengan project Client.",
                503,
            ) from exc

    def _api_key(self) -> str:
        try:
            return resolve_publishable_key(settings)
        except Exception as exc:
            raise SupplierAuthError("SUPABASE_PUBLISHABLE_KEY belum dikonfigurasi dengan benar.", 503) from exc

    def _headers(self, access_token: Optional[str] = None) -> dict[str, str]:
        headers = {
            "apikey": self._api_key(),
            "Content-Type": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url()}{path}"
        try:
            if self._client:
                return await self._client.request(method, url, **kwargs)
            async with httpx.AsyncClient(timeout=12.0) as client:
                return await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning("Supabase Auth request failed: %s", exc)
            raise SupplierAuthNetworkError("Layanan autentikasi Supabase tidak dapat dijangkau.", 503) from exc

    async def _resolve_membership(self, access_token: str, user: dict[str, Any]) -> tuple[str, str, str, str]:
        user_id = str(user.get("id") or "").strip()
        email = str(user.get("email") or "").strip()
        if not user_id:
            raise SupplierAuthError("Identitas pengguna Supabase tidak valid.", 401)

        response = await self._request(
            "GET",
            "/rest/v1/supplier_memberships",
            headers=self._headers(access_token),
            params={
                "select": "supplier_id,role,is_active",
                "user_id": f"eq.{user_id}",
                "is_active": "eq.true",
            },
        )
        if response.status_code != 200:
            logger.error("supplier_memberships lookup failed: HTTP %s", response.status_code)
            if response.status_code == 401:
                raise SupplierAuthError("Token Supabase kedaluwarsa atau tidak valid.", 401)
            if response.status_code == 403:
                raise SupplierAuthError("Sesi tidak memiliki hak akses Supplier.", 403)
            raise SupplierAuthError("Gagal memeriksa membership Supplier.", 503)

        try:
            rows = response.json()
        except ValueError as exc:
            raise SupplierAuthError("Respons membership Supplier tidak valid.", 503) from exc

        if not isinstance(rows, list) or not rows:
            raise SupplierAuthError("Akun belum terdaftar sebagai pengguna Supplier aktif.", 403)
        if len(rows) != 1:
            raise SupplierAuthError(
                "Akun terhubung ke lebih dari satu Supplier. Pilih satu membership secara eksplisit.", 403
            )

        row = rows[0]
        if not isinstance(row, dict) or row.get("is_active") is not True:
            raise SupplierAuthError("Membership Supplier tidak aktif.", 403)
        supplier_id = str(row.get("supplier_id") or "").strip()
        role = str(row.get("role") or "").strip().lower()
        if not supplier_id or role not in {"owner", "admin", "operator", "viewer"}:
            raise SupplierAuthError("Konfigurasi membership Supplier tidak valid.", 403)
        return user_id, email, supplier_id, role

    async def login(self, email: str, password: str) -> SupplierSession:
        email = email.strip().lower()
        if not email or not password:
            raise SupplierAuthError("Email dan password wajib diisi.", 400)

        response = await self._request(
            "POST",
            "/auth/v1/token?grant_type=password",
            headers=self._headers(),
            json={"email": email, "password": password},
        )
        if response.status_code not in (200, 201):
            # Do not disclose whether the email exists.
            raise SupplierAuthError("Email atau password tidak valid.", 401)

        try:
            data = response.json()
        except ValueError as exc:
            raise SupplierAuthError("Respons login Supabase tidak valid.", 503) from exc

        access_token = str(data.get("access_token") or "")
        refresh_token = str(data.get("refresh_token") or "")
        user = data.get("user") or {}
        expires_in = max(60, int(data.get("expires_in") or 3600))
        if not access_token or not refresh_token or not isinstance(user, dict):
            raise SupplierAuthError("Supabase tidak mengembalikan sesi yang lengkap.", 503)

        user_id, clean_email, supplier_id, role = await self._resolve_membership(access_token, user)
        now = time.time()
        max_age = max(3600, int(settings.SUPPLIER_SESSION_MAX_AGE_SECONDS))
        session = SupplierSession(
            session_id=secrets.token_urlsafe(36),
            user_id=user_id,
            email=clean_email,
            supplier_id=supplier_id,
            role=role,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=now + expires_in,
            absolute_expires_at=now + max_age,
        )
        self._sessions[session.session_id] = session
        return session

    async def _refresh(self, session: SupplierSession) -> None:
        response = await self._request(
            "POST",
            "/auth/v1/token?grant_type=refresh_token",
            headers=self._headers(),
            json={"refresh_token": session.refresh_token},
        )
        if response.status_code not in (200, 201):
            self._sessions.pop(session.session_id, None)
            raise SupplierAuthError("Sesi Supplier kedaluwarsa. Silakan login kembali.", 401)

        try:
            data = response.json()
        except ValueError as exc:
            raise SupplierAuthError("Respons refresh Supabase tidak valid.", 503) from exc
        access_token = str(data.get("access_token") or "")
        refresh_token = str(data.get("refresh_token") or "")
        user = data.get("user") or {}
        expires_in = max(60, int(data.get("expires_in") or 3600))
        if not access_token or not refresh_token or not isinstance(user, dict):
            raise SupplierAuthError("Supabase gagal memperbarui sesi.", 503)

        user_id, email, supplier_id, role = await self._resolve_membership(access_token, user)
        session.user_id = user_id
        session.email = email
        session.supplier_id = supplier_id
        session.role = role
        session.access_token = access_token
        session.refresh_token = refresh_token
        session.access_expires_at = time.time() + expires_in

    async def get_session(self, session_id: str) -> SupplierSession:
        session = self._sessions.get(session_id)
        if not session:
            raise SupplierAuthError("Sesi Supplier tidak ditemukan. Silakan login kembali.", 401)
        now = time.time()
        if now >= session.absolute_expires_at:
            self._sessions.pop(session_id, None)
            raise SupplierAuthError("Sesi Supplier kedaluwarsa. Silakan login kembali.", 401)

        if now >= session.access_expires_at - 60:
            try:
                await self._refresh(session)
            except SupplierAuthNetworkError:
                if now >= session.access_expires_at:
                    raise
                logger.warning("Supabase offline; retaining unexpired Supplier session for local read-only fallback.")
            except SupplierAuthError:
                self._sessions.pop(session_id, None)
                raise

        # Re-check the membership on every API request while Supabase is reachable.
        # This makes role changes and membership revocation effective immediately.
        try:
            user_id, email, supplier_id, role = await self._resolve_membership(
                session.access_token,
                {"id": session.user_id, "email": session.email},
            )
            session.user_id = user_id
            session.email = email
            session.supplier_id = supplier_id
            session.role = role
        except SupplierAuthNetworkError:
            if time.time() < session.access_expires_at:
                logger.warning("Supabase offline; using previously validated Supplier membership for local cache reads.")
                return session
            raise SupplierAuthError("Sesi Supplier kedaluwarsa saat Supabase tidak tersedia.", 401)
        except SupplierAuthError as exc:
            if exc.status_code == 401:
                # Token may have expired earlier than the local clock estimate. Refresh once.
                try:
                    await self._refresh(session)
                    user_id, email, supplier_id, role = await self._resolve_membership(
                        session.access_token,
                        {"id": session.user_id, "email": session.email},
                    )
                    session.user_id = user_id
                    session.email = email
                    session.supplier_id = supplier_id
                    session.role = role
                except SupplierAuthError:
                    self._sessions.pop(session_id, None)
                    raise
            else:
                # In particular, remove sessions whose supplier_memberships row was revoked.
                if exc.status_code == 403:
                    self._sessions.pop(session_id, None)
                raise
        return session

    async def logout(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        session = self._sessions.pop(session_id, None)
        if not session:
            return
        try:
            await self._request(
                "POST",
                "/auth/v1/logout",
                headers=self._headers(session.access_token),
            )
        except SupplierAuthError:
            logger.info("Remote logout could not be confirmed; local Supplier session was cleared.")


supplier_auth_service = SupplierAuthService()

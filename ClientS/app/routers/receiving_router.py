from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Optional, Protocol, Sequence
import uuid
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models.paket_receiving_operation import (
    ACTIVE_OR_HELD_PHASES,
    PaketReceivingOperation,
)
from app.services.auth_dependencies import require_active_session
from app.services.circuit_breaker import OperationCircuitBreaker
from app.services.hospital_binding_service import verify_hospital_binding
from app.services.installation_service import (
    InstallationIdentityMismatchError,
    InstallationUIDProvider,
    PersistentFileInstallationUIDProvider,
)
from app.services.package_receiving_service import (
    ActivePackageOperationConflictError,
    AuthenticationError,
    CommitAuthorityError,
    ConfirmPermitError,
    HospitalMismatchError,
    ManifestCompletenessError,
    PackageReceivingService,
    RoomValidationError,
    StateTransitionError,
)
from app.services.rfid_service import RFIDScanSession, RFIDServiceManager
from app.services.session_store import SessionData, SessionStore
from app.services.supabase_cloud_adapter import SupabaseAuthorizationError

logger = logging.getLogger("receiving_router")

router = APIRouter(prefix="/receiving", tags=["penerimaan_paket"])


# =============================================================================
# FEATURE GATE PENERIMAAN PAKET
# =============================================================================

def is_receiving_feature_enabled() -> bool:
    """Feature gate untuk endpoint penerimaan paket. Default locked (False)."""
    return os.getenv("ENABLE_PACKAGE_RECEIVING_API", "0") == "1"


def require_receiving_feature_enabled() -> None:
    """Dependency otorisasi feature gate. Menolak dengan HTTP 503 jika nonaktif."""
    if not is_receiving_feature_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fitur penerimaan paket terkunci (Feature Gate nonaktif). Akses belum dibuka untuk operasional.",
        )


# =============================================================================
# PROTOKOL & MOCK CLOUD ADAPTER UNTUK PENERIMAAN
# =============================================================================

class CloudPackageAdapter(Protocol):
    """Protokol komunikasi cloud untuk metadata paket, claim, confirm, dan status."""

    async def get_package_info(self, token: str, paket_id: int) -> Optional[dict[str, Any]]:
        ...

    async def claim_package(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def confirm_package(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def get_package_claim_status(
        self, token: str, paket_id: int, hospital_id: Optional[int] = None
    ) -> dict[str, Any]:
        ...

    async def get_hospital_packages(
        self, token: str, hospital_id: int, status_filter: Optional[str] = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        ...

    async def get_hospital_suppliers(
        self, token: str, hospital_id: int
    ) -> list[dict[str, Any]]:
        ...

    async def get_hospital_contracts(
        self, token: str, hospital_id: int
    ) -> list[dict[str, Any]]:
        ...

    async def get_hospital_devices(
        self, token: str, hospital_id: int
    ) -> list[dict[str, Any]]:
        ...

    async def get_package_by_code(
        self, token: str, hospital_id: int, code: str
    ) -> Optional[dict[str, Any]]:
        ...



class DefaultMockCloudPackageAdapter:
    """Mock Cloud Adapter bawaan untuk pengujian terisolasi dan verifikasi lokal."""

    def __init__(self) -> None:
        self.packages: dict[int, dict[str, Any]] = {
            101: {
                "paket_id": 101,
                "hospital_id": 101,
                "verification_code": "VC-101",
                "status_paket": "kirim",
                "manifest_items": [
                    {"epc": "E28011606000020496000001", "kategori": "Linen", "nama_linen": "Sprei Standar"},
                    {"epc": "E28011606000020496000002", "kategori": "Linen", "nama_linen": "Sarung Bantal"},
                ],
            },
            102: {
                "paket_id": 102,
                "hospital_id": 999,  # Milik RS lain (untuk uji akses lintas RS)
                "verification_code": "VC-102",
                "status_paket": "kirim",
                "manifest_items": [
                    {"epc": "E28011606000020496000099", "kategori": "Linen", "nama_linen": "Linen RS Lain"},
                ],
            },
            103: {
                "paket_id": 103,
                "hospital_id": None,  # Belum terikat / karantina (hospital_id IS NULL)
                "verification_code": "VC-103",
                "status_paket": "kirim",
                "manifest_items": [
                    {"epc": "E28011606000020496000003", "kategori": "Linen", "nama_linen": "Linen Unbound"},
                ],
            },
        }
        self.claim_mode: str = "success"  # "success", "timeout", "rejected"
        self.confirm_mode: str = "success"  # "success", "timeout", "rejected"

    async def get_package_info(self, token: str, paket_id: int) -> Optional[dict[str, Any]]:
        return self.packages.get(int(paket_id))

    async def get_package_by_code(
        self, token: str, hospital_id: int, code: str
    ) -> Optional[dict[str, Any]]:
        clean_code = (code or "").strip()
        if not clean_code:
            return None

        clean_code_upper = clean_code.upper()
        for p_id, pkg in self.packages.items():
            pkg_vcode = str(pkg.get("verification_code", "")).upper()
            pkg_id_str = str(pkg.get("paket_id", ""))
            pkg_code = f"PKG-MOCK-{p_id}".upper()
            if (
                clean_code_upper == pkg_vcode
                or clean_code == pkg_id_str
                or clean_code_upper in pkg_code
            ):
                pkg_h_id = pkg.get("hospital_id")
                if pkg_h_id is None or int(pkg_h_id) != int(hospital_id):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Akses lintas rumah sakit ditolak. Paket ini bukan milik rumah sakit Anda.",
                    )
                return {
                    "status": "ok",
                    "paket_id": pkg["paket_id"],
                    "hospital_id": pkg.get("hospital_id"),
                    "supplier": pkg.get("supplier", "PT Linen Prima Nusantara"),
                    "total_linen": len(pkg.get("manifest_items", [])),
                    "manifest_items": pkg.get("manifest_items", []),
                    "status_paket": pkg.get("status_paket", "kirim"),
                    "kode_pengiriman": f"PKG-MOCK-{p_id}",
                    "catatan": "Paket Mock Penerimaan",
                }
        return None


    async def claim_package(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.claim_mode == "timeout":
            raise asyncio.TimeoutError("Claim RPC timeout")
        if self.claim_mode == "rejected":
            raise RuntimeError("Claim rejected by cloud")

        p_id = int(payload["paket_id"])
        if p_id in self.packages:
            self.packages[p_id]["status_paket"] = "claimed"
            self.packages[p_id]["claimed_by_operation_id"] = payload["operation_id"]
            self.packages[p_id]["claimed_by_installation_uid"] = payload["installation_uid"]

        return {
            "status": "SUCCESS",
            "paket_id": p_id,
            "operation_id": payload["operation_id"],
            "installation_uid": payload["installation_uid"],
            "status_paket": "claimed",
            "manifest_hash": payload.get("expected_manifest_hash") or payload.get("manifest_hash"),
        }

    async def confirm_package(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.confirm_mode == "timeout":
            raise asyncio.TimeoutError("Confirm RPC timeout")
        if self.confirm_mode == "rejected":
            raise RuntimeError("Confirm rejected by cloud")

        p_id = int(payload["paket_id"])
        pkg = self.packages.get(p_id)
        if p_id in self.packages:
            self.packages[p_id]["status_paket"] = "confirmed"
            self.packages[p_id]["confirmed_by_operation_id"] = payload["operation_id"]
            self.packages[p_id]["confirmed_by_installation_uid"] = payload["installation_uid"]

        return {
            "status": "confirmed",
            "status_paket": "confirmed",
            "paket_id": p_id,
            "hospital_id": payload.get("hospital_id") or (pkg.get("hospital_id") if pkg else None),
            "operation_id": payload["operation_id"],
            "installation_uid": payload.get("installation_uid"),
            "manifest_hash": payload.get("manifest_hash"),
        }

    async def get_package_claim_status(
        self, token: str, paket_id: int, hospital_id: Optional[int] = None
    ) -> dict[str, Any]:
        p_id = int(paket_id)
        pkg = self.packages.get(p_id)
        if not pkg:
            return {"status": "NOT_FOUND", "code": "PACKAGE_NOT_FOUND"}

        return {
            "status": "FOUND",
            "paket_id": p_id,
            "package_id": p_id,
            "package_status": pkg.get("status_paket", "pending"),
            "status_paket": pkg.get("status_paket", "pending"),
            "hospital_id": pkg.get("hospital_id"),
            "manifest_hash": "mock_manifest_hash_1234567890abcdef1234567890abcdef1234567890abcdef",
            "claimed_by_operation_id": pkg.get("claimed_by_operation_id"),
            "claimed_by_installation_uid": pkg.get("claimed_by_installation_uid"),
            "confirmed_by_operation_id": pkg.get("confirmed_by_operation_id"),
            "confirmed_by_installation_uid": pkg.get("confirmed_by_installation_uid"),
        }

    async def get_hospital_packages(
        self, token: str, hospital_id: int, status_filter: Optional[str] = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        results = []
        for p_id, pkg in self.packages.items():
            if pkg.get("hospital_id") is not None and int(pkg["hospital_id"]) == int(hospital_id):
                st = pkg.get("status_paket", "pending")
                if status_filter and st.lower() != status_filter.strip().lower():
                    continue
                results.append({
                    "id": p_id,
                    "kode_pengiriman": f"PKG-MOCK-{p_id}",
                    "status": st,
                    "hospital_id": int(hospital_id),
                    "device_id": "DEV-MAGICRF-STAGING-01",
                    "idempotency_key": f"idemp-mock-{p_id}",
                    "payload_digest": "mock_payload_digest_1234567890abcdef",
                    "manifest_hash": "mock_manifest_hash_1234567890abcdef",
                    "catatan": "Paket Mock Penerimaan",
                    "created_at": "2026-11-16T00:00:00Z",
                    "updated_at": "2026-11-16T00:00:00Z",
                })
        return results[:limit]

    async def get_hospital_suppliers(self, token: str, hospital_id: int) -> list[dict[str, Any]]:
        if int(hospital_id) in (1, 101):
            return [
                {
                    "supplier_id": "a0000000-0000-0000-0000-000000000001",
                    "supplier_code": "SUPP-001",
                    "supplier_name": "PT Linen Prima Nusantara",
                    "contact_email": "support@linenprima.co.id",
                    "is_active": True,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        return []

    async def get_hospital_contracts(self, token: str, hospital_id: int) -> list[dict[str, Any]]:
        if int(hospital_id) in (1, 101):
            return [
                {
                    "contract_id": "c0000000-0000-0000-0000-000000000001",
                    "contract_number": "KTR-2026-LPN-SMC-01",
                    "supplier_id": "a0000000-0000-0000-0000-000000000001",
                    "hospital_id": int(hospital_id),
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_until": "2031-01-01T00:00:00Z",
                    "is_active": True,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        return []

    async def get_hospital_devices(self, token: str, hospital_id: int) -> list[dict[str, Any]]:
        if int(hospital_id) in (1, 101):
            return [
                {
                    "device_id": "DEV-MAGICRF-STAGING-01",
                    "supplier_id": "a0000000-0000-0000-0000-000000000001",
                    "device_name": "MagicRF M100 Scanner Gateway",
                    "device_type": "RFID_SCANNER_GATEWAY",
                    "status": "ACTIVE",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        return []


_global_cloud_adapter: CloudPackageAdapter = DefaultMockCloudPackageAdapter()
_custom_cloud_adapter: Optional[CloudPackageAdapter] = None
_global_rfid_manager = RFIDServiceManager(demo_mode=True)
_global_uid_provider = PersistentFileInstallationUIDProvider()


def set_custom_cloud_adapter(adapter: Optional[CloudPackageAdapter]) -> None:
    """Mengatur adapter kustom untuk kebutuhan pengujian unit/integrasi."""
    global _custom_cloud_adapter
    _custom_cloud_adapter = adapter


def get_default_cloud_adapter() -> CloudPackageAdapter:
    """
    Factory pemilihan cloud adapter berdasarkan konfigurasi environment eksplisit (F7).
    - Pada production (APP_ENV=production): Wajib menggunakan SupabaseCloudPackageAdapter nyata.
      Jika kredensial tidak lengkap, menolak dengan kegagalan aman (fail-fast).
    - Pada development / test: Mengizinkan mock bawaan atau adapter yang disuntikkan.
    """
    env = os.getenv("APP_ENV", "development").strip().lower()
    is_prod = env in ("production", "prod") or os.getenv("IS_PRODUCTION", "0") == "1"

    if is_prod:
        from app.services.supabase_cloud_adapter import SupabaseCloudPackageAdapter

        adapter = SupabaseCloudPackageAdapter()
        if not adapter.is_configured():
            raise RuntimeError(
                "PRODUCTION_CONFIG_ERROR: SupabaseCloudPackageAdapter belum terkonfigurasi. "
                "SUPABASE_URL dan SUPABASE_PUBLISHABLE_KEY wajib diisi pada lingkungan production. "
                "Mock adapter dilarang keras di production."
            )
        return adapter

    if _custom_cloud_adapter is not None:
        return _custom_cloud_adapter

    if os.getenv("USE_REAL_SUPABASE_ADAPTER", "0") == "1":
        from app.services.supabase_cloud_adapter import SupabaseCloudPackageAdapter
        return SupabaseCloudPackageAdapter()

    return _global_cloud_adapter


def get_default_rfid_manager(request: Request) -> RFIDServiceManager:
    return getattr(request.app.state, "rfid_service", None) or _global_rfid_manager


def get_default_uid_provider() -> InstallationUIDProvider:
    return _global_uid_provider


def get_package_receiving_service(
    request: Request,
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    rfid_manager: RFIDServiceManager = Depends(get_default_rfid_manager),
    uid_provider: InstallationUIDProvider = Depends(get_default_uid_provider),
) -> PackageReceivingService:
    from app.routers.auth_router import get_default_session_store

    return PackageReceivingService(
        session_store=get_default_session_store(),
        rfid_service_manager=rfid_manager,
        cloud_adapter=cloud_adapter,
        circuit_breaker=OperationCircuitBreaker(),
        installation_uid_provider=uid_provider,
        db_session_factory=SessionLocal,
    )


# =============================================================================
# REQUEST & RESPONSE SCHEMAS
# =============================================================================

class LookupPackageByCodeRequest(BaseModel):
    verification_code: str = Field(..., min_length=1, max_length=120)


class StartScanSessionRequest(BaseModel):
    paket_id: int
    operation_id: Optional[str] = None


class StopScanSessionRequest(BaseModel):
    paket_id: int
    operation_id: str


class ResetScanSessionRequest(BaseModel):
    paket_id: int
    operation_id: Optional[str] = None


class ManualScanEpcRequest(BaseModel):
    operation_id: str
    epc: str = Field(..., min_length=1, max_length=128)


class ProcessPackageRequest(BaseModel):
    paket_id: int
    verification_code: str
    operation_id: Optional[str] = None
    ruangan_tujuan: Optional[str] = Field(default=None, min_length=1, max_length=100)
    nama_petugas: Optional[str] = Field(default=None, max_length=100)


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/feature-status")
def get_feature_status() -> dict[str, Any]:
    """Cek status keterbukaan Feature Gate penerimaan paket."""
    enabled = is_receiving_feature_enabled()
    return {
        "feature_gate_enabled": enabled,
        "status": "active" if enabled else "locked",
        "message": (
            "Fitur penerimaan paket aktif (Development/Test Mode)"
            if enabled
            else "Fitur penerimaan paket terkunci (Feature Gate nonaktif)."
        ),
    }


def _extract_session_hospital_id(session: Any) -> int:
    if isinstance(session, dict):
        return int(session.get("hospital_id", 0))
    return int(getattr(session, "hospital_id", 0))


def _extract_session_token(session: Any) -> str:
    if isinstance(session, dict):
        return str(session.get("access_token") or "tok_default")
    return str(getattr(session, "access_token", "tok_default"))


def _extract_session_id(session: Any) -> str:
    if isinstance(session, dict):
        return str(session.get("session_id") or "sess_default")
    return str(getattr(session, "session_id", "sess_default"))


@router.get("/packages")
async def list_incoming_packages(
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter status paket: pending, claimed, confirmed"),
    limit: int = Query(default=50, ge=1, le=200, description="Batas jumlah paket yang diambil"),
    session: Any = Depends(require_active_session),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Mengambil daftar paket pengiriman linen dari supplier untuk rumah sakit yang sedang login.
    - Tenant isolation: Menolak jika hospital_id tidak terikat atau tidak sah.
    - Menjamin verification_code tidak pernah dibocorkan ke client (Prinsip Least Privilege).
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)

    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    if not hospital_id or int(hospital_id) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sesi pengguna tidak memiliki hospital_id yang sah.",
        )

    packages = await cloud_adapter.get_hospital_packages(
        token=access_token,
        hospital_id=hospital_id,
        status_filter=status_filter,
        limit=limit,
    )

    # Sanitasi & Masking ketat: Buang verification_code jika ada
    sanitized = []
    for pkg in packages:
        p_copy = dict(pkg)
        p_copy.pop("verification_code", None)
        # Server-side guard: pastikan paket milik hospital_id ini
        if p_copy.get("hospital_id") is not None and int(p_copy.get("hospital_id")) != int(hospital_id):
            continue
        sanitized.append(p_copy)

    return {
        "status": "ok",
        "hospital_id": hospital_id,
        "total": len(sanitized),
        "packages": sanitized,
    }


@router.get("/notifications")
async def get_hospital_notifications(
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Mengambil daftar notifikasi paket linen masuk dari supplier untuk rumah sakit aktif.
    Menyediakan kode verifikasi secara aman khusus untuk sesi rumah sakit pemilik paket.
    """
    hospital_id = _extract_session_hospital_id(session)
    if not hospital_id or int(hospital_id) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sesi pengguna tidak memiliki hospital_id yang sah.",
        )

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
    )

    if not supabase_url or not service_key:
        return {
            "status": "ok",
            "hospital_id": hospital_id,
            "unread_count": 0,
            "packages": [],
        }

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{supabase_url}/rest/v1/pengiriman_linen?"
                f"hospital_id=eq.{int(hospital_id)}&"
                f"select=id,kode_pengiriman,verification_code,status,catatan,created_at,"
                f"detail_pengiriman_linen(id,epc,nama_linen,kategori)&"
                f"order=created_at.desc&limit=20",
                headers=headers,
            )
            if resp.status_code != 200:
                logger.warning("Supabase notifications query failed (HTTP %s): %s", resp.status_code, resp.text)
                return {
                    "status": "ok",
                    "hospital_id": hospital_id,
                    "unread_count": 0,
                    "packages": [],
                }

            raw_packages = resp.json() or []
    except Exception as exc:
        logger.error("Error fetching notifications from Supabase: %s", exc)
        return {
            "status": "ok",
            "hospital_id": hospital_id,
            "unread_count": 0,
            "packages": [],
        }

    formatted_packages = []
    unread_count = 0
    for p in raw_packages:
        p_status = str(p.get("status") or "").lower()
        if p_status == "pending":
            unread_count += 1
        items = p.get("detail_pengiriman_linen") or []
        formatted_packages.append({
            "id": p.get("id"),
            "kode_pengiriman": p.get("kode_pengiriman"),
            "verification_code": p.get("verification_code"),
            "status": p_status,
            "catatan": p.get("catatan"),
            "created_at": p.get("created_at"),
            "item_count": len(items),
            "items": items,
        })

    return {
        "status": "ok",
        "hospital_id": hospital_id,
        "unread_count": unread_count,
        "packages": formatted_packages,
    }


@router.get("/suppliers")
async def list_partner_suppliers(
    session: Any = Depends(require_active_session),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Mengambil daftar rekanan supplier yang memiliki kontrak kerjasama aktif dengan rumah sakit ini.
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)

    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    if not hospital_id or int(hospital_id) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sesi pengguna tidak memiliki hospital_id yang sah.",
        )

    suppliers = await cloud_adapter.get_hospital_suppliers(
        token=access_token,
        hospital_id=hospital_id,
    )

    return {
        "status": "ok",
        "hospital_id": hospital_id,
        "total": len(suppliers),
        "suppliers": suppliers,
    }


@router.get("/contracts")
async def list_hospital_contracts(
    session: Any = Depends(require_active_session),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Mengambil daftar kontrak kerjasama antara supplier dan rumah sakit bersangkutan.
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)

    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    if not hospital_id or int(hospital_id) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sesi pengguna tidak memiliki hospital_id yang sah.",
        )

    contracts = await cloud_adapter.get_hospital_contracts(
        token=access_token,
        hospital_id=hospital_id,
    )

    # Server-side tenant guard
    valid_contracts = [
        c for c in contracts if c.get("hospital_id") is None or int(c.get("hospital_id")) == int(hospital_id)
    ]

    return {
        "status": "ok",
        "hospital_id": hospital_id,
        "total": len(valid_contracts),
        "contracts": valid_contracts,
    }


@router.get("/devices")
async def list_supplier_devices(
    session: Any = Depends(require_active_session),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Mengambil daftar perangkat gateway supplier yang melayani rumah sakit ini.
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)

    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    if not hospital_id or int(hospital_id) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sesi pengguna tidak memiliki hospital_id yang sah.",
        )

    devices = await cloud_adapter.get_hospital_devices(
        token=access_token,
        hospital_id=hospital_id,
    )

    return {
        "status": "ok",
        "hospital_id": hospital_id,
        "total": len(devices),
        "devices": devices,
    }


@router.get("/package/{paket_id}")
async def get_package_manifest(
    paket_id: int,
    session: Any = Depends(require_active_session),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Ambil pratinjau metadata paket dari cloud.
    - Server-side hospital binding verification.
    - Menolak akses lintas rumah sakit.
    - MASK/OMIT verification_code: Tidak pernah membocorkan verification_code (C9 & F4 Fix).
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    pkg = await cloud_adapter.get_package_info(access_token, paket_id)
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paket {paket_id} tidak ditemukan pada cloud supplier.",
        )

    # Server-side validation: paket harus milik rumah sakit operator yang login (P0-02 Router NULL Guard)
    pkg_hospital_id = pkg.get("hospital_id")
    if pkg_hospital_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: paket belum terikat pada rumah sakit tujuan (karantina).",
        )
    if int(pkg_hospital_id) != int(hospital_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses lintas rumah sakit ditolak. Paket ini bukan milik rumah sakit Anda.",
        )

    # F4 & F9: Tidak mengembalikan verification_code melalui endpoint ini
    return {
        "status": "ok",
        "paket_id": pkg["paket_id"],
        "hospital_id": pkg.get("hospital_id"),
        "supplier": pkg.get("supplier"),
        "total_linen": len(pkg.get("manifest_items", [])),
        "manifest_items": pkg.get("manifest_items", []),
        "status_paket": pkg.get("status_paket", "kirim"),
    }


@router.post("/package/lookup")
async def lookup_package_by_code(
    req: LookupPackageByCodeRequest,
    session: Any = Depends(require_active_session),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Mengambil paket pengiriman linen dari supplier hanya dengan Kode Verifikasi (surat jalan fisik).
    - Verifikasi akun dan hak akses rumah sakit diproses secara transparan di latar belakang (background)
      menggunakan sesi aktif yang terikat pada hospital_id.
    - Operator tidak perlu menginput ID Paket secara manual.
    - Penegakan Tenant Isolation: Menolak paket yang ditujukan untuk rumah sakit lain.
    - Prinsip Least Privilege: verification_code tidak pernah dibocorkan kembali ke client response.
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)

    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    if not hospital_id or int(hospital_id) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sesi pengguna tidak memiliki hospital_id yang sah.",
        )

    code = req.verification_code.strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kode verifikasi supplier wajib diisi.",
        )

    try:
        pkg = await cloud_adapter.get_package_by_code(token=access_token, hospital_id=hospital_id, code=code)
    except HTTPException:
        raise
    except SupabaseAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except Exception as exc:
        logger.warning("Gagal melakukan lookup paket dengan kode verifikasi '%s': %s", code, exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN if "Akses" in str(exc) else status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paket dengan kode verifikasi '{code}' tidak ditemukan untuk rumah sakit Anda.",
        )

    pkg_hospital_id = pkg.get("hospital_id")
    if pkg_hospital_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: paket belum terikat pada rumah sakit tujuan (karantina).",
        )
    if int(pkg_hospital_id) != int(hospital_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses lintas rumah sakit ditolak. Paket ini bukan milik rumah sakit Anda.",
        )

    return {
        "status": "ok",
        "paket_id": pkg["paket_id"],
        "hospital_id": pkg.get("hospital_id"),
        "supplier": pkg.get("supplier"),
        "total_linen": len(pkg.get("manifest_items", [])),
        "manifest_items": pkg.get("manifest_items", []),
        "status_paket": pkg.get("status_paket", "pending"),
        "kode_pengiriman": pkg.get("kode_pengiriman"),
        "catatan": pkg.get("catatan"),
    }


@router.get("/package/by-code/{code}")
async def lookup_package_by_code_get(
    code: str,
    session: Any = Depends(require_active_session),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """Alias GET untuk lookup paket linen berdasarkan kode verifikasi."""
    return await lookup_package_by_code(
        req=LookupPackageByCodeRequest(verification_code=code),
        session=session,
        cloud_adapter=cloud_adapter,
        db=db,
        _gate=_gate,
    )



@router.post("/scan/start")
async def start_scan_session_api(
    req: StartScanSessionRequest,
    session: Any = Depends(require_active_session),
    rfid_manager: RFIDServiceManager = Depends(get_default_rfid_manager),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Mulai sesi pemindaian RFID fisik di backend untuk paket tertentu.
    - Menolak jika paket sudah dalam operasi aktif, terminal, atau tertahan.
    """
    hospital_id = _extract_session_hospital_id(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    # 1. Pemeriksaan database lokal: status paket saat ini
    existing_op = (
        db.query(PaketReceivingOperation)
        .filter(PaketReceivingOperation.paket_id == req.paket_id)
        .order_by(PaketReceivingOperation.created_at.desc())
        .first()
    )
    if existing_op:
        if existing_op.lifecycle_phase == "claim_held_reconciliation":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operasi tertahan dalam status claim_held_reconciliation. Hubungi supervisor untuk rekonsiliasi cloud.",
            )
        if existing_op.lifecycle_phase == "confirmed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Paket {req.paket_id} sudah pernah diterima dan dikonfirmasi sebelumnya (idempotent).",
            )
        if existing_op.lifecycle_phase == "claim_held_reconciliation":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operasi tertahan dalam status claim_held_reconciliation. Hubungi supervisor untuk rekonsiliasi cloud.",
            )
        if existing_op.lifecycle_phase == "auth_blocked_user":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operasi pada paket ini berstatus 'auth_blocked_user' dan dilarang diproses ulang.",
            )
        if existing_op.lifecycle_phase == "claim_rejected":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Operasi pada paket ini berstatus 'claim_rejected' ({existing_op.failure_reason}). Tidak dapat discan ulang dengan operasi ini.",
            )
        if existing_op.lifecycle_phase == "claim_uncertain":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operasi pada paket ini berstatus 'claim_uncertain' akibat gangguan jaringan. Memerlukan rekonsiliasi.",
            )
        if existing_op.lifecycle_phase in ("claiming", "claim_verified", "local_committed"):
            if req.operation_id and req.operation_id != existing_op.operation_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Paket {req.paket_id} sedang diproses oleh operasi aktif lain: {existing_op.operation_id} (fase: {existing_op.lifecycle_phase}).",
                )

    target_operation_id = req.operation_id
    if req.operation_id:
        op_by_id = (
            db.query(PaketReceivingOperation)
            .filter(PaketReceivingOperation.operation_id == req.operation_id)
            .first()
        )
        if op_by_id:
            if op_by_id.hospital_id != hospital_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Operasi {req.operation_id} tidak dapat digunakan lintas rumah sakit.",
                )
            if op_by_id.paket_id != req.paket_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Operation ID '{req.operation_id}' sudah terikat pada paket {op_by_id.paket_id}, tidak dapat digunakan untuk paket {req.paket_id}.",
                )
        else:
            if not rfid_manager.get_active_scan_session(req.operation_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Otoritas penerbitan ID hanya dimiliki oleh backend. Operation ID arbitrer dari client ditolak.",
                )
    elif existing_op and existing_op.lifecycle_phase in ("claiming", "claim_verified", "local_committed"):
        target_operation_id = existing_op.operation_id

    # 2. Mulai sesi pemindaian di memori backend
    try:
        scan_sess = rfid_manager.start_scan_session(paket_id=req.paket_id, operation_id=target_operation_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return {
        "status": "ok",
        "scan_status": "scanning",
        "paket_id": req.paket_id,
        "operation_id": scan_sess.operation_id,
        "is_active": scan_sess.is_active,
        "message": f"Sesi pemindaian untuk paket {req.paket_id} berhasil dimulai.",
    }


@router.post("/scan/manual-epc")
async def manual_scan_epc_api(
    req: ManualScanEpcRequest,
    session: Any = Depends(require_active_session),
    rfid_manager: RFIDServiceManager = Depends(get_default_rfid_manager),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """Menambahkan EPC secara manual ke sesi pemindaian yang sedang aktif (untuk pengujian non-RFID)."""
    hospital_id = _extract_session_hospital_id(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    scan_sess = rfid_manager.get_active_scan_session(req.operation_id)
    if not scan_sess:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesi pemindaian aktif dengan operation_id '{req.operation_id}' tidak ditemukan atau sudah dibekukan.",
        )
    try:
        scan_sess.add_epc(req.epc)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "status": "ok",
        "operation_id": scan_sess.operation_id,
        "scanned_count": len(scan_sess.scanned_epcs),
        "scanned_epcs": sorted(scan_sess.scanned_epcs),
        "message": f"EPC '{req.epc}' berhasil ditambahkan ke sesi pemindaian.",
    }


@router.post("/scan/stop")
async def stop_scan_session_api(
    req: StopScanSessionRequest,
    session: Any = Depends(require_active_session),
    rfid_manager: RFIDServiceManager = Depends(get_default_rfid_manager),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """Hentikan dan bekukan (freeze) sesi pemindaian RFID fisik di backend."""
    hospital_id = _extract_session_hospital_id(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    try:
        scan_sess = rfid_manager.stop_scan_session(req.operation_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesi pemindaian dengan operation_id '{req.operation_id}' tidak ditemukan.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "status": "ok",
        "scan_status": "frozen",
        "operation_id": scan_sess.operation_id,
        "paket_id": scan_sess.paket_id,
        "is_frozen": scan_sess.is_frozen,
        "scanned_count": len(scan_sess.snapshot_epcs),
        "snapshot_count": len(scan_sess.snapshot_epcs),
        "snapshot_epcs": scan_sess.snapshot_epcs,
        "message": "Sesi pemindaian berhasil dibekukan (frozen) dan siap diproses ke tahap commit.",
    }


@router.post("/scan/reset")
async def reset_scan_session_api(
    req: ResetScanSessionRequest,
    session: Any = Depends(require_active_session),
    rfid_manager: RFIDServiceManager = Depends(get_default_rfid_manager),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """Reset seluruh hasil scan fisik di backend untuk paket tertentu."""
    hospital_id = _extract_session_hospital_id(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    sess = rfid_manager.reset_scan_session(paket_id=req.paket_id, operation_id=req.operation_id)
    return {
        "status": "ok",
        "paket_id": req.paket_id,
        "operation_id": sess.operation_id if sess else req.operation_id,
        "message": f"Sesi pemindaian untuk paket {req.paket_id} berhasil di-reset.",
    }


@router.get("/scan/session/{paket_id}")
def get_scan_session_status(
    paket_id: int,
    session: Any = Depends(require_active_session),
    rfid_manager: RFIDServiceManager = Depends(get_default_rfid_manager),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """Ambil status sesi pemindaian RFID aktif untuk paket tertentu."""
    hospital_id = _extract_session_hospital_id(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    sess = rfid_manager.get_session_by_package(paket_id)
    if not sess:
        return {
            "status": "none",
            "paket_id": paket_id,
            "is_active": False,
            "is_frozen": False,
            "scanned_count": 0,
            "scanned_epcs": [],
            "epc_count": 0,
        }

    return {
        "status": "active" if sess.is_active else "stopped",
        "scan_status": "frozen" if sess.is_frozen else ("scanning" if sess.is_active else "stopped"),
        "paket_id": sess.paket_id,
        "operation_id": sess.operation_id,
        "is_active": sess.is_active,
        "is_frozen": sess.is_frozen,
        "scanned_count": len(sess.scanned_epcs),
        "scanned_epcs": sorted(sess.scanned_epcs),
        "epc_count": len(sess.scanned_epcs),
        "snapshot_count": len(sess.snapshot_epcs),
        "is_invalidated": sess.is_invalidated,
    }


@router.post("/process")
async def process_package_receiving_endpoint(
    req: ProcessPackageRequest,
    session: Any = Depends(require_active_session),
    coordinator: PackageReceivingService = Depends(get_package_receiving_service),
    cloud_adapter: CloudPackageAdapter = Depends(get_default_cloud_adapter),
    rfid_manager: RFIDServiceManager = Depends(get_default_rfid_manager),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Eksekusi alur 19 langkah penerimaan paket melalui PackageReceivingService:
    - hospital_id diverifikasi mutlak dari SessionData server-side (browser tidak dipercaya).
    - EPC dan bukti scan wajib berasal dari RFIDScanSession backend yang telah dibekukan.
    - Manifest metadata wajib berasal dari cloud adapter.
    - Penegakan integritas lifecycle lokal (tidak ada double-commit, tidak ada pembajakan).
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)
    session_id = _extract_session_id(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    # 1. Validasi ruangan_tujuan dan master data ruangan
    from app.models.ruangan import Ruangan

    total_ruangan = db.query(Ruangan).count()
    if total_ruangan == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Master data ruangan rumah sakit masih kosong. Penerimaan paket dihentikan sebelum ada efek samping transaksi atau claim cloud.",
        )
    if req.ruangan_tujuan is not None:
        if not req.ruangan_tujuan.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'ruangan_tujuan' tidak boleh kosong atau hanya berupa spasi.",
            )
        cleaned_room = req.ruangan_tujuan.strip()
        if cleaned_room.lower() == "penerimaan central":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Penggunaan default 'Penerimaan Central' dilarang. Ruangan tujuan harus dipilih dari master data resmi.",
            )
        matched_room = db.query(Ruangan).filter(Ruangan.nama_ruangan == cleaned_room).first()
        if not matched_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ruangan tujuan '{cleaned_room}' tidak terdaftar pada master data ruangan rumah sakit.",
            )
        if not matched_room.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ruangan tujuan '{cleaned_room}' berstatus nonaktif dan tidak dapat digunakan untuk penerimaan transaksi baru.",
            )
        ruangan_clean = cleaned_room
    else:
        first_room = db.query(Ruangan).filter(Ruangan.is_active == True).order_by(Ruangan.id.asc()).first()
        if not first_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Master data ruangan aktif masih kosong. Penerimaan paket dihentikan sebelum ada efek samping transaksi atau claim cloud.",
            )
        ruangan_clean = first_room.nama_ruangan

    # 2. Validasi metadata paket dari cloud
    pkg = await cloud_adapter.get_package_info(access_token, req.paket_id)
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paket {req.paket_id} tidak ditemukan pada cloud supplier.",
        )

    pkg_hospital_id = pkg.get("hospital_id")
    if pkg_hospital_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: paket belum terikat pada rumah sakit tujuan (karantina).",
        )
    if int(pkg_hospital_id) != int(hospital_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses lintas rumah sakit ditolak. Paket ini bukan milik rumah sakit Anda.",
        )

    manifest_items = pkg.get("manifest_items") or []

    # 3. Periksa status operasi yang ada di database lokal
    if req.operation_id:
        foreign_op = (
            db.query(PaketReceivingOperation)
            .filter(PaketReceivingOperation.operation_id == req.operation_id)
            .first()
        )
        if foreign_op:
            if int(foreign_op.paket_id) != int(req.paket_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Operation ID '{req.operation_id}' sudah terikat pada paket {foreign_op.paket_id} dan dilarang digunakan untuk paket {req.paket_id}.",
                )
            if foreign_op.lifecycle_phase in ("claim_rejected", "conflict", "reconciled_orphan", "auth_blocked_user"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Operasi {req.operation_id} berada dalam status terminal '{foreign_op.lifecycle_phase}' dan dilarang diproses ulang.",
                )

    existing_op = (
        db.query(PaketReceivingOperation)
        .filter(PaketReceivingOperation.paket_id == req.paket_id)
        .order_by(PaketReceivingOperation.created_at.desc())
        .first()
    )
    if existing_op:
        if existing_op.lifecycle_phase == "claim_held_reconciliation":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operasi tertahan dalam status claim_held_reconciliation. Hubungi supervisor untuk rekonsiliasi cloud.",
            )
        if existing_op.lifecycle_phase == "confirmed":
            if req.operation_id and existing_op.operation_id == req.operation_id:
                return {
                    "status": "ok",
                    "lifecycle_phase": "confirmed",
                    "sync_state": existing_op.sync_state or "synced",
                    "operation_id": existing_op.operation_id,
                    "paket_id": existing_op.paket_id,
                    "transaksi_id": existing_op.transaksi_id,
                    "idempotent": True,
                    "message": "Operasi penerimaan paket telah berhasil dikonfirmasi sebelumnya (idempotent).",
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Paket {req.paket_id} sudah pernah diterima dan dikonfirmasi sebelumnya oleh operasi {existing_op.operation_id}.",
                )
        if existing_op.lifecycle_phase in ("claiming", "claim_verified", "local_committed"):
            if not req.operation_id or existing_op.operation_id != req.operation_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Paket {req.paket_id} sedang diproses oleh operasi aktif lain: {existing_op.operation_id}.",
                )
        if existing_op.lifecycle_phase in ("claim_rejected", "conflict", "reconciled_orphan", "auth_blocked_user"):
            if req.operation_id and existing_op.operation_id == req.operation_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Operasi pada paket ini berstatus terminal '{existing_op.lifecycle_phase}' dan dilarang diproses ulang.",
                )

    # 4. Ambil bukti scan RFID fisik dari backend memory
    target_scan_sess: Optional[RFIDScanSession] = None
    with rfid_manager._sessions_lock:
        if req.operation_id and req.operation_id in rfid_manager._active_scan_sessions:
            target_scan_sess = rfid_manager._active_scan_sessions[req.operation_id]
        else:
            for s in rfid_manager._active_scan_sessions.values():
                if s.paket_id == int(req.paket_id):
                    target_scan_sess = s
                    break

    if not target_scan_sess or not target_scan_sess.is_frozen or not target_scan_sess.snapshot_epcs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bukti scan RFID fisik tidak tersedia atau belum dibekukan oleh backend.",
        )

    # 5. Panggil PackageReceivingService
    try:
        result = await coordinator.process_package_receiving(
            session_id=session_id,
            paket_id=req.paket_id,
            verification_code=req.verification_code,
            manifest_items=manifest_items,
            scan_session=target_scan_sess,
            operation_id=req.operation_id,
            ruangan_tujuan=ruangan_clean,
            nama_petugas=req.nama_petugas,
        )
        return result
    except RoomValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ActivePackageOperationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ManifestCompletenessError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Ketidakcocokan Manifest: {exc}")
    except InstallationIdentityMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Inkonsistensi Identitas: {exc}")
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except HospitalMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except StateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (CommitAuthorityError, ConfirmPermitError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        logger.exception("Kesalahan tidak terduga pada proses penerimaan paket: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal Server Error: {exc}")


@router.get("/operations/{paket_id}")
def get_package_operations_history(
    paket_id: int,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Ambil riwayat operasi penerimaan paket di database lokal.
    F9 Fix: Query membatasi hospital_id berdasarkan sesi aktif rumah sakit.
    """
    hospital_id = _extract_session_hospital_id(session)
    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    # F9: Membatasi pencarian hanya untuk hospital_id milik sesi aktif
    ops = (
        db.query(PaketReceivingOperation)
        .filter(
            PaketReceivingOperation.paket_id == int(paket_id),
            PaketReceivingOperation.hospital_id == int(hospital_id),
        )
        .order_by(PaketReceivingOperation.created_at.desc())
        .all()
    )

    return {
        "status": "ok",
        "paket_id": paket_id,
        "count": len(ops),
        "operations": [
            {
                "operation_id": op.operation_id,
                "paket_id": op.paket_id,
                "hospital_id": op.hospital_id,
                "installation_uid": op.installation_uid,
                "lifecycle_phase": op.lifecycle_phase,
                "sync_state": op.sync_state,
                "transaksi_id": op.transaksi_id,
                "scan_count": op.scan_count,
                "failure_reason": op.failure_reason,
                "created_at": op.created_at.isoformat() if op.created_at else None,
            }
            for op in ops
        ],
    }


@router.post("/operations/{operation_id}/reconcile")
async def reconcile_operation_endpoint(
    operation_id: str,
    session: Any = Depends(require_active_session),
    coordinator: PackageReceivingService = Depends(get_package_receiving_service),
    db: Session = Depends(get_db),
    _gate: None = Depends(require_receiving_feature_enabled),
) -> dict[str, Any]:
    """
    Endpoint operasional aman untuk rekonsiliasi crash recovery (R2.10 P0).
    Memvalidasi active session, hospital binding, tenant isolation, installation UID,
    keberadaan record operasi lokal, dan memanggil coordinator.reconcile_held_operation().
    """
    hospital_id = _extract_session_hospital_id(session)
    access_token = _extract_session_token(session)
    session_id = _extract_session_id(session)

    try:
        verify_hospital_binding(db, hospital_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Hospital binding tidak valid: {exc}")

    if not operation_id or not operation_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parameter operation_id wajib diisi.")

    # Validasi keberadaan paket lokal dan isolasi tenant
    op_rec = db.query(PaketReceivingOperation).filter_by(operation_id=operation_id.strip()).first()
    if not op_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operasi {operation_id} tidak ditemukan di database lokal.",
        )

    # Larang mutlak rekonsiliasi lintas rumah sakit (Tenant Isolation)
    if int(op_rec.hospital_id) != int(hospital_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operasi {operation_id} terikat pada RS {op_rec.hospital_id}, akses ditolak untuk RS {hospital_id}.",
        )

    # Validasi kesesuaian installation_uid lokal
    current_inst_uid = coordinator.installation_uid_provider.get_installation_uid()
    if op_rec.installation_uid != current_inst_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operasi {operation_id} dibuat oleh instalasi {op_rec.installation_uid}, tidak cocok dengan instalasi aktif {current_inst_uid}.",
        )

    # Eksekusi rekonsiliasi
    result = await coordinator.reconcile_held_operation(
        operation_id=operation_id.strip(),
        session_id=session_id,
        token=access_token,
        hospital_id=int(hospital_id),
    )
    return result

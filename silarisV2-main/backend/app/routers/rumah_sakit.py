"""Supplier CRUD for the shared public.rumah_sakit master table.

Secured via Trusted Local Installation:
- Supplier operates as Master Application with full CRUD authority.
- No human login or user session is required for Supplier.
- Supabase Admin API / service_role is utilized strictly on backend.
- Full validation for unique hospital codes and unique client emails.
- Automatic Client user account and single-tenant hospital membership provisioning.
- Inactivation preserves shipment history, local cache, and contracts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import RumahSakitLocal
from app.database.session import get_db
from app.schemas.rumah_sakit import RumahSakitCreate, RumahSakitUpdate, RumahSakitResponse
from app.services.supabase_client import supabase_client
from app.services.sync_service import sync_service
from app.services.trusted_local import require_trusted_supplier_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rumah-sakit", tags=["Rumah Sakit"])


def _api_row(row: dict[str, Any], local_row: Optional[RumahSakitLocal] = None) -> dict[str, Any]:
    cloud_id = int(row["id"])
    return {
        "id": cloud_id,
        "rs_id": str(cloud_id),
        "kode_rs": row["kode_rs"],
        "nama_rs": row["nama_rs"],
        "alamat": row.get("alamat") or (local_row.alamat if local_row else None),
        "kontak": row.get("kontak") or (local_row.kontak if local_row else None),
        "email": row.get("email") or (local_row.email if local_row else None),
        "client_email": (local_row.client_email if local_row else None) or row.get("client_email"),
        "is_active": bool(row.get("is_active", True)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _upsert_local(
    db: Session,
    row: dict[str, Any],
    kontak: Optional[str] = None,
    email: Optional[str] = None,
    client_email: Optional[str] = None,
    client_user_id: Optional[str] = None,
) -> RumahSakitLocal:
    cloud_id = int(row["id"])
    rs_id = str(cloud_id)
    local = db.query(RumahSakitLocal).filter(RumahSakitLocal.rs_id == rs_id).first()
    if local is None:
        local = RumahSakitLocal(rs_id=rs_id)
        db.add(local)
    local.kode_rs = row.get("kode_rs")
    local.nama_rs = row.get("nama_rs")
    local.alamat = row.get("alamat")
    if kontak is not None:
        local.kontak = kontak.strip() if kontak else None
    elif row.get("kontak"):
        local.kontak = str(row["kontak"]).strip()
    if email is not None:
        local.email = email.strip() if email else None
    elif row.get("email"):
        local.email = str(row["email"]).strip()
    if client_email is not None:
        local.client_email = client_email.strip().lower() if client_email else None
    if client_user_id is not None:
        local.client_user_id = client_user_id.strip() if client_user_id else None
    local.is_active = bool(row.get("is_active", True))
    local.timestamp = datetime.now(timezone.utc)
    db.commit()
    db.refresh(local)
    return local


def _raise_cloud_error(exc: httpx.HTTPStatusError, default_message: str) -> None:
    status_code = exc.response.status_code
    try:
        body = exc.response.json()
        raw = body.get("message") or body.get("details") or body.get("hint") or default_message
    except Exception:
        raw = default_message
    if status_code in (401, 403):
        raise HTTPException(status_code=403, detail="Akses Cloud ditolak. Periksa konfigurasi kredensial backend.")
    if status_code == 409:
        raise HTTPException(status_code=409, detail="Kode rumah sakit sudah terdaftar atau terjadi konflik data di cloud.")
    if status_code == 404:
        raise HTTPException(status_code=404, detail="Rumah sakit tidak ditemukan di cloud.")
    if status_code in (400, 422):
        raise HTTPException(status_code=422, detail=str(raw))
    raise HTTPException(status_code=502, detail=default_message)


@router.get("", response_model=list[RumahSakitResponse])
async def list_rumah_sakit(
    actor: dict[str, str] = Depends(require_trusted_supplier_access),
    db: Session = Depends(get_db),
):
    """Read all hospital master rows using Supplier Master authority."""
    if sync_service.cloud_online:
        try:
            rows = await supabase_client.get_rumah_sakit()
        except httpx.HTTPStatusError as exc:
            logger.error("Supabase rumah_sakit query failed with HTTP %s", exc.response.status_code)
            rows = None
        except Exception as exc:
            logger.warning("Supabase query exception: %s", exc)
            rows = None

        if rows is not None:
            if not rows and db.query(RumahSakitLocal).count() > 0:
                logger.warning(
                    "Supabase returned 0 rows while local cache is populated; preserving local cache."
                )
            else:
                try:
                    await sync_service.sync_down_rumah_sakit()
                except Exception as exc:
                    logger.warning("Cloud RS cache refresh failed: %s", exc)
                local_cache_map = {r.rs_id: r for r in db.query(RumahSakitLocal).all()}
                return [_api_row(row, local_cache_map.get(str(row.get("id")))) for row in rows]

    # Offline / local cache fallback
    cached = db.query(RumahSakitLocal).order_by(RumahSakitLocal.nama_rs.asc()).all()
    result = []
    for row in cached:
        try:
            cloud_id = int(row.rs_id)
        except (TypeError, ValueError):
            continue
        result.append({
            "id": cloud_id,
            "rs_id": str(cloud_id),
            "kode_rs": row.kode_rs,
            "nama_rs": row.nama_rs,
            "alamat": row.alamat,
            "kontak": row.kontak,
            "email": row.email,
            "client_email": row.client_email,
            "is_active": bool(row.is_active),
            "created_at": None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return result


@router.post("", response_model=RumahSakitResponse, status_code=201)
async def create_rumah_sakit(
    payload: RumahSakitCreate,
    actor: dict[str, str] = Depends(require_trusted_supplier_access),
    db: Session = Depends(get_db),
):
    """Create a new hospital master record and provision Client account if requested."""
    clean_kode = payload.kode_rs.strip().upper()
    clean_nama = payload.nama_rs.strip()
    if not clean_kode or not clean_nama:
        raise HTTPException(status_code=422, detail="Kode dan nama rumah sakit wajib diisi.")

    # 1. Uniqueness check for kode_rs in local database
    existing_kode = db.query(RumahSakitLocal).filter(
        RumahSakitLocal.kode_rs == clean_kode,
        RumahSakitLocal.is_active == True,
    ).first()
    if existing_kode:
        raise HTTPException(
            status_code=409,
            detail=f"Kode rumah sakit '{clean_kode}' sudah terdaftar untuk '{existing_kode.nama_rs}'.",
        )

    # 2. Uniqueness check for client_email in local database
    clean_client_email = None
    target_email_input = payload.client_email or payload.email
    if target_email_input and target_email_input.strip():
        clean_client_email = target_email_input.strip().lower()
        existing_email = db.query(RumahSakitLocal).filter(
            RumahSakitLocal.client_email == clean_client_email,
            RumahSakitLocal.is_active == True,
        ).first()
        if existing_email:
            raise HTTPException(
                status_code=409,
                detail=f"Email akun client '{clean_client_email}' sudah digunakan oleh rumah sakit '{existing_email.nama_rs}'.",
            )

    data = {
        "kode_rs": clean_kode,
        "nama_rs": clean_nama,
        "alamat": payload.alamat.strip() if payload.alamat else None,
        "is_active": True,
    }

    row = None
    client_user_id = None
    target_password = payload.client_password or payload.password

    # Attempt Cloud creation if cloud is online
    if sync_service.cloud_online:
        try:
            row = await supabase_client.create_rumah_sakit(data)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise HTTPException(status_code=409, detail="Kode rumah sakit sudah terdaftar di cloud.")
            logger.warning(
                "Supabase create rumah_sakit HTTP error %s: %s. Melanjutkan penyimpanan secara lokal.",
                exc.response.status_code,
                exc,
            )
        except Exception as exc:
            logger.warning("Supabase create rumah_sakit exception: %s. Melanjutkan penyimpanan secara lokal.", exc)

    if row:
        cloud_id = int(row["id"])
        # Pastikan kontrak supplier aktif terpasang untuk RS baru
        try:
            await supabase_client.provision_supplier_contract(cloud_id)
        except Exception as contract_exc:
            logger.warning("Auto-provisioning supplier contract notice: %s", contract_exc)

        # Auto-provision Client user account and hospital membership if credentials provided
        if clean_client_email and target_password:
            try:
                auth_res = await supabase_client.signup_auth_user(clean_client_email, target_password)
                if auth_res:
                    client_user_id = auth_res.get("id") or (auth_res.get("user") or {}).get("id")
                await supabase_client.provision_hospital_client(
                    hospital_id=cloud_id,
                    client_email=clean_client_email,
                    user_id=client_user_id,
                )
                logger.info(
                    "Provisioned Client user %s (user_id=%s) for hospital_id=%s",
                    clean_client_email, client_user_id, cloud_id,
                )
            except Exception as prov_exc:
                logger.error("Client account provisioning partial failure: %s", prov_exc)
    else:
        # Local-first fallback (if offline or cloud credentials restricted)
        max_id = 0
        for r in db.query(RumahSakitLocal).all():
            try:
                max_id = max(max_id, int(r.rs_id))
            except (ValueError, TypeError):
                pass
        next_id = max_id + 1
        data["id"] = next_id
        row = data

        # Even in local mode, attempt user signup in Supabase Auth if credentials provided
        if clean_client_email and target_password:
            try:
                auth_res = await supabase_client.signup_auth_user(clean_client_email, target_password)
                if auth_res:
                    client_user_id = auth_res.get("id") or (auth_res.get("user") or {}).get("id")
                # Attempt to link membership in Supabase Cloud
                try:
                    await supabase_client.provision_hospital_client(
                        hospital_id=next_id,
                        client_email=clean_client_email,
                        user_id=client_user_id,
                    )
                except Exception as p_err:
                    logger.debug("Local mode membership provisioning notice: %s", p_err)
            except Exception as prov_exc:
                logger.debug("Local mode Client auth signup notice: %s", prov_exc)

    local_row = _upsert_local(
        db,
        row,
        kontak=payload.kontak,
        email=payload.email,
        client_email=clean_client_email,
        client_user_id=client_user_id,
    )
    return _api_row(row, local_row)


@router.put("/{rs_id}", response_model=RumahSakitResponse)
async def update_rumah_sakit(
    rs_id: str,
    payload: RumahSakitUpdate,
    actor: dict[str, str] = Depends(require_trusted_supplier_access),
    db: Session = Depends(get_db),
):
    """Update hospital master information or manage Client account credentials."""
    update_data = payload.model_dump(exclude_unset=True)

    if "kode_rs" in update_data:
        if not update_data["kode_rs"] or not update_data["kode_rs"].strip():
            raise HTTPException(status_code=422, detail="Kode rumah sakit tidak boleh kosong.")
        update_data["kode_rs"] = update_data["kode_rs"].strip().upper()
        # Verify unique kode_rs
        conflict = db.query(RumahSakitLocal).filter(
            RumahSakitLocal.kode_rs == update_data["kode_rs"],
            RumahSakitLocal.rs_id != str(rs_id),
            RumahSakitLocal.is_active == True,
        ).first()
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"Kode rumah sakit '{update_data['kode_rs']}' sudah digunakan oleh '{conflict.nama_rs}'.",
            )

    if "nama_rs" in update_data:
        if not update_data["nama_rs"] or not update_data["nama_rs"].strip():
            raise HTTPException(status_code=422, detail="Nama rumah sakit tidak boleh kosong.")
        update_data["nama_rs"] = update_data["nama_rs"].strip()

    if "alamat" in update_data and update_data["alamat"] is not None:
        update_data["alamat"] = update_data["alamat"].strip() or None

    # Handle client_email and client_password
    clean_client_email = None
    target_email_input = update_data.pop("client_email", None) or update_data.get("email")
    if target_email_input and target_email_input.strip():
        clean_client_email = target_email_input.strip().lower()
        conflict_email = db.query(RumahSakitLocal).filter(
            RumahSakitLocal.client_email == clean_client_email,
            RumahSakitLocal.rs_id != str(rs_id),
            RumahSakitLocal.is_active == True,
        ).first()
        if conflict_email:
            raise HTTPException(
                status_code=409,
                detail=f"Email client '{clean_client_email}' sudah digunakan oleh '{conflict_email.nama_rs}'.",
            )

    password_input = update_data.pop("password", None)
    client_password = update_data.pop("client_password", None) or password_input

    # Cloud fields for public.rumah_sakit
    cloud_payload = {}
    for f in ("kode_rs", "nama_rs", "alamat", "is_active"):
        if f in update_data and update_data[f] is not None:
            cloud_payload[f] = update_data[f]

    if cloud_payload:
        cloud_payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    # If Supabase is online and cloud fields changed, sync to cloud
    row = None
    if sync_service.cloud_online and cloud_payload:
        try:
            row = await supabase_client.update_rumah_sakit(rs_id, cloud_payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise HTTPException(status_code=409, detail="Konflik data saat memperbarui rumah sakit di cloud.")
            logger.warning("Supabase update rumah_sakit HTTP error %s: %s", exc.response.status_code, exc)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning("Supabase update rumah_sakit request failed: %s", exc)

    # If client password reset requested
    target_local = db.query(RumahSakitLocal).filter(RumahSakitLocal.rs_id == str(rs_id)).first()
    client_user_id = target_local.client_user_id if target_local else None

    if client_password:
        target_email = clean_client_email or (target_local.client_email if target_local else None)
        if target_email:
            try:
                auth_res = await supabase_client.signup_auth_user(target_email, client_password)
                if auth_res:
                    client_user_id = auth_res.get("id") or (auth_res.get("user") or {}).get("id")
                # Ensure membership is provisioned
                try:
                    await supabase_client.provision_hospital_client(
                        hospital_id=int(rs_id),
                        client_email=target_email,
                        user_id=client_user_id,
                    )
                except Exception as p_err:
                    logger.warning("Membership sync warning: %s", p_err)
            except Exception as reset_err:
                logger.error("Password reset warning: %s", reset_err)

    # Upsert local cache
    merged_row = {
        "id": int(rs_id),
        "kode_rs": update_data.get("kode_rs") or (target_local.kode_rs if target_local else ""),
        "nama_rs": update_data.get("nama_rs") or (target_local.nama_rs if target_local else ""),
        "alamat": update_data.get("alamat") if "alamat" in update_data else (target_local.alamat if target_local else None),
        "is_active": update_data.get("is_active") if "is_active" in update_data else (target_local.is_active if target_local else True),
    }
    local_row = _upsert_local(
        db,
        merged_row,
        kontak=payload.kontak if "kontak" in update_data else (target_local.kontak if target_local else None),
        email=payload.email if "email" in update_data else (target_local.email if target_local else None),
        client_email=clean_client_email or (target_local.client_email if target_local else None),
        client_user_id=client_user_id,
    )
    return _api_row(row or merged_row, local_row)


@router.delete("/{rs_id}")
async def deactivate_rumah_sakit(
    rs_id: str,
    actor: dict[str, str] = Depends(require_trusted_supplier_access),
    db: Session = Depends(get_db),
):
    """Soft disable hospital master row. Existing shipments and contracts remain preserved."""
    local = db.query(RumahSakitLocal).filter(RumahSakitLocal.rs_id == str(rs_id)).first()
    if not local:
        raise HTTPException(status_code=404, detail="Rumah sakit tidak ditemukan.")

    if sync_service.cloud_online:
        try:
            await supabase_client.update_rumah_sakit(rs_id, {"is_active": False})
        except Exception as exc:
            logger.warning("Cloud deactivation exception: %s", exc)

    local.is_active = False
    local.timestamp = datetime.now(timezone.utc)
    db.commit()

    return {
        "detail": "Rumah sakit berhasil dinonaktifkan. Riwayat pengiriman tetap dipertahankan.",
        "rs_id": str(rs_id),
        "is_active": False,
    }

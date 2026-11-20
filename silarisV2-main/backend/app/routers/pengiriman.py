"""
Pengiriman router — shipment management at /api/pengiriman

Handles: create shipment, antrean bermasalah, retry, cancel, histori.
"""

import json
import math
import random
import string
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, cast, String

from app.database.session import get_db
from app.database.models import Linen, PengirimanTemp, RumahSakitLocal, KategoriLinen, NamaLinen
from app.schemas.pengiriman import PengirimanCreate, PengirimanCreateResponse
from app.services.sync_service import sync_service

router = APIRouter(prefix="/api/pengiriman", tags=["Pengiriman"])


def _generate_kode_verifikasi() -> str:
    """Generate a unique verification code in format VRF-XXXXXX."""
    chars = string.ascii_uppercase + string.digits
    random_part = "".join(random.choices(chars, k=6))
    return f"VRF-{random_part}"


import asyncio

_active_pengiriman_locks = set()
_lock_mutex = asyncio.Lock()


@router.post("", status_code=201, response_model=PengirimanCreateResponse)
async def create_pengiriman(
    payload: PengirimanCreate, db: Session = Depends(get_db)
):
    """
    Create a new shipment.
    1. Check rate-limit lock to prevent duplicate submit
    2. Validate all EPCs have status "tersedia"
    3. Generate kode_verifikasi
    4. Save to PengirimanTemp with status_upload "pending"
    5. Update all linen status to "dikirim"
    6. Try immediate sync to Supabase
    """
    if not payload.daftar_epc:
        raise HTTPException(status_code=400, detail="Daftar EPC tidak boleh kosong.")

    lock_key = f"create_{payload.rs_id}_{tuple(sorted(payload.daftar_epc))}"
    async with _lock_mutex:
        if lock_key in _active_pengiriman_locks:
            raise HTTPException(
                status_code=429,
                detail="Permintaan pengiriman ini sedang diproses. Harap tunggu.",
            )
        _active_pengiriman_locks.add(lock_key)

    try:
        # Validate all EPCs exist and are "tersedia"
        linen_items = (
            db.query(Linen, KategoriLinen.nama, NamaLinen.nama_linen)
            .join(KategoriLinen, Linen.kategori_id == KategoriLinen.kategori_id)
            .join(NamaLinen, Linen.nama_id == NamaLinen.nama_id)
            .filter(Linen.epc.in_(payload.daftar_epc))
            .all()
        )

        found_epcs = {item[0].epc for item in linen_items}
        missing = set(payload.daftar_epc) - found_epcs
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"EPC tidak ditemukan: {', '.join(missing)}",
            )

        not_available = [
            item[0].epc for item in linen_items if item[0].status != "tersedia"
        ]
        if not_available:
            raise HTTPException(
                status_code=400,
                detail=f"EPC berikut tidak berstatus 'tersedia': {', '.join(not_available)}",
            )

        # Build daftar_epc JSON array for storage
        daftar_epc_json = [
            {
                "epc": item[0].epc,
                "nama_linen": item[2],  # NamaLinen.nama_linen
                "kategori": item[1],  # KategoriLinen.nama
            }
            for item in linen_items
        ]

        # Generate unique kode_verifikasi
        kode = _generate_kode_verifikasi()
        while db.query(PengirimanTemp).filter(
            PengirimanTemp.kode_verifikasi == kode
        ).first():
            kode = _generate_kode_verifikasi()

        # Create PengirimanTemp record
        pengiriman = PengirimanTemp(
            kode_verifikasi=kode,
            rs_id=payload.rs_id,
            daftar_epc=json.dumps(daftar_epc_json),
            status_upload="pending",
            percobaan_ke=0,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(pengiriman)

        # Update all linen status to "dikirim"
        for item in linen_items:
            item[0].status = "dikirim"

        db.commit()
        temp_id = pengiriman.temp_id
        kode_verifikasi = pengiriman.kode_verifikasi

        # Attempt immediate delivery to Client Supabase. Keep the local record as history.
        await sync_service.try_upload_now(db, pengiriman)
        db.refresh(pengiriman)

        return {
            "temp_id": temp_id,
            "kode_verifikasi": pengiriman.kode_verifikasi_cloud,
            "kode_verifikasi_lokal": kode_verifikasi,
            "cloud_package_code": pengiriman.cloud_package_code,
            "cloud_package_id": pengiriman.cloud_package_id,
            "status_upload": pengiriman.status_upload,
            "last_error": pengiriman.last_error,
        }
    finally:
        async with _lock_mutex:
            _active_pengiriman_locks.discard(lock_key)


@router.get("/antrean-bermasalah")
def get_antrean_bermasalah(db: Session = Depends(get_db)):
    """List PengirimanTemp requiring action (status_upload != 'sukses')."""
    records = (
        db.query(PengirimanTemp)
        .filter(PengirimanTemp.status_upload.in_(["gagal", "gagal_permanen", "pending"]))
        .order_by(PengirimanTemp.timestamp.desc())
        .all()
    )

    result = []
    for rec in records:
        rs = db.query(RumahSakitLocal).filter(
            RumahSakitLocal.rs_id == rec.rs_id
        ).first()
        epc_list = json.loads(rec.daftar_epc) if rec.daftar_epc else []
        iso_time = rec.timestamp.isoformat() if rec.timestamp else None
        err_msg = rec.last_error or ("Menunggu sinkronisasi" if rec.status_upload == "pending" else "Gagal sinkronisasi Supabase")

        result.append({
            "temp_id": rec.temp_id,
            "kode_verifikasi": rec.kode_verifikasi_cloud or rec.kode_verifikasi,
            "kode_verifikasi_lokal": rec.kode_verifikasi,
            "cloud_package_code": rec.cloud_package_code,
            "cloud_package_id": rec.cloud_package_id,
            "rs_id": rec.rs_id,
            "nama_rs": rs.nama_rs if rs else None,
            "kode_rs": rs.kode_rs if rs else None,
            "daftar_epc": epc_list,
            "items": epc_list,
            "total_linen": len(epc_list),
            "status_upload": rec.status_upload,
            "last_error": err_msg,
            "error_msg": err_msg,
            "created_at": iso_time,
            "waktu": iso_time,
            "timestamp": iso_time,
        })

    return result


@router.post("/{temp_id}/coba-lagi")
async def retry_pengiriman(temp_id: int, db: Session = Depends(get_db)):
    """Retry uploading a failed pengiriman to Supabase."""
    lock_key = f"retry_{temp_id}"
    async with _lock_mutex:
        if lock_key in _active_pengiriman_locks:
            raise HTTPException(
                status_code=429,
                detail="Proses coba-lagi pengiriman ini sedang berjalan. Harap tunggu.",
            )
        _active_pengiriman_locks.add(lock_key)

    try:
        record = db.query(PengirimanTemp).filter(
            PengirimanTemp.temp_id == temp_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Pengiriman tidak ditemukan.")

        if record.status_upload == "sukses" and record.cloud_package_id:
            return {
                "temp_id": record.temp_id,
                "kode_verifikasi": record.kode_verifikasi_cloud,
                "kode_verifikasi_lokal": record.kode_verifikasi,
                "cloud_package_code": record.cloud_package_code,
                "cloud_package_id": record.cloud_package_id,
                "status_upload": record.status_upload,
            }

        record.status_upload = "pending"
        record.percobaan_ke = 0
        db.commit()
        await sync_service.try_upload_now(db, record)
        db.refresh(record)

        return {
            "temp_id": record.temp_id,
            "kode_verifikasi": record.kode_verifikasi_cloud,
            "kode_verifikasi_lokal": record.kode_verifikasi,
            "cloud_package_code": record.cloud_package_code,
            "cloud_package_id": record.cloud_package_id,
            "status_upload": record.status_upload,
        }
    finally:
        async with _lock_mutex:
            _active_pengiriman_locks.discard(lock_key)


@router.post("/{temp_id}/batalkan")
def cancel_pengiriman(temp_id: int, db: Session = Depends(get_db)):
    """
    Cancel a pengiriman.
    Reverts all linen in daftar_epc to status "tersedia" and deletes the record.
    """
    record = db.query(PengirimanTemp).filter(
        PengirimanTemp.temp_id == temp_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Pengiriman tidak ditemukan.")

    # Once Client Supabase accepted a package, local cancellation would create a cloud orphan.
    if record.status_upload == "sukses" or record.cloud_package_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Paket sudah tersimpan di Client Supabase dan tidak dapat dibatalkan dari Supplier.",
        )

    # Parse EPC list and revert linen status
    epc_list = json.loads(record.daftar_epc)
    epc_strings = [item["epc"] for item in epc_list]

    linen_items = db.query(Linen).filter(Linen.epc.in_(epc_strings)).all()
    for linen in linen_items:
        linen.status = "tersedia"

    # Delete the PengirimanTemp record
    db.delete(record)
    db.commit()

    return {"detail": "Pengiriman berhasil dibatalkan. Status linen dikembalikan ke 'tersedia'."}


@router.get("/histori")
async def get_histori_pengiriman(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    rs_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Paginated local audit history of packages sent to Client Supabase."""
    query = db.query(PengirimanTemp)
    if start_date and start_date.strip():
        query = query.filter(func.date(PengirimanTemp.timestamp) >= start_date.strip()[:10])
    if end_date and end_date.strip():
        query = query.filter(func.date(PengirimanTemp.timestamp) <= end_date.strip()[:10])
    if rs_id and rs_id.strip():
        query = query.filter(PengirimanTemp.rs_id == rs_id.strip())
    if search and search.strip():
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                PengirimanTemp.kode_verifikasi.ilike(s),
                PengirimanTemp.kode_verifikasi_cloud.ilike(s),
                cast(PengirimanTemp.temp_id, String).ilike(s),
            )
        )

    total_data = query.count()
    total_page = max(1, math.ceil(total_data / limit))
    records = (
        query.order_by(PengirimanTemp.timestamp.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    data = []
    for rec in records:
        rs = db.query(RumahSakitLocal).filter(RumahSakitLocal.rs_id == rec.rs_id).first()
        epc_list = json.loads(rec.daftar_epc) if rec.daftar_epc else []
        iso_time = rec.timestamp.isoformat() if rec.timestamp else None
        data.append({
            "pengiriman_id": rec.temp_id,
            "id": rec.temp_id,
            "temp_id": rec.temp_id,
            "cloud_package_id": rec.cloud_package_id,
            "kode_verifikasi": rec.kode_verifikasi_cloud or rec.kode_verifikasi,
            "kode_verifikasi_lokal": rec.kode_verifikasi,
            "cloud_package_code": rec.cloud_package_code,
            "rs_id": rec.rs_id,
            "nama_rs": rs.nama_rs if rs else None,
            "kode_rs": rs.kode_rs if rs else None,
            "jumlah_linen": len(epc_list),
            "total_linen": len(epc_list),
            "items": epc_list,
            "status_upload": rec.status_upload,
            "created_at": iso_time,
            "tanggal": iso_time,
            "timestamp": iso_time,
            "cloud_manifest_hash": rec.cloud_manifest_hash,
        })

    return {
        "data": data,
        "total_data": total_data,
        "total_page": total_page,
        "current_page": page,
    }


@router.get("/histori/{pengiriman_id}")
async def get_histori_detail(pengiriman_id: str, db: Session = Depends(get_db)):
    """Return local audit details for a package delivered to Client Supabase."""
    try:
        temp_id = int(pengiriman_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Pengiriman tidak ditemukan.")

    record = db.query(PengirimanTemp).filter(PengirimanTemp.temp_id == temp_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Pengiriman tidak ditemukan.")

    rs = db.query(RumahSakitLocal).filter(RumahSakitLocal.rs_id == record.rs_id).first()
    epc_list = json.loads(record.daftar_epc) if record.daftar_epc else []
    iso_time = record.timestamp.isoformat() if record.timestamp else None

    return {
        "pengiriman_id": record.temp_id,
        "temp_id": record.temp_id,
        "cloud_package_id": record.cloud_package_id,
        "kode_verifikasi": record.kode_verifikasi_cloud or record.kode_verifikasi,
        "kode_verifikasi_lokal": record.kode_verifikasi,
        "cloud_package_code": record.cloud_package_code,
        "nama_rs": rs.nama_rs if rs else None,
        "kode_rs": rs.kode_rs if rs else None,
        "created_at": iso_time,
        "tanggal": iso_time,
        "timestamp": iso_time,
        "status_upload": record.status_upload,
        "items": epc_list,
        "daftar_epc": epc_list,
        "total_linen": len(epc_list),
    }


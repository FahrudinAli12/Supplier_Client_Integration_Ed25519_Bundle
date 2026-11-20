"""
Linen router — CRUD + search + pagination at /api/linen
"""

import math
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import Optional
from datetime import datetime, timezone

from app.database.session import get_db
from app.database.models import Linen, KategoriLinen, NamaLinen, PengirimanTemp, RumahSakitLocal
from app.schemas.linen import LinenCreate, LinenUpdate, LinenResponse, LinenDetailResponse

router = APIRouter(prefix="/api/linen", tags=["Linen"])


@router.get("")
def list_linen(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    kategori_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Paginated list of linen with search, status, and category filter.
    Search matches epc or nama_linen. Status filter is case-insensitive.
    """
    query = (
        db.query(Linen, KategoriLinen.nama, NamaLinen.nama_linen)
        .join(KategoriLinen, Linen.kategori_id == KategoriLinen.kategori_id)
        .join(NamaLinen, Linen.nama_id == NamaLinen.nama_id)
    )

    # Apply filters
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Linen.epc.ilike(search_term),
                NamaLinen.nama_linen.ilike(search_term),
            )
        )
    if status and status.strip():
        query = query.filter(func.lower(Linen.status) == status.strip().lower())
    if kategori_id is not None:
        query = query.filter(Linen.kategori_id == kategori_id)

    # Count total
    total_data = query.count()
    total_page = max(1, math.ceil(total_data / limit))

    # Paginate
    offset = (page - 1) * limit
    rows = query.order_by(Linen.timestamp.desc()).offset(offset).limit(limit).all()

    data = []
    for linen, kategori_nama, nama_linen_str in rows:
        data.append({
            "linen_id": linen.linen_id,
            "epc": linen.epc,
            "kategori_id": linen.kategori_id,
            "kategori": kategori_nama,
            "nama_id": linen.nama_id,
            "nama_linen": nama_linen_str,
            "status": linen.status,
            "timestamp": linen.timestamp.isoformat() if linen.timestamp else None,
            "created_at": linen.timestamp.isoformat() if linen.timestamp else None,
        })

    return {
        "data": data,
        "total_data": total_data,
        "total_page": total_page,
        "current_page": page,
    }


@router.get("/{epc}", response_model=LinenDetailResponse)
def get_linen_by_epc(epc: str, db: Session = Depends(get_db)):
    """
    Detail of a single linen item by EPC.
    Returns complete info: category, name, registration date, current hospital,
    and shipment history.
    """
    clean_epc = (epc or "").strip().upper()
    if len(clean_epc) == 28 and clean_epc.startswith("3000"):
        clean_epc = clean_epc[4:]

    result = (
        db.query(Linen, KategoriLinen.nama, NamaLinen.nama_linen)
        .join(KategoriLinen, Linen.kategori_id == KategoriLinen.kategori_id)
        .join(NamaLinen, Linen.nama_id == NamaLinen.nama_id)
        .filter(Linen.epc == clean_epc)
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Item belum terdaftar.")

    linen, kategori_nama, nama_linen_str = result

    # Find all shipment records containing this EPC in PengirimanTemp
    pengiriman_records = (
        db.query(PengirimanTemp)
        .filter(PengirimanTemp.daftar_epc.contains(clean_epc))
        .order_by(PengirimanTemp.timestamp.desc())
        .all()
    )

    history = []
    latest_rs_name = None
    for p in pengiriman_records:
        rs = db.query(RumahSakitLocal).filter(
            RumahSakitLocal.rs_id == p.rs_id
        ).first()
        rs_name = rs.nama_rs if rs else f"RS #{p.rs_id}"
        item = {
            "temp_id": p.temp_id,
            "kode_verifikasi": p.kode_verifikasi_cloud,
            "kode_verifikasi_lokal": p.kode_verifikasi,
            "nama_rs": rs_name,
            "timestamp": p.timestamp.isoformat() if p.timestamp else None,
            "status_upload": p.status_upload,
        }
        history.append(item)
        if latest_rs_name is None:
            latest_rs_name = rs_name

    transaksi_terakhir = history[0] if history else None
    current_rs = latest_rs_name if linen.status == "dikirim" else None

    return {
        "epc": linen.epc,
        "nama_linen": nama_linen_str,
        "kategori": kategori_nama,
        "status": linen.status,
        "nama_rs": current_rs,
        "tanggal_registrasi": linen.timestamp.isoformat() if linen.timestamp else None,
        "riwayat_pengiriman": history,
        "transaksi_terakhir": transaksi_terakhir,
    }


@router.post("", status_code=201)
def create_linen(payload: LinenCreate, db: Session = Depends(get_db)):
    """Register a new linen item (RFID or manual). 409 if EPC already exists."""
    kategori = db.query(KategoriLinen).filter(KategoriLinen.kategori_id == payload.kategori_id).first()
    if not kategori:
        raise HTTPException(status_code=404, detail="Kategori linen tidak ditemukan.")

    nama_obj = db.query(NamaLinen).filter(
        NamaLinen.nama_id == payload.nama_id,
        NamaLinen.kategori_id == payload.kategori_id,
    ).first()
    if not nama_obj:
        raise HTTPException(
            status_code=404,
            detail="Nama linen tidak ditemukan atau tidak sesuai dengan kategori yang dipilih.",
        )

    existing = db.query(Linen).filter(Linen.epc == payload.epc).first()
    if existing:
        raise HTTPException(status_code=409, detail="Tag sudah terdaftar.")

    linen = Linen(
        epc=payload.epc,
        kategori_id=payload.kategori_id,
        nama_id=payload.nama_id,
        status="tersedia",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(linen)
    db.commit()
    db.refresh(linen)

    return {
        "linen_id": linen.linen_id,
        "epc": linen.epc,
        "kategori_id": linen.kategori_id,
        "kategori": kategori.nama,
        "nama_id": linen.nama_id,
        "nama_linen": nama_obj.nama_linen,
        "status": linen.status,
        "timestamp": linen.timestamp.isoformat() if linen.timestamp else None,
        "created_at": linen.timestamp.isoformat() if linen.timestamp else None,
    }


@router.put("/{epc}")
def update_linen(epc: str, payload: LinenUpdate, db: Session = Depends(get_db)):
    """Update a linen item's kategori_id, nama_id, or status with transaction validation."""
    clean_epc = (epc or "").strip().upper()
    if len(clean_epc) == 28 and clean_epc.startswith("3000"):
        clean_epc = clean_epc[4:]

    linen = db.query(Linen).filter(Linen.epc == clean_epc).first()
    if not linen:
        raise HTTPException(status_code=404, detail="Item tidak ditemukan.")

    target_kategori_id = payload.kategori_id if payload.kategori_id is not None else linen.kategori_id
    if payload.kategori_id is not None:
        kategori = db.query(KategoriLinen).filter(KategoriLinen.kategori_id == payload.kategori_id).first()
        if not kategori:
            raise HTTPException(status_code=404, detail="Kategori linen tidak ditemukan.")
        linen.kategori_id = payload.kategori_id

    if payload.nama_id is not None:
        nama_obj = db.query(NamaLinen).filter(
            NamaLinen.nama_id == payload.nama_id,
            NamaLinen.kategori_id == target_kategori_id,
        ).first()
        if not nama_obj:
            raise HTTPException(
                status_code=404,
                detail="Nama linen tidak ditemukan atau tidak sesuai kategori.",
            )
        linen.nama_id = payload.nama_id

    if payload.status is not None:
        norm_status = payload.status.strip().lower()
        if norm_status not in ("tersedia", "dikirim"):
            raise HTTPException(
                status_code=400,
                detail="Status hanya boleh 'tersedia' atau 'dikirim'.",
            )
        # Protect against bypassing shipment transactions
        if linen.status == "dikirim" and norm_status == "tersedia":
            active_tx = (
                db.query(PengirimanTemp)
                .filter(
                    PengirimanTemp.daftar_epc.contains(clean_epc),
                    PengirimanTemp.status_upload.in_(["pending", "sukses"]),
                )
                .first()
            )
            if active_tx:
                raise HTTPException(
                    status_code=409,
                    detail="Status tidak dapat diubah ke 'tersedia' karena linen masih terikat dalam transaksi pengiriman aktif. Batalkan pengiriman jika diperlukan.",
                )
        linen.status = norm_status

    db.commit()
    db.refresh(linen)

    result = (
        db.query(Linen, KategoriLinen.nama, NamaLinen.nama_linen)
        .join(KategoriLinen, Linen.kategori_id == KategoriLinen.kategori_id)
        .join(NamaLinen, Linen.nama_id == NamaLinen.nama_id)
        .filter(Linen.linen_id == linen.linen_id)
        .first()
    )
    linen_obj, kategori_nama, nama_linen_str = result
    return {
        "linen_id": linen_obj.linen_id,
        "epc": linen_obj.epc,
        "kategori_id": linen_obj.kategori_id,
        "kategori": kategori_nama,
        "nama_id": linen_obj.nama_id,
        "nama_linen": nama_linen_str,
        "status": linen_obj.status,
        "timestamp": linen_obj.timestamp.isoformat() if linen_obj.timestamp else None,
        "created_at": linen_obj.timestamp.isoformat() if linen_obj.timestamp else None,
    }


@router.delete("/{epc}")
def delete_linen(epc: str, db: Session = Depends(get_db)):
    """Delete a linen item. 409 if status is 'dikirim'."""
    linen = db.query(Linen).filter(Linen.epc == epc).first()
    if not linen:
        raise HTTPException(status_code=404, detail="Item tidak ditemukan.")

    if linen.status == "dikirim":
        raise HTTPException(
            status_code=409,
            detail="Item ini masih tercatat dalam riwayat pengiriman aktif.",
        )

    db.delete(linen)
    db.commit()
    return {"detail": "Item berhasil dihapus."}

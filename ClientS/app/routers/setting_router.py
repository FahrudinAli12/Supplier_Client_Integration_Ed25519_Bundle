from __future__ import annotations

import time
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models.detail_transaksi_linen import DetailTransaksiLinen
from app.models.linen import Linen
from app.models.riwayat_linen import RiwayatLinen
from app.models.transaksi_linen import TransaksiLinen
from app.services.auth_dependencies import extract_session_hospital_id, require_active_session
from app.services.cloud_sync_service import CloudSyncService, clean_epc
from app.services.session_store import SessionData

router = APIRouter(prefix="/setting", tags=["setting"])
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# GET DATA DARI CLOUD (DITUTUP SEMENTARA HINGGA RPC TAHAP 4)
# ──────────────────────────────────────────────────────────

@router.get("/get-data")
def get_data_cloud(
    kode: str,
    session: SessionData = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> dict:
    """Ambil data paket linen dari cloud (ditutup sementara demi isolasi RS multi-tenant)."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Penerimaan paket belum tersedia. Konfigurasi akses rumah sakit sedang disiapkan.",
    )


# ──────────────────────────────────────────────────────────
# SIMPAN DATA KE LOKAL (DITUTUP SEMENTARA HINGGA RPC TAHAP 4)
# ──────────────────────────────────────────────────────────

class SimpanDataPayload(BaseModel):
    verification_code: str
    petugas: str
    paket_id: str | int
    supplier: Optional[str] = None
    catatan: Optional[str] = None
    linen_terdaftar: list[dict]  # [{id, epc, kategori, nama_linen}]


@router.post("/simpan-data")
def simpan_data(
    payload: SimpanDataPayload,
    session: SessionData = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> dict:
    """Simpan data linen dari paket cloud ke database lokal (ditutup sementara demi isolasi RS multi-tenant)."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Penerimaan paket belum tersedia. Konfigurasi akses rumah sakit sedang disiapkan.",
    )


# ──────────────────────────────────────────────────────────
# LOG PENGIRIMAN DATA
# ──────────────────────────────────────────────────────────

@router.get("/log")
def get_log_penerimaan(
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Ambil semua log transaksi penerimaan linen dari cloud untuk rumah sakit aktif."""
    active_hospital_id = extract_session_hospital_id(session)
    query = db.query(TransaksiLinen).filter(TransaksiLinen.jenis_transaksi == "penerimaan")
    if active_hospital_id:
        query = query.filter(
            (TransaksiLinen.hospital_id == active_hospital_id) | (TransaksiLinen.hospital_id.is_(None))
        )
    rows = query.order_by(TransaksiLinen.id.desc()).all()
    result = []
    for i, row in enumerate(rows, 1):
        result.append({
            "no": i,
            "id": row.id,
            "tanggal": row.created_at.strftime("%d/%m/%Y %H:%M") if row.created_at else "-",
            "petugas": row.petugas or "-",
            "jumlah_linen": row.total_linen,
            "keterangan": row.catatan or "-",
            "kode_transaksi": row.kode_transaksi,
        })
    return result


@router.get("/log/{transaksi_id}/detail")
def get_log_detail(
    transaksi_id: int,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Ambil detail linen dari transaksi penerimaan tertentu."""
    active_hospital_id = extract_session_hospital_id(session)
    if active_hospital_id:
        trx = db.query(TransaksiLinen).filter(
            TransaksiLinen.id == transaksi_id,
            (TransaksiLinen.hospital_id == active_hospital_id) | (TransaksiLinen.hospital_id.is_(None)),
        ).first()
        if not trx:
            raise HTTPException(status_code=404, detail="Log penerimaan tidak ditemukan")

    details = (
        db.query(DetailTransaksiLinen, Linen)
        .join(Linen, DetailTransaksiLinen.linen_id == Linen.id)
        .filter(DetailTransaksiLinen.transaksi_id == transaksi_id)
        .all()
    )
    result = []
    for i, (d, l) in enumerate(details, 1):
        result.append({
            "no": i,
            "epc": d.epc,
            "kategori": l.kategori,
            "nama_linen": l.nama_linen,
        })
    return result

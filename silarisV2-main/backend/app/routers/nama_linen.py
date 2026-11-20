"""
Nama Linen router — CRUD at /api/nama-linen
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from app.database.session import get_db
from app.database.models import NamaLinen, Linen, KategoriLinen
from app.schemas.nama_linen import NamaLinenCreate, NamaLinenUpdate, NamaLinenResponse

router = APIRouter(prefix="/api/nama-linen", tags=["Nama Linen"])


def _build_nama_linen_response(db: Session, nl: NamaLinen) -> dict:
    """Build response dict with computed jumlah_linen and nama_kategori."""
    jumlah = (
        db.query(func.count(Linen.linen_id))
        .filter(Linen.nama_id == nl.nama_id)
        .scalar()
        or 0
    )
    kategori = db.query(KategoriLinen).filter(KategoriLinen.kategori_id == nl.kategori_id).first()
    return {
        "nama_id": nl.nama_id,
        "kategori_id": nl.kategori_id,
        "nama_kategori": kategori.nama if kategori else None,
        "nama_linen": nl.nama_linen,
        "keterangan": nl.keterangan,
        "jumlah_linen": jumlah,
    }


@router.get("", response_model=List[NamaLinenResponse])
def list_nama_linen(
    kategori_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """List nama linen, optionally filtered by kategori_id. Includes jumlah_linen and nama_kategori."""
    query = db.query(NamaLinen)
    if kategori_id is not None:
        query = query.filter(NamaLinen.kategori_id == kategori_id)
    rows = query.order_by(NamaLinen.nama_linen).all()
    return [_build_nama_linen_response(db, nl) for nl in rows]


@router.post("", response_model=NamaLinenResponse, status_code=201)
def create_nama_linen(payload: NamaLinenCreate, db: Session = Depends(get_db)):
    """Create a new nama linen (kategori_id required, unique per kategori)."""
    kategori = db.query(KategoriLinen).filter(KategoriLinen.kategori_id == payload.kategori_id).first()
    if not kategori:
        raise HTTPException(status_code=404, detail="Kategori linen tidak ditemukan.")

    existing = db.query(NamaLinen).filter(
        NamaLinen.kategori_id == payload.kategori_id,
        func.lower(NamaLinen.nama_linen) == func.lower(payload.nama_linen),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Nama linen sudah terdaftar dalam kategori ini.")

    nl = NamaLinen(
        kategori_id=payload.kategori_id,
        nama_linen=payload.nama_linen,
        keterangan=payload.keterangan.strip() if payload.keterangan else None,
    )
    db.add(nl)
    db.commit()
    db.refresh(nl)
    return _build_nama_linen_response(db, nl)


@router.put("/{nama_id}", response_model=NamaLinenResponse)
def update_nama_linen(
    nama_id: int,
    payload: NamaLinenUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing nama linen."""
    nl = db.query(NamaLinen).filter(NamaLinen.nama_id == nama_id).first()
    if not nl:
        raise HTTPException(status_code=404, detail="Nama Linen tidak ditemukan.")

    target_kategori_id = payload.kategori_id if payload.kategori_id is not None else nl.kategori_id
    if payload.kategori_id is not None:
        kategori = db.query(KategoriLinen).filter(KategoriLinen.kategori_id == payload.kategori_id).first()
        if not kategori:
            raise HTTPException(status_code=404, detail="Kategori linen tidak ditemukan.")
        nl.kategori_id = payload.kategori_id

    if payload.nama_linen is not None:
        existing = db.query(NamaLinen).filter(
            NamaLinen.kategori_id == target_kategori_id,
            func.lower(NamaLinen.nama_linen) == func.lower(payload.nama_linen),
            NamaLinen.nama_id != nama_id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Nama linen sudah terdaftar dalam kategori ini.")
        nl.nama_linen = payload.nama_linen

    if payload.keterangan is not None:
        nl.keterangan = payload.keterangan.strip() if payload.keterangan else None

    db.commit()
    db.refresh(nl)
    return _build_nama_linen_response(db, nl)


@router.delete("/{nama_id}")
def delete_nama_linen(nama_id: int, db: Session = Depends(get_db)):
    """Delete a nama linen. 409 if still in use by linen."""
    nl = db.query(NamaLinen).filter(NamaLinen.nama_id == nama_id).first()
    if not nl:
        raise HTTPException(status_code=404, detail="Nama Linen tidak ditemukan.")

    jumlah = (
        db.query(func.count(Linen.linen_id))
        .filter(Linen.nama_id == nama_id)
        .scalar()
        or 0
    )
    if jumlah > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Nama Linen ini masih dipakai oleh {jumlah} data Linen.",
        )

    db.delete(nl)
    db.commit()
    return {"detail": "Nama Linen berhasil dihapus."}

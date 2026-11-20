"""
Kategori Linen router — CRUD at /api/kategori
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.database.session import get_db
from app.database.models import KategoriLinen, Linen, NamaLinen
from app.schemas.kategori import KategoriCreate, KategoriUpdate, KategoriResponse

router = APIRouter(prefix="/api/kategori", tags=["Kategori Linen"])


def _build_kategori_response(db: Session, kategori: KategoriLinen) -> dict:
    """Build response dict with computed jumlah_linen."""
    jumlah = (
        db.query(func.count(Linen.linen_id))
        .filter(Linen.kategori_id == kategori.kategori_id)
        .scalar()
        or 0
    )
    return {
        "kategori_id": kategori.kategori_id,
        "nama": kategori.nama,
        "keterangan": kategori.keterangan,
        "jumlah_linen": jumlah,
    }


@router.get("", response_model=List[KategoriResponse])
def list_kategori(db: Session = Depends(get_db)):
    """List all kategori (no pagination — data is small). Includes jumlah_linen."""
    rows = db.query(KategoriLinen).order_by(KategoriLinen.nama).all()
    return [_build_kategori_response(db, k) for k in rows]


@router.post("", response_model=KategoriResponse, status_code=201)
def create_kategori(payload: KategoriCreate, db: Session = Depends(get_db)):
    """Create a new kategori with validation."""
    clean_nama = payload.nama.strip()
    if not clean_nama:
        raise HTTPException(status_code=422, detail="Nama kategori tidak boleh kosong.")

    existing = db.query(KategoriLinen).filter(
        func.lower(KategoriLinen.nama) == func.lower(clean_nama)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Kategori dengan nama tersebut sudah ada.")

    kategori = KategoriLinen(
        nama=clean_nama,
        keterangan=payload.keterangan.strip() if payload.keterangan else None,
    )
    db.add(kategori)
    db.commit()
    db.refresh(kategori)
    return _build_kategori_response(db, kategori)


@router.put("/{kategori_id}", response_model=KategoriResponse)
def update_kategori(
    kategori_id: int,
    payload: KategoriUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing kategori with validation."""
    kategori = db.query(KategoriLinen).filter(
        KategoriLinen.kategori_id == kategori_id
    ).first()
    if not kategori:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan.")

    if payload.nama is not None:
        clean_nama = payload.nama.strip()
        if not clean_nama:
            raise HTTPException(status_code=422, detail="Nama kategori tidak boleh kosong.")
        existing = db.query(KategoriLinen).filter(
            func.lower(KategoriLinen.nama) == func.lower(clean_nama),
            KategoriLinen.kategori_id != kategori_id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Kategori dengan nama tersebut sudah ada.")
        kategori.nama = clean_nama

    if payload.keterangan is not None:
        kategori.keterangan = payload.keterangan.strip() if payload.keterangan else None

    db.commit()
    db.refresh(kategori)
    return _build_kategori_response(db, kategori)


@router.delete("/{kategori_id}")
def delete_kategori(kategori_id: int, db: Session = Depends(get_db)):
    """Delete a kategori. 409 if still in use by linen or nama_linen."""
    kategori = db.query(KategoriLinen).filter(
        KategoriLinen.kategori_id == kategori_id
    ).first()
    if not kategori:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan.")

    jumlah_linen = (
        db.query(func.count(Linen.linen_id))
        .filter(Linen.kategori_id == kategori_id)
        .scalar()
        or 0
    )
    jumlah_nama = (
        db.query(func.count(NamaLinen.nama_id))
        .filter(NamaLinen.kategori_id == kategori_id)
        .scalar()
        or 0
    )
    if jumlah_linen > 0 or jumlah_nama > 0:
        reasons = []
        if jumlah_nama > 0:
            reasons.append(f"{jumlah_nama} master Nama Linen")
        if jumlah_linen > 0:
            reasons.append(f"{jumlah_linen} data Linen terdaftar")
        raise HTTPException(
            status_code=409,
            detail=f"Kategori ini tidak dapat dihapus karena masih digunakan oleh {', '.join(reasons)}.",
        )

    db.delete(kategori)
    db.commit()
    return {"detail": "Kategori berhasil dihapus."}

"""
Pydantic schemas for Linen endpoints.
Field names match 03_api_data_contract.md §2.1 exactly.
"""

import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


class LinenCreate(BaseModel):
    epc: str = Field(..., min_length=1, description="24-char hex EPC tag identifier")
    kategori_id: int
    nama_id: int

    @field_validator("epc")
    @classmethod
    def normalize_and_validate_epc(cls, v: str) -> str:
        cleaned = (v or "").strip().upper()
        if any(ord(ch) > 127 for ch in cleaned):
            raise ValueError("EPC mengandung karakter non-ASCII.")
        if len(cleaned) == 28 and cleaned.startswith("3000"):
            cleaned = cleaned[4:]
        if not re.fullmatch(r"[0-9A-F]{24}", cleaned):
            raise ValueError("Format EPC harus berupa 24 karakter hexadecimal.")
        return cleaned


class LinenUpdate(BaseModel):
    kategori_id: Optional[int] = None
    nama_id: Optional[int] = None
    status: Optional[str] = None


class LinenResponse(BaseModel):
    """Full linen object for list endpoints."""
    linen_id: int
    epc: str
    kategori_id: int
    kategori: str  # Derived: kategori_linen.nama
    nama_id: int
    nama_linen: str  # Derived: nama_linen.nama_linen
    status: str
    timestamp: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ShipmentHistoryItem(BaseModel):
    temp_id: int
    kode_verifikasi: Optional[str] = None
    kode_verifikasi_lokal: Optional[str] = None
    nama_rs: Optional[str] = None
    timestamp: Optional[str] = None
    status_upload: Optional[str] = None


class LinenDetailResponse(BaseModel):
    """Linen detail for GET /api/linen/{epc} (Cek Info page)."""
    epc: str
    nama_linen: str
    kategori: str
    status: str
    nama_rs: Optional[str] = None
    tanggal_registrasi: Optional[str] = None
    riwayat_pengiriman: List[ShipmentHistoryItem] = []
    transaksi_terakhir: Optional[ShipmentHistoryItem] = None

    model_config = {"from_attributes": True}

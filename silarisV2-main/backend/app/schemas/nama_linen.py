"""
Pydantic schemas for Nama Linen endpoints.
"""

from pydantic import BaseModel, model_validator
from typing import Optional


class NamaLinenCreate(BaseModel):
    kategori_id: int
    nama_linen: Optional[str] = None
    nama: Optional[str] = None
    keterangan: Optional[str] = None

    @model_validator(mode="after")
    def validate_name(self) -> "NamaLinenCreate":
        resolved = (self.nama_linen or self.nama or "").strip()
        if not resolved:
            raise ValueError("Nama linen tidak boleh kosong.")
        self.nama_linen = resolved
        return self


class NamaLinenUpdate(BaseModel):
    kategori_id: Optional[int] = None
    nama_linen: Optional[str] = None
    nama: Optional[str] = None
    keterangan: Optional[str] = None

    @model_validator(mode="after")
    def validate_name(self) -> "NamaLinenUpdate":
        if self.nama_linen is not None or self.nama is not None:
            resolved = (self.nama_linen if self.nama_linen is not None else self.nama or "").strip()
            if not resolved:
                raise ValueError("Nama linen tidak boleh kosong.")
            self.nama_linen = resolved
        return self


class NamaLinenResponse(BaseModel):
    nama_id: int
    kategori_id: int
    nama_kategori: Optional[str] = None
    nama_linen: str
    keterangan: Optional[str] = None
    jumlah_linen: int = 0  # Computed: COUNT of linen with this nama_id

    model_config = {"from_attributes": True}

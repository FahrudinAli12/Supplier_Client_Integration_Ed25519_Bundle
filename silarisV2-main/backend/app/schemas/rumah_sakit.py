"""Pydantic schemas mapped to the shared public.rumah_sakit table."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class RumahSakitCreate(BaseModel):
    kode_rs: str = Field(min_length=1, max_length=64)
    nama_rs: str = Field(min_length=1, max_length=255)
    alamat: Optional[str] = Field(default=None, max_length=2000)
    kontak: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    client_email: Optional[str] = Field(default=None, max_length=255)
    client_password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class RumahSakitUpdate(BaseModel):
    kode_rs: Optional[str] = Field(default=None, min_length=1, max_length=64)
    nama_rs: Optional[str] = Field(default=None, min_length=1, max_length=255)
    alamat: Optional[str] = Field(default=None, max_length=2000)
    kontak: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    client_email: Optional[str] = Field(default=None, max_length=255)
    client_password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    is_active: Optional[bool] = None


class RumahSakitResponse(BaseModel):
    # rs_id is retained as a string alias for compatibility with the existing
    # Supplier frontend and PengirimanTemp SQLite records. The cloud ID is BIGINT.
    rs_id: str
    id: int
    kode_rs: str
    nama_rs: str
    alamat: Optional[str] = None
    kontak: Optional[str] = None
    email: Optional[str] = None
    client_email: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

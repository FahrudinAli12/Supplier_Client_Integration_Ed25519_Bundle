from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.models.rumah_sakit import RumahSakit

logger = logging.getLogger("hospital_binding")


class HospitalBindingError(RuntimeError):
    """Base exception untuk masalah pengikatan rumah sakit lokal."""
    pass


class HospitalBindingMissingError(HospitalBindingError):
    """Database lokal belum terikat ke rumah sakit manapun."""
    pass


class HospitalBindingAmbiguousError(HospitalBindingError):
    """Database lokal memiliki lebih dari satu data rumah sakit (inkonsistensi data)."""
    pass


class HospitalBindingMismatchError(HospitalBindingError):
    """Rumah sakit yang terikat pada database lokal berbeda dari konfigurasi instalasi."""
    pass


def is_dynamic_mode() -> bool:
    """Periksa apakah mode dinamis/multi-tenant lokal aktif (HOSPITAL_CLOUD_ID=auto/0/*)."""
    val = os.getenv("HOSPITAL_CLOUD_ID", "").strip().lower()
    return not val or val in ("auto", "dynamic", "0", "*", "all")


def auto_provision_from_cloud(db: Session, hospital_id: int) -> Optional[RumahSakit]:
    """Auto-provisioning data rumah sakit dari Supabase Cloud ke database lokal pada mode dinamis."""
    if hospital_id <= 0:
        return None

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
    )

    nama = f"Rumah Sakit #{hospital_id}"
    kode = f"RS-{hospital_id}"
    alamat = None

    if supabase_url and service_key:
        try:
            import httpx
            headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
            resp = httpx.get(
                f"{supabase_url}/rest/v1/rumah_sakit?id=eq.{hospital_id}&select=id,nama_rs,kode_rs,alamat",
                headers=headers,
                timeout=5.0,
            )
            if resp.status_code == 200 and resp.json():
                data = resp.json()[0]
                nama = data.get("nama_rs") or nama
                kode = data.get("kode_rs") or kode
                alamat = data.get("alamat")
        except Exception as exc:
            logger.warning("Gagal fetch data RS ID %d dari Supabase: %s", hospital_id, exc)

    try:
        existing = db.query(RumahSakit).filter(RumahSakit.id == int(hospital_id)).first()
        if existing:
            return existing
        now = datetime.now(timezone.utc)
        new_rs = RumahSakit(
            id=int(hospital_id),
            nama=nama,
            kode=kode,
            alamat=alamat,
            created_at=now,
        )
        db.add(new_rs)
        db.commit()
        db.refresh(new_rs)
        logger.info("Auto-provisioned hospital binding: %s (ID %d)", nama, hospital_id)
        return new_rs
    except Exception as exc:
        db.rollback()
        logger.error("Auto-provisioning failed for RS ID %d: %s", hospital_id, exc)
        return None


def get_bound_hospital(db: Session, target_hospital_id: Optional[int] = None) -> Optional[RumahSakit]:
    """Ambil data rumah sakit yang terikat pada database lokal saat ini.

    Aturan:
    - Jika is_dynamic_mode() aktif:
      Cari rumah sakit yang sesuai dengan target_hospital_id. Jika ada, kembalikan.
      Jika tidak ditemukan baris sama sekali, kembalikan None.
    - Jika mode statis/pinned:
      Tabel harus memiliki tepat 1 baris. Jika 0 -> None, jika > 1 -> HospitalBindingAmbiguousError.
    """
    if is_dynamic_mode():
        if target_hospital_id is not None and int(target_hospital_id) > 0:
            found = db.query(RumahSakit).filter(RumahSakit.id == int(target_hospital_id)).first()
            if found:
                return found
        rows = db.query(RumahSakit).all()
        return rows[0] if rows else None

    rows = db.query(RumahSakit).all()
    if len(rows) == 0:
        return None
    if len(rows) > 1:
        raise HospitalBindingAmbiguousError(
            f"Inkonsistensi database: ditemukan {len(rows)} data rumah sakit pada database lokal. "
            "Satu instalasi ClientS hanya boleh terikat ke tepat satu rumah sakit."
        )
    return rows[0]


def verify_hospital_binding(db: Session, expected_hospital_id: Optional[int]) -> RumahSakit:
    """Verifikasi bahwa database lokal telah terikat dan cocok dengan konfigurasi instalasi.

    Aturan:
    - Pada mode dinamis (HOSPITAL_CLOUD_ID=auto):
      Cocokkan dengan expected_hospital_id dari sesi aktif atau auto-provision jika belum tercatat.
    - Pada mode statis/pinned (HOSPITAL_CLOUD_ID=angka):
      Wajib terikat ke tepat satu rumah sakit yang identik dengan expected_hospital_id.
    """
    if is_dynamic_mode() and expected_hospital_id is not None and int(expected_hospital_id) > 0:
        exp_id = int(expected_hospital_id)
        match_rs = db.query(RumahSakit).filter(RumahSakit.id == exp_id).first()
        if match_rs is not None:
            return match_rs
        prov = auto_provision_from_cloud(db, exp_id)
        if prov is not None:
            return prov

    bound_rs = get_bound_hospital(db, target_hospital_id=expected_hospital_id)
    if bound_rs is None:
        raise HospitalBindingMissingError(
            "Database lokal belum terikat ke rumah sakit manapun. "
            "Lakukan provisioning pengikatan rumah sakit terlebih dahulu."
        )

    if expected_hospital_id is not None:
        try:
            expected_id_int = int(expected_hospital_id)
        except (ValueError, TypeError) as exc:
            raise HospitalBindingMismatchError(
                f"Konfigurasi hospital_id instalasi ({expected_hospital_id!r}) tidak valid."
            ) from exc

        if int(bound_rs.id) != expected_id_int:
            raise HospitalBindingMismatchError(
                f"Ketidakcocokan identitas rumah sakit: database lokal terikat ke RS ID {bound_rs.id} "
                f"('{bound_rs.nama}'), tetapi konfigurasi instalasi aktif adalah RS ID {expected_id_int}. "
                "Akses ditolak untuk mencegah kontaminasi data antar-rumah sakit."
            )

    return bound_rs


def provision_hospital_binding(
    db: Session,
    hospital_id: int,
    nama_rs: str,
    kode_rs: str,
    alamat: Optional[str] = None,
) -> RumahSakit:
    """Ikat database lokal ke satu rumah sakit secara eksplisit (Provisioning).

    Aturan:
    - ID rumah sakit lokal HARUS menggunakan ID rumah sakit resmi dari cloud (BIGINT).
    - Menolak jika database lokal sudah terikat ke rumah sakit lain pada mode statis.
    """
    if hospital_id <= 0:
        raise HospitalBindingError("hospital_id harus berupa bilangan bulat positif (> 0).")

    clean_nama = (nama_rs or "").strip()
    clean_kode = (kode_rs or "").strip()
    if not clean_nama:
        raise HospitalBindingError("Nama rumah sakit tidak boleh kosong.")
    if not clean_kode:
        raise HospitalBindingError("Kode rumah sakit tidak boleh kosong.")

    existing = db.query(RumahSakit).filter(RumahSakit.id == int(hospital_id)).first()
    if existing is not None:
        existing.nama = clean_nama
        existing.kode = clean_kode
        if alamat is not None:
            existing.alamat = alamat.strip()
        db.commit()
        db.refresh(existing)
        logger.info("Informasi rumah sakit ID %d diperbarui: %s (%s)", existing.id, clean_nama, clean_kode)
        return existing

    if not is_dynamic_mode():
        bound = get_bound_hospital(db)
        if bound is not None and int(bound.id) != int(hospital_id):
            raise HospitalBindingError(
                f"Database lokal sudah terikat ke RS ID {bound.id} ('{bound.nama}'). "
                f"Pengikatan ulang ke RS ID {hospital_id} ('{clean_nama}') ditolak."
            )

    now = datetime.now(timezone.utc)
    new_rs = RumahSakit(
        id=int(hospital_id),
        nama=clean_nama,
        kode=clean_kode,
        alamat=alamat.strip() if alamat else None,
        created_at=now,
    )
    db.add(new_rs)
    db.commit()
    db.refresh(new_rs)
    logger.info("Database lokal berhasil diikat secara eksplisit ke RS ID %d: %s (%s)", new_rs.id, clean_nama, clean_kode)
    return new_rs


import time
from datetime import datetime
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.detail_transaksi_linen import DetailTransaksiLinen
from app.models.linen import Linen
from app.models.ruangan import Ruangan
from app.models.reader_device import ReaderDevice
from app.models.transaksi_linen import TransaksiLinen
from app.schemas.linen_schema import LinenCreate, LinenUpdate, LinenResponse, LinenDecommissionRequest
from app.schemas.ruangan_schema import RuanganCreate, RuanganUpdate, RuanganResponse
from app.services.auth_dependencies import (
    extract_session_hospital_id,
    require_active_session,
    require_master_data_editor,
)

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(require_active_session)],
)


@router.get("/linen", response_model=list[LinenResponse])
def list_linen(
    q: str | None = None,
    status: str | None = None,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> list[Linen]:
    """Daftar master linen dengan pencarian dan filter status (tersedia/dicuci/dipakai)."""
    query = db.query(Linen)
    active_hospital_id = extract_session_hospital_id(session)
    if active_hospital_id:
        query = query.filter((Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None)))
    if status:
        query = query.filter(Linen.status == status)
    if q:
        search = f"%{q.lower()}%"
        query = query.filter(
            (Linen.epc.ilike(search))
            | (Linen.nama_linen.ilike(search))
            | (Linen.kategori.ilike(search))
            | (Linen.lokasi.ilike(search))
        )
    return query.order_by(Linen.created_at.desc()).all()


@router.post("/linen", response_model=LinenResponse, status_code=status.HTTP_201_CREATED)
def create_linen(
    payload: LinenCreate,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> Linen:
    """Buat data linen baru."""
    active_hospital_id = extract_session_hospital_id(session)
    existing_query = db.query(Linen).filter(Linen.epc == payload.epc)
    if active_hospital_id:
        existing_query = existing_query.filter(
            (Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None))
        )
    existing = existing_query.first()
    if existing:
        raise HTTPException(status_code=400, detail="EPC sudah terdaftar")
    linen_dict = payload.model_dump()
    if active_hospital_id and not linen_dict.get("hospital_id"):
        linen_dict["hospital_id"] = active_hospital_id
    linen = Linen(**linen_dict)
    db.add(linen)
    db.commit()
    db.refresh(linen)
    return linen


@router.get("/linen/{linen_id}", response_model=LinenResponse)
def get_linen(
    linen_id: int,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> Linen:
    active_hospital_id = extract_session_hospital_id(session)
    query = db.query(Linen).filter(Linen.id == linen_id)
    if active_hospital_id:
        query = query.filter((Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None)))
    linen = query.first()
    if linen is None:
        raise HTTPException(status_code=404, detail="Linen tidak ditemukan")
    return linen


@router.put("/linen/{linen_id}", response_model=LinenResponse)
def update_linen(
    linen_id: int,
    payload: LinenUpdate,
    epc: str | None = None,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> Linen:
    active_hospital_id = extract_session_hospital_id(session)
    query = db.query(Linen).filter(Linen.id == linen_id)
    if active_hospital_id:
        query = query.filter((Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None)))
    linen = query.first()
    if not linen and epc:
        epc_query = db.query(Linen).filter(Linen.epc == epc)
        if active_hospital_id:
            epc_query = epc_query.filter(
                (Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None))
            )
        linen = epc_query.first()
    if linen is None:
        raise HTTPException(status_code=404, detail="Linen tidak ditemukan")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "lokasi":
            setattr(linen, key, value)
        elif value is not None and value != "":
            setattr(linen, key, value)
    db.commit()
    db.refresh(linen)
    return linen


@router.delete("/linen/{linen_id}", response_model=dict[str, str])
def delete_linen(
    linen_id: int,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    active_hospital_id = extract_session_hospital_id(session)
    query = db.query(Linen).filter(Linen.id == linen_id)
    if active_hospital_id:
        query = query.filter((Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None)))
    linen = query.first()
    if linen is None:
        raise HTTPException(status_code=404, detail="Linen tidak ditemukan")
    db.delete(linen)
    db.commit()
    return {"status": "deleted"}


@router.post("/linen/decommission", response_model=dict[str, Any])
def decommission_linen_batch(
    payload: LinenDecommissionRequest,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Pemusnahan atau Afkir linen massal berdasarkan scan fisik RFID yang telah divalidasi."""
    if not payload.epc_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Daftar scan fisik EPC linen tidak boleh kosong.",
        )

    active_hospital_id = extract_session_hospital_id(session)
    clean_epcs = list(dict.fromkeys(e.strip().upper() for e in payload.epc_list if e and e.strip()))
    if not clean_epcs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak ada kode EPC yang valid dalam daftar scan fisik.",
        )

    # Ambil linen yang terikat pada rumah sakit aktif
    query = db.query(Linen).filter(Linen.epc.in_(clean_epcs))
    if active_hospital_id:
        query = query.filter(
            (Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None))
        )
    matched_linens = query.all()

    if not matched_linens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak ada linen terdaftar milik rumah sakit ini dalam daftar scan fisik yang dikirimkan.",
        )

    kode_trx = f"TRX-AFKIR-{int(time.time())}"
    staff_name = (
        payload.petugas.strip()
        if (payload.petugas and payload.petugas.strip())
        else getattr(session, "nama_lengkap", getattr(session, "email", "Petugas Linen"))
    )

    action = (payload.action or "afkir").lower().strip()

    # 1. Catat Transaksi Afkir ke TransaksiLinen
    trx = TransaksiLinen(
        jenis_transaksi="afkir",
        kode_transaksi=kode_trx,
        petugas=staff_name,
        ruangan="Pemusnahan / Afkir",
        total_linen=len(matched_linens),
        status="selesai",
        catatan=f"Pemusnahan linen ({payload.alasan}). Catatan: {payload.catatan or '-'}",
        hospital_id=active_hospital_id,
    )
    db.add(trx)
    db.flush()

    # 2. Catat DetailTransaksiLinen dan update atau delete linen
    for ln in matched_linens:
        status_sebelum = ln.status
        lokasi_sebelum = ln.lokasi

        detail = DetailTransaksiLinen(
            transaksi_id=trx.id,
            linen_id=ln.id,
            epc=ln.epc,
            status_sebelum=status_sebelum,
            status_setelah="afkir" if action == "afkir" else "dihapus",
            waktu_scan=datetime.utcnow(),
            keterangan=f"Pemusnahan linen fisik ({payload.alasan})",
        )
        db.add(detail)

        if action == "delete":
            db.delete(ln)
        else:
            ln.status = "afkir"
            ln.lokasi = "Afkir / Dimusnahkan"
            db.add(ln)

    db.commit()

    return {
        "status": "success",
        "action": action,
        "total_processed": len(matched_linens),
        "kode_transaksi": kode_trx,
        "message": f"Berhasil memproses pemusnahan {len(matched_linens)} linen secara fisik.",
    }


@router.get("/ruangan", response_model=list[RuanganResponse])
def list_ruangan(
    q: str | None = None,
    is_active: bool | None = None,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> list[Ruangan]:
    """Daftar master ruangan dengan pencarian sederhana dan filter status aktif.

    Akses:
    - Seluruh pengguna terautentikasi (Admin, Supervisor, Operator) dapat membaca.
    - Parameter is_active:
      - None: Kembalikan semua ruangan (aktif & nonaktif) untuk kebutuhan manajemen.
      - True: Hanya kembalikan ruangan aktif (untuk dropdown transaksi).
      - False: Hanya kembalikan ruangan nonaktif.
    """
    query = db.query(Ruangan)
    active_hospital_id = extract_session_hospital_id(session)
    if active_hospital_id:
        query = query.filter((Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None)))

    if is_active is not None:
        query = query.filter(Ruangan.is_active == is_active)
    if q:
        search = f"%{q.lower()}%"
        query = query.filter(
            (Ruangan.kode_ruangan.ilike(search))
            | (Ruangan.nama_ruangan.ilike(search))
            | (Ruangan.keterangan.ilike(search))
        )
    return query.order_by(Ruangan.id.desc()).all()


@router.post("/ruangan", response_model=RuanganResponse, status_code=status.HTTP_201_CREATED)
def create_ruangan(
    payload: RuanganCreate,
    session: Any = Depends(require_master_data_editor),
    db: Session = Depends(get_db),
) -> Ruangan:
    """Buat data ruangan baru. Wajib role Admin atau Supervisor."""
    active_hospital_id = extract_session_hospital_id(session)
    existing_query = db.query(Ruangan).filter(Ruangan.kode_ruangan == payload.kode_ruangan)
    if active_hospital_id:
        existing_query = existing_query.filter(
            (Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None))
        )
    existing = existing_query.first()
    if existing:
        raise HTTPException(status_code=400, detail="Kode ruangan sudah ada")

    ruangan_dict = payload.model_dump()
    if active_hospital_id and not ruangan_dict.get("hospital_id"):
        ruangan_dict["hospital_id"] = active_hospital_id

    ruangan = Ruangan(**ruangan_dict)
    db.add(ruangan)
    db.commit()
    db.refresh(ruangan)
    return ruangan


@router.put("/ruangan/{ruangan_id}", response_model=RuanganResponse)
def update_ruangan(
    ruangan_id: int,
    payload: RuanganUpdate,
    session: Any = Depends(require_master_data_editor),
    db: Session = Depends(get_db),
) -> Ruangan:
    """Perbarui data ruangan (kode, nama, keterangan, is_active). Wajib role Admin atau Supervisor."""
    active_hospital_id = extract_session_hospital_id(session)
    ruangan_query = db.query(Ruangan).filter(Ruangan.id == ruangan_id)
    if active_hospital_id:
        ruangan_query = ruangan_query.filter(
            (Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None))
        )
    ruangan = ruangan_query.first()
    if ruangan is None:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    update_dict = payload.model_dump(exclude_unset=True)

    if "kode_ruangan" in update_dict and update_dict["kode_ruangan"]:
        new_kode = update_dict["kode_ruangan"].strip()
        if new_kode != ruangan.kode_ruangan:
            existing_query = db.query(Ruangan).filter(
                Ruangan.kode_ruangan == new_kode,
                Ruangan.id != ruangan_id,
            )
            if active_hospital_id:
                existing_query = existing_query.filter(
                    (Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None))
                )
            if existing_query.first():
                raise HTTPException(status_code=400, detail="Kode ruangan sudah digunakan oleh ruangan lain")
            ruangan.kode_ruangan = new_kode

    if "nama_ruangan" in update_dict and update_dict["nama_ruangan"]:
        ruangan.nama_ruangan = update_dict["nama_ruangan"].strip()

    if "keterangan" in update_dict:
        ruangan.keterangan = update_dict["keterangan"]

    if "is_active" in update_dict and update_dict["is_active"] is not None:
        ruangan.is_active = bool(update_dict["is_active"])

    db.commit()
    db.refresh(ruangan)
    return ruangan


@router.delete("/ruangan/{ruangan_id}", response_model=dict[str, Any])
def delete_ruangan(
    ruangan_id: int,
    session: Any = Depends(require_master_data_editor),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Penonaktifan ruangan (Soft-Delete Enforcement). Wajib role Admin atau Supervisor.

    Kebijakan Integritas:
    - Tidak melakukan SQL DELETE fisik pada tabel ruangan dalam kondisi apapun.
    - Mengubah kolom is_active menjadi False.
    - Record master ruangan tetap abadi di SQLite demi menjaga integritas data riwayat
      TransaksiLinen dan Linen.lokasi seumur hidup sistem (bahkan jika ruangan pernah di-rename).
    - Mencegah orphaning jejak audit historis.
    """
    active_hospital_id = extract_session_hospital_id(session)
    ruangan_query = db.query(Ruangan).filter(Ruangan.id == ruangan_id)
    if active_hospital_id:
        ruangan_query = ruangan_query.filter(
            (Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None))
        )
    ruangan = ruangan_query.first()
    if ruangan is None:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    # Soft-delete enforcement: ubah is_active menjadi False tanpa SQL DELETE fisik
    ruangan.is_active = False
    db.commit()
    db.refresh(ruangan)
    return {
        "status": "deleted",
        "action": "deactivated",
        "message": f"Ruangan '{ruangan.nama_ruangan}' berhasil dinonaktifkan (soft-delete). Record master tetap tersimpan untuk integritas riwayat transaksi.",
        "id": ruangan.id,
        "is_active": ruangan.is_active,
    }


@router.patch("/ruangan/{ruangan_id}/status", response_model=RuanganResponse)
def toggle_ruangan_status(
    ruangan_id: int,
    is_active: Optional[bool] = Query(default=None),
    session: Any = Depends(require_master_data_editor),
    db: Session = Depends(get_db),
) -> Ruangan:
    """Mengaktifkan atau menonaktifkan ruangan. Wajib role Admin atau Supervisor.

    - Jika parameter is_active diberikan: ubah ke nilai boolean tersebut (True = Aktifkan, False = Nonaktifkan).
    - Jika parameter is_active tidak diberikan: toggle status saat ini (True <-> False).
    """
    active_hospital_id = extract_session_hospital_id(session)
    ruangan_query = db.query(Ruangan).filter(Ruangan.id == ruangan_id)
    if active_hospital_id:
        ruangan_query = ruangan_query.filter(
            (Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None))
        )
    ruangan = ruangan_query.first()
    if ruangan is None:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    if is_active is not None:
        ruangan.is_active = bool(is_active)
    else:
        ruangan.is_active = not bool(ruangan.is_active)

    db.commit()
    db.refresh(ruangan)
    return ruangan


@router.get("/reader", response_model=list[dict])
def list_reader(db: Session = Depends(get_db)) -> list[dict]:
    """Daftar reader device yang terdaftar."""
    readers = db.query(ReaderDevice).all()
    return [{"id": item.id, "nama_reader": item.nama_reader, "port": item.port, "status": item.status} for item in readers]

import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.detail_transaksi_linen import DetailTransaksiLinen
from app.models.linen import Linen
from app.models.riwayat_linen import RiwayatLinen
from app.models.ruangan import Ruangan
from app.models.transaksi_linen import TransaksiLinen
from app.schemas.detail_transaksi_schema import DetailTransaksiCreate, DetailTransaksiResponse
from app.schemas.riwayat_schema import RiwayatCreate, RiwayatResponse
from app.schemas.transaksi_schema import BatchTransaksiCreate, TransaksiCreate, TransaksiResponse
from app.services.auth_dependencies import extract_session_hospital_id, require_active_session
from app.services.sync_service import SyncService

router = APIRouter(
    prefix="/transaksi",
    tags=["transaksi"],
    dependencies=[Depends(require_active_session)],
)


@router.get("", response_model=list[TransaksiResponse])
def list_transaksi(
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> list[TransaksiLinen]:
    """Daftar transaksi terisolasi sesuai rumah sakit aktif."""
    active_hospital_id = extract_session_hospital_id(session)
    query = db.query(TransaksiLinen)
    if active_hospital_id:
        query = query.filter(
            (TransaksiLinen.hospital_id == active_hospital_id) | (TransaksiLinen.hospital_id.is_(None))
        )
    return query.order_by(TransaksiLinen.id.desc()).all()


@router.post("", response_model=TransaksiResponse, status_code=status.HTTP_201_CREATED)
def create_transaksi(
    payload: TransaksiCreate,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> TransaksiLinen:
    """Buat header transaksi baru terikat pada rumah sakit aktif."""
    active_hospital_id = extract_session_hospital_id(session)
    trx_dict = payload.model_dump()
    if active_hospital_id and not trx_dict.get("hospital_id"):
        trx_dict["hospital_id"] = active_hospital_id
    transaksi = TransaksiLinen(**trx_dict)
    db.add(transaksi)
    db.commit()
    db.refresh(transaksi)
    return transaksi


@router.post("/batch", response_model=TransaksiResponse, status_code=status.HTTP_201_CREATED)
def create_batch_transaksi(
    payload: BatchTransaksiCreate,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> TransaksiLinen:
    """Proses transaksi batch multiple EPC (Linen Masuk / Keluar / Cuci) untuk rumah sakit aktif."""
    if not payload.epc_list:
        raise HTTPException(status_code=400, detail="Daftar EPC tidak boleh kosong")

    active_hospital_id = extract_session_hospital_id(session)
    kode_trx = payload.kode_transaksi or f"TRX-{payload.jenis_transaksi.upper()}-{int(time.time())}"

    unique_epcs = list(dict.fromkeys(payload.epc_list))

    valid_items = []
    for epc in unique_epcs:
        linen_query = db.query(Linen).filter(Linen.epc == epc)
        if active_hospital_id:
            linen_query = linen_query.filter(
                (Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None))
            )
        linen = linen_query.first()
        if not linen:
            continue
        if linen.status in ("afkir", "dimusnahkan"):
            continue
        valid_items.append((epc, linen))

    if not valid_items:
        raise HTTPException(
            status_code=400,
            detail="Tidak ada linen aktif terdaftar pada rumah sakit ini yang dapat diproses. Pastikan linen telah diverifikasi dan bukan linen afkir/dimusnahkan."
        )

    if payload.ruangan and payload.ruangan.strip():
        cleaned_room = payload.ruangan.strip()
        room_check = db.query(Ruangan).filter(Ruangan.nama_ruangan == cleaned_room)
        if active_hospital_id:
            room_check = room_check.filter(
                (Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None))
            )
        room_obj = room_check.first()
        if room_obj and not room_obj.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"Ruangan tujuan '{cleaned_room}' berstatus nonaktif dan tidak dapat digunakan untuk transaksi baru."
            )

    # 1. Header Transaksi
    transaksi = TransaksiLinen(
        jenis_transaksi=payload.jenis_transaksi,
        kode_transaksi=kode_trx,
        petugas=payload.petugas or "Petugas UI",
        ruangan=payload.ruangan or ("R. Laundry" if payload.jenis_transaksi == "masuk" else "Ruangan Pasien"),
        total_linen=len(valid_items),
        status="selesai",
        catatan=payload.catatan,
        hospital_id=active_hospital_id,
    )
    db.add(transaksi)
    db.flush()

    for epc, linen in valid_items:
        status_sebelum = linen.status
        lokasi_sebelum = linen.lokasi

        if payload.jenis_transaksi == "keluar":
            status_setelah = "dipakai"
            lokasi_setelah = payload.ruangan or "Ruangan Pasien"
        elif payload.jenis_transaksi == "masuk":
            status_setelah = "dicuci"
            lokasi_setelah = "R. Laundry"
            linen.total_cuci += 1
        elif payload.jenis_transaksi == "cuci":
            status_setelah = "tersedia"
            lokasi_setelah = "Gudang / Storage"
        else:
            status_setelah = linen.status
            lokasi_setelah = linen.lokasi

        linen.status = status_setelah
        linen.lokasi = lokasi_setelah
        db.add(linen)

        detail = DetailTransaksiLinen(
            transaksi_id=transaksi.id,
            linen_id=linen.id,
            epc=epc,
            status_sebelum=status_sebelum,
            status_setelah=status_setelah,
            keterangan=payload.catatan or f"Batch {payload.jenis_transaksi}",
        )
        db.add(detail)

        riwayat = RiwayatLinen(
            linen_id=linen.id,
            transaksi_id=transaksi.id,
            event_type=payload.jenis_transaksi,
            lokasi_sebelumnya=lokasi_sebelum,
            lokasi_sesudah=lokasi_setelah,
            hospital_id=active_hospital_id,
        )
        db.add(riwayat)

    db.commit()

    try:
        SyncService().enqueue_for_sync(
            {
                "transaksi_id": transaksi.id,
                "kode_transaksi": transaksi.kode_transaksi,
                "jenis_transaksi": transaksi.jenis_transaksi,
                "petugas": transaksi.petugas,
                "ruangan": transaksi.ruangan,
                "hospital_id": active_hospital_id,
                "epcs": unique_epcs,
                "timestamp": time.time(),
            }
        )
    except Exception:
        pass

    return transaksi


@router.post("/detail", response_model=DetailTransaksiResponse, status_code=status.HTTP_201_CREATED)
def create_detail_transaksi(
    payload: DetailTransaksiCreate,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> DetailTransaksiLinen:
    """Tambah detail item ke transaksi."""
    active_hospital_id = extract_session_hospital_id(session)
    if active_hospital_id:
        trx = db.query(TransaksiLinen).filter(
            TransaksiLinen.id == payload.transaksi_id,
            (TransaksiLinen.hospital_id == active_hospital_id) | (TransaksiLinen.hospital_id.is_(None)),
        ).first()
        if not trx:
            raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")

    existing = (
        db.query(DetailTransaksiLinen)
        .filter(DetailTransaksiLinen.transaksi_id == payload.transaksi_id, DetailTransaksiLinen.epc == payload.epc)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="EPC sudah ada dalam transaksi ini")

    detail = DetailTransaksiLinen(**payload.model_dump())
    db.add(detail)
    db.commit()
    db.refresh(detail)

    linen_query = db.query(Linen).filter(Linen.epc == payload.epc)
    if active_hospital_id:
        linen_query = linen_query.filter(
            (Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None))
        )
    linen = linen_query.first()
    if linen is not None:
        linen.status = "dipakai" if payload.transaksi_id else linen.status
        linen.lokasi = "Ruangan" if payload.transaksi_id else linen.lokasi
        db.add(linen)
        db.commit()

    return detail


@router.post("/riwayat", response_model=RiwayatResponse, status_code=status.HTTP_201_CREATED)
def create_riwayat(
    payload: RiwayatCreate,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> RiwayatLinen:
    """Catat riwayat pergerakan linen."""
    active_hospital_id = extract_session_hospital_id(session)
    r_dict = payload.model_dump()
    if active_hospital_id and not r_dict.get("hospital_id"):
        r_dict["hospital_id"] = active_hospital_id
    riwayat = RiwayatLinen(**r_dict)
    db.add(riwayat)

    linen_query = db.query(Linen).filter(Linen.id == payload.linen_id)
    if active_hospital_id:
        linen_query = linen_query.filter(
            (Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None))
        )
    linen = linen_query.first()
    if linen is not None:
        if payload.event_type == "keluar":
            linen.status = "dipakai"
            linen.lokasi = payload.lokasi_sesudah or linen.lokasi
        elif payload.event_type == "masuk":
            linen.status = "tersedia"
            linen.lokasi = payload.lokasi_sesudah or linen.lokasi
        elif payload.event_type == "cuci":
            linen.status = "dicuci"
            linen.lokasi = payload.lokasi_sesudah or linen.lokasi
        db.add(linen)

    db.commit()
    db.refresh(riwayat)
    return riwayat


@router.get("/riwayat", response_model=list[RiwayatResponse])
def list_riwayat(
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> list[RiwayatLinen]:
    """Ambil seluruh riwayat linen milik rumah sakit aktif."""
    active_hospital_id = extract_session_hospital_id(session)
    query = db.query(RiwayatLinen)
    if active_hospital_id:
        query = query.filter(
            (RiwayatLinen.hospital_id == active_hospital_id) | (RiwayatLinen.hospital_id.is_(None))
        )
    return query.order_by(RiwayatLinen.id.desc()).all()


@router.get("/{transaksi_id}/detail")
def get_transaksi_detail(
    transaksi_id: int,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Ambil detail per transaksi dengan data master linen."""
    active_hospital_id = extract_session_hospital_id(session)
    if active_hospital_id:
        trx = db.query(TransaksiLinen).filter(
            TransaksiLinen.id == transaksi_id,
            (TransaksiLinen.hospital_id == active_hospital_id) | (TransaksiLinen.hospital_id.is_(None)),
        ).first()
        if not trx:
            raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")

    details = (
        db.query(DetailTransaksiLinen, Linen)
        .join(Linen, DetailTransaksiLinen.linen_id == Linen.id)
        .filter(DetailTransaksiLinen.transaksi_id == transaksi_id)
        .all()
    )
    result = []
    for d, l in details:
        result.append({
            "id": d.id,
            "epc": d.epc,
            "kategori": l.kategori,
            "nama_linen": l.nama_linen,
            "total_cuci": l.total_cuci,
            "keterangan": d.keterangan
        })
    return result


class AutoScanRequest(BaseModel):
    epc: str = Field(..., min_length=1)
    transaction_type: str = Field(..., description="LINEN_MASUK or LINEN_KELUAR or masuk or keluar")
    reader_name: Optional[str] = None
    port: Optional[str] = None
    ruangan: Optional[str] = None
    petugas: Optional[str] = None


@router.post("/auto-scan", status_code=status.HTTP_201_CREATED)
def auto_scan_transaction(
    payload: AutoScanRequest,
    session: Any = Depends(require_active_session),
    db: Session = Depends(get_db),
):
    """Proses otomatis 1 RFID Scan dari COM3 (Linen Masuk) atau COM4 (Linen Keluar)."""
    active_hospital_id = extract_session_hospital_id(session)
    epc = payload.epc.strip().upper()
    if len(epc) < 4:
        raise HTTPException(status_code=400, detail="Format EPC tidak valid")

    r_name = (payload.reader_name or "").upper()
    t_type = (payload.transaction_type or "").upper()
    port = (payload.port or "").upper()

    # Rule checks for COM3 (Linen Masuk) and COM4 (Linen Keluar)
    if "KELUAR" in t_type:
        if "MASUK" in r_name or port == "COM3":
            raise HTTPException(
                status_code=400,
                detail="Koneksi COM3 (RFID Linen Masuk) tidak diizinkan membuat transaksi Linen Keluar"
            )
        jenis_transaksi = "keluar"
        reader_source = payload.reader_name or "RFID_LINEN_KELUAR"
        port_source = payload.port or "COM4"
        status_setelah = "dipakai"
        lokasi_setelah = payload.ruangan or "Ruangan Pasien"
        if payload.ruangan and payload.ruangan.strip():
            cleaned_room = payload.ruangan.strip()
            room_check = db.query(Ruangan).filter(Ruangan.nama_ruangan == cleaned_room)
            if active_hospital_id:
                room_check = room_check.filter(
                    (Ruangan.hospital_id == active_hospital_id) | (Ruangan.hospital_id.is_(None))
                )
            room_obj = room_check.first()
            if room_obj and not room_obj.is_active:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ruangan tujuan '{cleaned_room}' berstatus nonaktif dan tidak dapat digunakan untuk transaksi baru."
                )
    else:
        if "KELUAR" in r_name or port == "COM4":
            raise HTTPException(
                status_code=400,
                detail="Koneksi COM4 (RFID Linen Keluar) tidak diizinkan membuat transaksi Linen Masuk"
            )
        jenis_transaksi = "masuk"
        reader_source = payload.reader_name or "RFID_LINEN_MASUK"
        port_source = payload.port or "COM3"
        status_setelah = "dicuci"
        lokasi_setelah = "R. Laundry"

    # Verify linen exists in master database for the active hospital
    linen_query = db.query(Linen).filter(Linen.epc == epc)
    if active_hospital_id:
        linen_query = linen_query.filter(
            (Linen.hospital_id == active_hospital_id) | (Linen.hospital_id.is_(None))
        )
    linen = linen_query.first()
    if not linen:
        raise HTTPException(
            status_code=400,
            detail=f"EPC {epc} belum terdaftar di sistem rumah sakit Anda. Hanya linen yang sudah terdaftar yang dapat diproses."
        )

    status_sebelum = linen.status
    lokasi_sebelum = linen.lokasi
    if jenis_transaksi == "masuk":
        linen.total_cuci += 1
    linen.status = status_setelah
    linen.lokasi = lokasi_setelah
    db.add(linen)

    kode_trx = f"AUTO-{jenis_transaksi.upper()}-{int(time.time()*1000)}"
    transaksi = TransaksiLinen(
        jenis_transaksi=jenis_transaksi,
        kode_transaksi=kode_trx,
        petugas=payload.petugas or f"RFID Scanner ({reader_source})",
        ruangan=lokasi_setelah,
        total_linen=1,
        status="selesai",
        catatan=f"Auto-scan dari {reader_source} ({port_source})",
        reader_source=reader_source,
        port_source=port_source,
        hospital_id=active_hospital_id,
    )
    db.add(transaksi)
    db.commit()
    db.refresh(transaksi)

    detail = DetailTransaksiLinen(
        transaksi_id=transaksi.id,
        linen_id=linen.id,
        epc=epc,
        status_sebelum=status_sebelum,
        status_setelah=status_setelah,
        keterangan=f"Auto scan via {reader_source}",
    )
    db.add(detail)

    riwayat = RiwayatLinen(
        linen_id=linen.id,
        transaksi_id=transaksi.id,
        event_type=jenis_transaksi,
        lokasi_sebelumnya=lokasi_sebelum,
        lokasi_sesudah=lokasi_setelah,
        hospital_id=active_hospital_id,
    )
    db.add(riwayat)
    db.commit()

    return {
        "status": "ok",
        "transaksi_id": transaksi.id,
        "kode_transaksi": transaksi.kode_transaksi,
        "jenis_transaksi": jenis_transaksi,
        "reader_source": reader_source,
        "port_source": port_source,
        "linen": {
            "id": linen.id,
            "epc": linen.epc,
            "nama_linen": linen.nama_linen,
            "kategori": linen.kategori,
            "status": linen.status,
            "lokasi": linen.lokasi,
            "total_cuci": linen.total_cuci,
        }
    }

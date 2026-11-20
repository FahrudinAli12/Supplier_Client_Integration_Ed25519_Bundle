"""
Dashboard router — GET /api/dashboard/summary
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.session import get_db
from app.database.models import Linen, PengirimanTemp, RumahSakitLocal

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    Dashboard summary calculated directly from actual local database:
    - total_linen: all registered linen
    - total_tersedia: linen with status 'tersedia'
    - total_dikirim: linen with status 'dikirim'
    - total_rumah_sakit: active hospitals in local master cache
    - total_transaksi_pengiriman: total shipment transactions recorded
    - transaksi_berhasil_disinkronkan: shipments with status 'sukses'
    - transaksi_gagal: shipments with status 'gagal_permanen'
    - antrean_membutuhkan_tindakan: shipments pending or permanently failed
    - total_antrean_bermasalah: backward-compatibility alias for antrean_membutuhkan_tindakan
    """
    total_linen = db.query(func.count(Linen.linen_id)).scalar() or 0
    total_tersedia = (
        db.query(func.count(Linen.linen_id))
        .filter(Linen.status == "tersedia")
        .scalar()
        or 0
    )
    total_dikirim = (
        db.query(func.count(Linen.linen_id))
        .filter(Linen.status == "dikirim")
        .scalar()
        or 0
    )
    total_rumah_sakit = (
        db.query(func.count(RumahSakitLocal.rs_id))
        .filter(RumahSakitLocal.is_active == True)
        .scalar()
        or 0
    )
    total_transaksi = db.query(func.count(PengirimanTemp.temp_id)).scalar() or 0
    transaksi_sukses = (
        db.query(func.count(PengirimanTemp.temp_id))
        .filter(PengirimanTemp.status_upload == "sukses")
        .scalar()
        or 0
    )
    transaksi_gagal = (
        db.query(func.count(PengirimanTemp.temp_id))
        .filter(PengirimanTemp.status_upload == "gagal_permanen")
        .scalar()
        or 0
    )
    antrean_tindakan = (
        db.query(func.count(PengirimanTemp.temp_id))
        .filter(PengirimanTemp.status_upload.in_(["pending", "gagal_permanen"]))
        .scalar()
        or 0
    )

    return {
        "total_linen": total_linen,
        "total_tersedia": total_tersedia,
        "total_dikirim": total_dikirim,
        "total_rumah_sakit": total_rumah_sakit,
        "total_transaksi_pengiriman": total_transaksi,
        "transaksi_berhasil_disinkronkan": transaksi_sukses,
        "transaksi_gagal": transaksi_gagal,
        "antrean_membutuhkan_tindakan": antrean_tindakan,
        "total_antrean_bermasalah": transaksi_gagal,
    }

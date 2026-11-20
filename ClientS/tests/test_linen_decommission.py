import os
import pytest
from starlette.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.models.ruangan import Ruangan
from app.models.rumah_sakit import RumahSakit
from app.models.linen import Linen
from app.models.transaksi_linen import TransaksiLinen
from app.models.detail_transaksi_linen import DetailTransaksiLinen
from app.services.auth_dependencies import require_active_session
from app.routers.auth_router import get_default_session_store
from app.main import app


@pytest.fixture
def decommission_test_env():
    """Environment terisolasi untuk pengujian afkir & pemusnahan linen via RFID."""
    os.environ["DISABLE_BACKGROUND_SERVICES_FOR_TESTS"] = "1"
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Bersihkan tabel terkait
    db.query(DetailTransaksiLinen).delete()
    db.query(TransaksiLinen).delete()
    db.query(Linen).delete()
    db.query(Ruangan).delete()
    db.query(RumahSakit).delete()

    h1 = RumahSakit(id=201, kode="RS_TEST_AFKIR", nama="RS Test Afkir")
    h2 = RumahSakit(id=202, kode="RS_TEST_OTHER", nama="RS Test Other")
    db.add_all([h1, h2])
    db.commit()

    # Tambah ruangan aktif
    r1 = Ruangan(id=10, kode_ruangan="R-01", nama_ruangan="R Mawar 001", is_active=True, hospital_id=201)
    db.add(r1)

    # Tambah linen untuk RS 201
    l1 = Linen(id=1, epc="EPC_AFKIR_001", kategori="Sprei", nama_linen="Sprei Pasien 01", lokasi="R Mawar 001", status="tersedia", hospital_id=201)
    l2 = Linen(id=2, epc="EPC_AFKIR_002", kategori="Selimut", nama_linen="Selimut Pasien 02", lokasi="R Mawar 001", status="dipakai", hospital_id=201)
    l3 = Linen(id=3, epc="EPC_OTHER_003", kategori="Handuk", nama_linen="Handuk RS Lain", lokasi="Storage", status="tersedia", hospital_id=202)
    db.add_all([l1, l2, l3])
    db.commit()
    db.close()

    yield 201

    db = SessionLocal()
    db.query(DetailTransaksiLinen).delete()
    db.query(TransaksiLinen).delete()
    db.query(Linen).delete()
    db.query(Ruangan).delete()
    db.query(RumahSakit).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_decommission_validation(decommission_test_env):
    """Pengujian validasi data scan fisik sebelum pemusnahan."""
    hospital_id = decommission_test_env
    store = get_default_session_store()
    session = await store.create_session(
        user_id="user_admin_afkir",
        email="admin@rsafkir.id",
        hospital_id=hospital_id,
        hospital_name="RS Test Afkir",
        hospital_code="RS_TEST_AFKIR",
        role="admin",
        access_token="tok_afkir_1",
        refresh_token="ref_afkir_1",
        token_expires_in=3600,
    )

    app.dependency_overrides[require_active_session] = lambda: session
    client = TestClient(app)

    try:
        # 1. Payload kosong -> HTTP 400 atau 422 (Pydantic validation)
        res = client.post("/api/master/linen/decommission", json={
            "epc_list": [],
            "alasan": "Rusak",
            "petugas": "Bagus"
        })
        assert res.status_code in (400, 422)

        # 2. Tag EPC milik RS lain (bukan milik RS 201) -> HTTP 400
        res = client.post("/api/master/linen/decommission", json={
            "epc_list": ["EPC_OTHER_003"],
            "alasan": "Rusak",
            "petugas": "Bagus"
        })
        assert res.status_code == 400
        assert "Tidak ada linen terdaftar milik rumah sakit ini" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(require_active_session, None)


@pytest.mark.asyncio
async def test_decommission_action_afkir_success(decommission_test_env):
    """Pengujian alur afkir: status linen dikunci menjadi afkir dan tercatat di riwayat."""
    hospital_id = decommission_test_env
    store = get_default_session_store()
    session = await store.create_session(
        user_id="user_admin_afkir",
        email="admin@rsafkir.id",
        hospital_id=hospital_id,
        hospital_name="RS Test Afkir",
        hospital_code="RS_TEST_AFKIR",
        role="admin",
        access_token="tok_afkir_2",
        refresh_token="ref_afkir_2",
        token_expires_in=3600,
    )

    app.dependency_overrides[require_active_session] = lambda: session
    client = TestClient(app)

    try:
        res = client.post("/api/master/linen/decommission", json={
            "epc_list": ["EPC_AFKIR_001"],
            "alasan": "Rusak / Robek",
            "petugas": "Bagus",
            "catatan": "Sobek parah di ruang dahlia",
            "action": "afkir"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["total_processed"] == 1
        assert "TRX-AFKIR" in data["kode_transaksi"]

        # Verifikasi database lokal
        db = SessionLocal()
        l1 = db.query(Linen).filter(Linen.epc == "EPC_AFKIR_001").first()
        assert l1.status == "afkir"
        assert l1.lokasi == "Afkir / Dimusnahkan"

        # Verifikasi transaksi tercatat
        trx = db.query(TransaksiLinen).filter(TransaksiLinen.kode_transaksi == data["kode_transaksi"]).first()
        assert trx is not None
        assert trx.jenis_transaksi == "afkir"
        assert trx.total_linen == 1
        assert trx.petugas == "Bagus"
        db.close()

        # Verifikasi bahwa linen afkir ditolak dalam transaksi laundry masuk/keluar
        res_trx = client.post("/api/transaksi/batch", json={
            "jenis_transaksi": "keluar",
            "ruangan": "R Mawar 001",
            "petugas": "Bagus",
            "epc_list": ["EPC_AFKIR_001"]
        })
        assert res_trx.status_code == 400
        assert "afkir" in res_trx.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(require_active_session, None)


@pytest.mark.asyncio
async def test_decommission_action_delete_success(decommission_test_env):
    """Pengujian alur delete permanen dari database lokal dengan tetap menyimpan log transaksi."""
    hospital_id = decommission_test_env
    store = get_default_session_store()
    session = await store.create_session(
        user_id="user_admin_afkir",
        email="admin@rsafkir.id",
        hospital_id=hospital_id,
        hospital_name="RS Test Afkir",
        hospital_code="RS_TEST_AFKIR",
        role="admin",
        access_token="tok_afkir_3",
        refresh_token="ref_afkir_3",
        token_expires_in=3600,
    )

    app.dependency_overrides[require_active_session] = lambda: session
    client = TestClient(app)

    try:
        res = client.post("/api/master/linen/decommission", json={
            "epc_list": ["EPC_AFKIR_002"],
            "alasan": "Lapuk / Habis Masa Pakai",
            "petugas": "Siti",
            "action": "delete"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "delete"

        db = SessionLocal()
        # Linen harus terhapus fisik dari tabel
        l2 = db.query(Linen).filter(Linen.epc == "EPC_AFKIR_002").first()
        assert l2 is None

        # Log transaksi tetap ada untuk audit RS
        trx = db.query(TransaksiLinen).filter(TransaksiLinen.kode_transaksi == data["kode_transaksi"]).first()
        assert trx is not None
        assert trx.jenis_transaksi == "afkir"
        db.close()
    finally:
        app.dependency_overrides.pop(require_active_session, None)

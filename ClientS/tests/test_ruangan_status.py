import os
import tempfile
import pytest
from starlette.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.models.ruangan import Ruangan
from app.models.rumah_sakit import RumahSakit
from app.models.linen import Linen
from app.routers.receiving_router import require_receiving_feature_enabled
from app.services.auth_dependencies import require_active_session
from app.routers.auth_router import get_default_session_store
from app.main import app


@pytest.fixture
def ruangan_test_env():
    """Environment terisolasi untuk pengujian aktif/nonaktif ruangan."""
    os.environ["DISABLE_BACKGROUND_SERVICES_FOR_TESTS"] = "1"
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Bersihkan & siapkan data RS
    db.query(Ruangan).delete()
    db.query(RumahSakit).delete()

    h1 = RumahSakit(id=101, kode="RS_TEST_A", nama="RS Test A")
    db.add(h1)
    db.commit()

    # Tambah 2 ruangan: 1 aktif, 1 nonaktif
    r1 = Ruangan(id=1, kode_ruangan="R-01", nama_ruangan="Ruang Mawar", is_active=True, hospital_id=101)
    r2 = Ruangan(id=2, kode_ruangan="R-02", nama_ruangan="Ruang Melati", is_active=False, hospital_id=101)
    db.add_all([r1, r2])
    db.commit()
    db.close()

    yield 101

    db = SessionLocal()
    db.query(Ruangan).delete()
    db.query(RumahSakit).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_ruangan_active_inactive_lifecycle(ruangan_test_env):
    hospital_id = ruangan_test_env
    store = get_default_session_store()
    session = await store.create_session(
        user_id="user_admin",
        email="admin@rstest.id",
        hospital_id=hospital_id,
        hospital_name="RS Test A",
        hospital_code="RS_TEST_A",
        role="admin",
        access_token="tok_123",
        refresh_token="ref_123",
        token_expires_in=3600,
    )

    app.dependency_overrides[require_active_session] = lambda: session
    try:
        client = TestClient(app)
        client.cookies.set("clients_session", session.session_id)
        headers = {"X-ClientS-Request": "1", "Origin": "http://127.0.0.1:8001"}

        # 1. Ambil semua ruangan (is_active tidak diset) -> harus mengembalikan 2 ruangan
        res_all = client.get("/api/master/ruangan", headers=headers)
        assert res_all.status_code == 200
        all_rooms = res_all.json()
        assert len(all_rooms) == 2

        # 2. Ambil hanya ruangan aktif (?is_active=true) -> hanya mengembalikan Ruang Mawar
        res_active = client.get("/api/master/ruangan?is_active=true", headers=headers)
        assert res_active.status_code == 200
        active_rooms = res_active.json()
        assert len(active_rooms) == 1
        assert active_rooms[0]["kode_ruangan"] == "R-01"

        # 3. Nonaktifkan Ruang Mawar (ID 1) via PATCH /status?is_active=false
        res_deact = client.patch("/api/master/ruangan/1/status?is_active=false", headers=headers)
        assert res_deact.status_code == 200
        assert res_deact.json()["is_active"] is False

        # 4. Ambil ruangan aktif lagi -> sekarang harus 0 (keduanya nonaktif)
        res_active_after = client.get("/api/master/ruangan?is_active=true", headers=headers)
        assert res_active_after.status_code == 200
        assert len(res_active_after.json()) == 0

        # 5. Aktifkan kembali Ruang Melati (ID 2) via PATCH /status?is_active=true
        res_act = client.patch("/api/master/ruangan/2/status?is_active=true", headers=headers)
        assert res_act.status_code == 200
        assert res_act.json()["is_active"] is True

        # 6. Ambil ruangan aktif -> sekarang harus 1 (Ruang Melati)
        res_active_melati = client.get("/api/master/ruangan?is_active=true", headers=headers)
        assert res_active_melati.status_code == 200
        assert len(res_active_melati.json()) == 1
        assert res_active_melati.json()[0]["kode_ruangan"] == "R-02"

        # 7. Update via PUT /ruangan/2 dengan is_active: false
        res_put = client.put("/api/master/ruangan/2", json={"is_active": False}, headers=headers)
        assert res_put.status_code == 200
        assert res_put.json()["is_active"] is False

        # 8. Cek lagi ruangan aktif -> 0
        res_none = client.get("/api/master/ruangan?is_active=true", headers=headers)
        assert len(res_none.json()) == 0
    finally:
        app.dependency_overrides.clear()

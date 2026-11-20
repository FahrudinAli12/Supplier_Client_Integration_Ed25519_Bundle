from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, init_db
from app.main import app
from app.models.detail_transaksi_linen import DetailTransaksiLinen
from app.models.linen import Linen
from app.models.riwayat_linen import RiwayatLinen
from app.models.ruangan import Ruangan
from app.models.transaksi_linen import TransaksiLinen
from app.services.auth_dependencies import require_active_session, require_master_data_editor


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    with SessionLocal() as db:
        db.query(DetailTransaksiLinen).delete()
        db.query(RiwayatLinen).delete()
        db.query(TransaksiLinen).delete()
        db.query(Linen).delete()
        db.query(Ruangan).delete()
        db.commit()
    yield


def test_complete_multi_tenant_isolation_between_hospitals():
    client = TestClient(app)

    # ─────────────────────────────────────────────────────────────
    # 1. AKUN AMINAH (HOSPITAL ID = 1)
    # ─────────────────────────────────────────────────────────────
    app.dependency_overrides[require_active_session] = lambda: {
        "user_id": "usr-aminah",
        "email": "admin@aminah.id",
        "hospital_id": 1,
        "role": "admin",
    }
    app.dependency_overrides[require_master_data_editor] = lambda: {
        "user_id": "usr-aminah",
        "email": "admin@aminah.id",
        "hospital_id": 1,
        "role": "admin",
    }

    # Buat ruangan di Aminah
    r_res = client.post("/api/master/ruangan", json={
        "kode_ruangan": "R-AMN-01",
        "nama_ruangan": "Ruang Melati Aminah",
        "keterangan": "Ruang Aminah",
    })
    assert r_res.status_code == 201

    # Buat linen di Aminah
    l_res = client.post("/api/master/linen", json={
        "epc": "EPC-AMN-1001",
        "kategori": "Sprei",
        "nama_linen": "Sprei Aminah",
        "lokasi": "Ruang Melati Aminah",
        "total_cuci": 0,
        "status": "tersedia",
    })
    assert l_res.status_code == 201
    amn_linen_id = l_res.json()["id"]

    # Buat transaksi di Aminah
    t_res = client.post("/api/transaksi/batch", json={
        "jenis_transaksi": "keluar",
        "kode_transaksi": "TRX-AMN-BATCH-01",
        "petugas": "Petugas Aminah",
        "ruangan": "Ruang Melati Aminah",
        "catatan": "Distribusi Aminah",
        "epc_list": ["EPC-AMN-1001"],
    })
    assert t_res.status_code == 201
    amn_trx_id = t_res.json()["id"]

    # Cek bahwa Aminah melihat datanya sendiri
    amn_linens = client.get("/api/master/linen").json()
    assert len(amn_linens) == 1
    assert amn_linens[0]["epc"] == "EPC-AMN-1001"

    amn_rooms = client.get("/api/master/ruangan").json()
    assert len(amn_rooms) == 1
    assert amn_rooms[0]["kode_ruangan"] == "R-AMN-01"

    amn_trxs = client.get("/api/transaksi").json()
    assert len(amn_trxs) == 1
    assert amn_trxs[0]["kode_transaksi"] == "TRX-AMN-BATCH-01"

    amn_riwayat = client.get("/api/transaksi/riwayat").json()
    assert len(amn_riwayat) == 1

    # ─────────────────────────────────────────────────────────────
    # 2. AKUN DR SOETOMO (HOSPITAL ID = 11)
    # ─────────────────────────────────────────────────────────────
    app.dependency_overrides[require_active_session] = lambda: {
        "user_id": "usr-soetomo",
        "email": "admin@drsoetomo.id",
        "hospital_id": 11,
        "role": "admin",
    }
    app.dependency_overrides[require_master_data_editor] = lambda: {
        "user_id": "usr-soetomo",
        "email": "admin@drsoetomo.id",
        "hospital_id": 11,
        "role": "admin",
    }

    # Dr Soetomo TIDAK boleh melihat linen milik Aminah
    st_linens = client.get("/api/master/linen").json()
    assert len(st_linens) == 0, f"Expected 0 linens for Dr Soetomo, got {st_linens}"

    # Dr Soetomo TIDAK boleh melihat ruangan milik Aminah
    st_rooms = client.get("/api/master/ruangan").json()
    assert len(st_rooms) == 0, f"Expected 0 rooms for Dr Soetomo, got {st_rooms}"

    # Dr Soetomo TIDAK boleh melihat transaksi milik Aminah
    st_trxs = client.get("/api/transaksi").json()
    assert len(st_trxs) == 0, f"Expected 0 transactions for Dr Soetomo, got {st_trxs}"

    # Dr Soetomo TIDAK boleh melihat riwayat milik Aminah
    st_riwayat = client.get("/api/transaksi/riwayat").json()
    assert len(st_riwayat) == 0, f"Expected 0 riwayat for Dr Soetomo, got {st_riwayat}"

    # Dr Soetomo TIDAK boleh mengakses detail transaksi milik Aminah
    st_trx_detail_res = client.get(f"/api/transaksi/{amn_trx_id}/detail")
    assert st_trx_detail_res.status_code == 404

    # Dr Soetomo TIDAK boleh memproses batch transaksi menggunakan linen milik Aminah
    st_batch_invalid = client.post("/api/transaksi/batch", json={
        "jenis_transaksi": "masuk",
        "petugas": "Petugas Soetomo",
        "ruangan": "Laundry Soetomo",
        "epc_list": ["EPC-AMN-1001"],
    })
    assert st_batch_invalid.status_code == 400

    # Sekarang Dr Soetomo membuat data miliknya sendiri
    st_r_res = client.post("/api/master/ruangan", json={
        "kode_ruangan": "R-STM-UGD",
        "nama_ruangan": "UGD Dr Soetomo",
        "keterangan": "UGD Sentral",
    })
    assert st_r_res.status_code == 201

    st_l_res = client.post("/api/master/linen", json={
        "epc": "EPC-STM-2001",
        "kategori": "Selimut",
        "nama_linen": "Selimut Soetomo",
        "lokasi": "UGD Dr Soetomo",
        "total_cuci": 0,
        "status": "tersedia",
    })
    assert st_l_res.status_code == 201

    st_t_res = client.post("/api/transaksi/batch", json={
        "jenis_transaksi": "keluar",
        "kode_transaksi": "TRX-STM-BATCH-01",
        "petugas": "Petugas Soetomo",
        "ruangan": "UGD Dr Soetomo",
        "catatan": "Distribusi Soetomo",
        "epc_list": ["EPC-STM-2001"],
    })
    assert st_t_res.status_code == 201

    # Verifikasi Dr Soetomo HANYA melihat datanya sendiri
    st_linens_now = client.get("/api/master/linen").json()
    assert len(st_linens_now) == 1
    assert st_linens_now[0]["epc"] == "EPC-STM-2001"

    st_rooms_now = client.get("/api/master/ruangan").json()
    assert len(st_rooms_now) == 1
    assert st_rooms_now[0]["kode_ruangan"] == "R-STM-UGD"

    st_trxs_now = client.get("/api/transaksi").json()
    assert len(st_trxs_now) == 1
    assert st_trxs_now[0]["kode_transaksi"] == "TRX-STM-BATCH-01"

    # ─────────────────────────────────────────────────────────────
    # 3. KEMBALI KE AKUN AMINAH (HOSPITAL ID = 1)
    # ─────────────────────────────────────────────────────────────
    app.dependency_overrides[require_active_session] = lambda: {
        "user_id": "usr-aminah",
        "email": "admin@aminah.id",
        "hospital_id": 1,
        "role": "admin",
    }
    app.dependency_overrides[require_master_data_editor] = lambda: {
        "user_id": "usr-aminah",
        "email": "admin@aminah.id",
        "hospital_id": 1,
        "role": "admin",
    }

    # Aminah TIDAK boleh melihat linen Dr Soetomo
    amn_linens_final = client.get("/api/master/linen").json()
    assert len(amn_linens_final) == 1
    assert amn_linens_final[0]["epc"] == "EPC-AMN-1001"

    # Aminah TIDAK boleh melihat ruangan Dr Soetomo
    amn_rooms_final = client.get("/api/master/ruangan").json()
    assert len(amn_rooms_final) == 1
    assert amn_rooms_final[0]["kode_ruangan"] == "R-AMN-01"

    # Aminah TIDAK boleh melihat transaksi Dr Soetomo
    amn_trxs_final = client.get("/api/transaksi").json()
    assert len(amn_trxs_final) == 1
    assert amn_trxs_final[0]["kode_transaksi"] == "TRX-AMN-BATCH-01"


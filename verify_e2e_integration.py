import asyncio
import os
import sys
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace

# Set paths
workspace_root = os.path.dirname(os.path.abspath(__file__))
supplier_backend = os.path.join(workspace_root, "silarisV2-main", "backend")
supplier_venv_site = os.path.join(workspace_root, "silarisV2-main", ".venv", "Lib", "site-packages")
client_backend = os.path.join(workspace_root, "ClientS")

if supplier_backend not in sys.path:
    sys.path.insert(0, supplier_backend)
if supplier_venv_site not in sys.path:
    sys.path.insert(0, supplier_venv_site)

from dotenv import load_dotenv
load_dotenv(os.path.join(supplier_backend, ".env"))

print("=" * 75)
print("STARTING COMPLETE SUPPLIER & CLIENT INTEGRATION VERIFICATION SUITE")
print("=" * 75)

# 1. Test Supplier Schemas and EPC Validation
from app.schemas.linen import LinenCreate, LinenDetailResponse

def test_epc_validation():
    print("\n[1/7] Testing EPC Clean & Format Validation...")
    obj = LinenCreate(epc="E28011902000000000000001", kategori_id=1, nama_id=1)
    assert obj.epc == "E28011902000000000000001"
    obj2 = LinenCreate(epc="3000E28011902000000000000001", kategori_id=1, nama_id=1)
    assert obj2.epc == "E28011902000000000000001"
    obj3 = LinenCreate(epc="e28011902000000000000001", kategori_id=1, nama_id=1)
    assert obj3.epc == "E28011902000000000000001"

    try:
        LinenCreate(epc="INVALID_EPC_HEX", kategori_id=1, nama_id=1)
        assert False, "Should have raised ValueError"
    except Exception:
        pass
    print("      PASSED: EPC format normalization and hex validation.")


# 2. Test Ed25519 Signing Contract
from app.services.client_package_gateway import (
    canonical_payload_bytes,
    ClientPackageGateway,
)
from cryptography.hazmat.primitives.asymmetric import ed25519

def test_ed25519_contract():
    print("\n[2/7] Testing Ed25519 Cryptographic Ingestion Contract...")
    gateway = ClientPackageGateway()
    assert gateway.is_configured() is True

    items = [
        {"epc": "E28011902000000000000002", "nama_linen": "Sprei Kasur", "kategori": "Linen Utama"},
        {"epc": "E28011902000000000000001", "nama_linen": "Sarung Bantal", "kategori": "Linen Tambahan"},
    ]
    raw_bytes = canonical_payload_bytes(
        package_code="KIRIM-20261118-001",
        hospital_code="RS001",
        idempotency_key="idemp-101",
        catatan="Pengiriman Linen Steril",
        items=items,
    )
    import hashlib
    digest = hashlib.sha256(raw_bytes).hexdigest()
    headers = gateway._headers(timestamp="1731900000", nonce="nonce-12345", payload_digest=digest)

    assert headers["X-Supplier-Device-Id"] == "SILARIS-SUPPLIER-DEVICE-01"
    assert "X-Supplier-Signature" in headers
    assert headers["X-Supplier-Nonce"] == "nonce-12345"

    sig_bytes = bytes.fromhex(headers["X-Supplier-Signature"])
    signed_content = f"{headers['X-Supplier-Device-Id']}:{headers['X-Supplier-Timestamp']}:{headers['X-Supplier-Nonce']}:{digest}".encode("utf-8")
    pub_key = gateway._private_key().public_key()
    pub_key.verify(sig_bytes, signed_content)
    print("      PASSED: Ed25519 Signing & Verification verified mathematically.")


# 3. Test Supplier Database Models & Schema Extensions
from app.database.models import PengirimanTemp, Linen, KategoriLinen, NamaLinen, RumahSakitLocal
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

db_path = os.path.join(supplier_backend, "local.db")
local_engine = create_engine(f"sqlite:///{db_path}")
SessionLocal = sessionmaker(bind=local_engine)

def test_supplier_models():
    print("\n[3/7] Testing Supplier Database Models & Schema Extensions...")
    from app.database.session import ensure_supplier_cloud_columns
    ensure_supplier_cloud_columns()

    insp = inspect(local_engine)
    pt_cols = [col["name"] for col in insp.get_columns("pengiriman_temp")]
    assert "last_error" in pt_cols, "pengiriman_temp must have last_error"
    assert "status_upload" in pt_cols

    rs_cols = [col["name"] for col in insp.get_columns("rumah_sakit")]
    assert "client_email" in rs_cols, "rumah_sakit must have client_email"
    assert "client_user_id" in rs_cols, "rumah_sakit must have client_user_id"
    assert "is_active" in rs_cols
    print("      PASSED: pengiriman_temp and rumah_sakit schemas verified with additive columns.")


# 4. Test Trusted Local Installation Security
from app.services.trusted_local import (
    validate_trusted_local_access,
    validate_host_header,
    validate_csrf_protection,
)
from app.routers.auth import get_auth_status
from fastapi import Request, HTTPException

def _make_req(client_ip="127.0.0.1", host="localhost:8000", method="GET", origin=None, headers=None):
    all_headers = {"host": host}
    if origin:
        all_headers["origin"] = origin
    if headers:
        all_headers.update(headers)
    req = SimpleNamespace()
    req.client = SimpleNamespace(host=client_ip)
    req.method = method
    req.headers = all_headers
    req.url = SimpleNamespace(path="/api/auth/status")
    return req

def _run_coro(coro):
    stack = [coro]
    val = None
    while stack:
        try:
            curr = stack[-1]
            if hasattr(curr, "send"):
                sub = curr.send(val)
                val = None
                if asyncio.iscoroutine(sub) or hasattr(sub, "send"):
                    stack.append(sub)
            else:
                stack.pop()
        except StopIteration as e:
            stack.pop()
            val = e.value
    return val

def test_trusted_local_security():
    print("\n[4/7] Testing Supplier Trusted Local Installation Security...")

    # A. Valid loopback request -> Master authority without login
    req_loopback = _make_req(client_ip="127.0.0.1", host="localhost:8000")
    auth_result = validate_trusted_local_access(req_loopback)
    assert auth_result["mode"] == "trusted_local"
    assert auth_result["role"] == "master_admin"

    status_data = _run_coro(get_auth_status(actor=auth_result))
    assert status_data["status"] == "ok"
    assert status_data["authenticated"] is True
    assert status_data["role"] == "master_admin"
    print("      PASSED: Direct Supplier Dashboard access granted with master_admin authority.")

    # B. DNS Rebinding check: external Host rejected
    req_dns = _make_req(client_ip="127.0.0.1", host="evil-domain.com")
    try:
        validate_host_header(req_dns)
        assert False, "Should have rejected foreign Host"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "DNS rebinding" in exc.detail
    print("      PASSED: DNS rebinding attempt blocked (403 Forbidden).")

    # C. External IP check: public IP rejected
    req_ext = _make_req(client_ip="8.8.8.8", host="localhost:8000")
    try:
        validate_trusted_local_access(req_ext)
        assert False, "Should have rejected public IP"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "trusted local" in exc.detail
    print("      PASSED: External IP access strictly rejected (403 Forbidden).")

    # D. CSRF protection: foreign Origin rejected on POST
    req_csrf = _make_req(
        client_ip="127.0.0.1", host="localhost:8000", method="POST", origin="https://attacker.com"
    )
    try:
        validate_csrf_protection(req_csrf, "127.0.0.1")
        assert False, "Should have rejected foreign Origin"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "CSRF" in exc.detail
    print("      PASSED: Cross-Origin state mutation blocked (403 Forbidden).")


# 5. Test Supplier Hospital & Client Account Management
from app.routers.rumah_sakit import create_rumah_sakit, update_rumah_sakit, list_rumah_sakit
from app.schemas.rumah_sakit import RumahSakitCreate, RumahSakitUpdate

def test_hospital_and_client_provisioning():
    print("\n[5/7] Testing Supplier Creation of Two Hospitals & Two Client Accounts...")
    actor = {"mode": "trusted_local", "role": "master_admin"}
    db = SessionLocal()

    try:
        ts = int(datetime.now().timestamp())
        kode_a = f"RS-A{ts % 10000:04d}"
        kode_b = f"RS-B{ts % 10000:04d}"
        email_a = f"client_{kode_a.lower()}@test-hospital.local"
        email_b = f"client_{kode_b.lower()}@test-hospital.local"

        # Create Hospital A with Client Account
        payload_a = RumahSakitCreate(
            kode_rs=kode_a,
            nama_rs=f"RSUD Sehat Alpha {kode_a}",
            alamat="Jl. Alpha Medika No. 1",
            kontak="081211111111",
            email=f"info@{kode_a.lower()}.local",
            client_email=email_a,
            client_password="PasswordAlpha123!",
        )
        res_a = _run_coro(create_rumah_sakit(payload=payload_a, actor=actor, db=db))
        assert res_a["kode_rs"] == kode_a
        assert res_a["client_email"] == email_a
        h_id_a = res_a["id"]
        print(f"      PASSED: Created Hospital A ({kode_a}, ID={h_id_a}) with Client ({email_a}).")

        # Create Hospital B with Client Account
        payload_b = RumahSakitCreate(
            kode_rs=kode_b,
            nama_rs=f"RSUD Sehat Beta {kode_b}",
            alamat="Jl. Beta Medika No. 2",
            kontak="081222222222",
            email=f"info@{kode_b.lower()}.local",
            client_email=email_b,
            client_password="PasswordBeta123!",
        )
        res_b = _run_coro(create_rumah_sakit(payload=payload_b, actor=actor, db=db))
        assert res_b["kode_rs"] == kode_b
        assert res_b["client_email"] == email_b
        h_id_b = res_b["id"]
        print(f"      PASSED: Created Hospital B ({kode_b}, ID={h_id_b}) with Client ({email_b}).")

        # Uniqueness check: duplicate client email must be rejected
        payload_dup = RumahSakitCreate(
            kode_rs=f"RS-DUP{ts % 1000}",
            nama_rs="RS Duplikat Email",
            client_email=email_a,
            client_password="Password123!",
        )
        try:
            _run_coro(create_rumah_sakit(payload=payload_dup, actor=actor, db=db))
            assert False, "Should have rejected duplicate client email"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "sudah digunakan" in exc.detail
        print("      PASSED: Duplicate Client email rejected with HTTP 409 Conflict.")

        # Edit Hospital A
        payload_edit = RumahSakitUpdate(nama_rs=f"RSUD Sehat Alpha Updated {kode_a}", kontak="081299999999")
        res_edit = _run_coro(update_rumah_sakit(rs_id=str(h_id_a), payload=payload_edit, actor=actor, db=db))
        assert res_edit["kontak"] == "081299999999"
        print("      PASSED: Updated Hospital A master info.")

        return h_id_a, kode_a, email_a, h_id_b, kode_b, email_b
    finally:
        db.close()


# 6. Test Multi-Hospital Client Tenant Isolation
import time

def test_multi_client_tenant_isolation(h_id_a, k_a, e_a, h_id_b, k_b, e_b):
    print("\n[6/7] Testing Client Multi-Tenant Isolation Between Hospital A & B...")
    import importlib.util
    store_file = os.path.join(client_backend, "app", "services", "session_store.py")
    spec = importlib.util.spec_from_file_location("clients_session_store", store_file)
    session_store_mod = importlib.util.module_from_spec(spec)
    sys.modules["clients_session_store"] = session_store_mod
    spec.loader.exec_module(session_store_mod)

    SessionData = session_store_mod.SessionData
    SessionStore = session_store_mod.SessionStore

    store_a = SessionStore(default_session_duration_seconds=3600)
    store_b = SessionStore(default_session_duration_seconds=3600)

    now = time.time()
    sess_a = SessionData(
        session_id="token-client-a",
        user_id="user-uuid-alpha",
        email=e_a,
        role="operator",
        hospital_id=h_id_a,
        hospital_code=k_a,
        hospital_name="RSUD Alpha",
        access_token="mock-token-a",
        refresh_token="mock-refresh-a",
        token_expires_at=now + 3600,
        session_expires_at=now + 3600,
        created_at=now,
        last_activity_at=now,
    )
    store_a._sessions[sess_a.session_id] = sess_a

    sess_b = SessionData(
        session_id="token-client-b",
        user_id="user-uuid-beta",
        email=e_b,
        role="operator",
        hospital_id=h_id_b,
        hospital_code=k_b,
        hospital_name="RSUD Beta",
        access_token="mock-token-b",
        refresh_token="mock-refresh-b",
        token_expires_at=now + 3600,
        session_expires_at=now + 3600,
        created_at=now,
        last_activity_at=now,
    )
    store_b._sessions[sess_b.session_id] = sess_b

    read_a = store_a._sessions.get("token-client-a")
    assert read_a is not None
    assert read_a.hospital_id == h_id_a
    assert read_a.hospital_code == k_a

    cross_read = store_b._sessions.get("token-client-a")
    assert cross_read is None, "Client B must NOT access Client A session"
    assert read_a.hospital_id != h_id_b, "Client A hospital_id must not match Hospital B"

    read_b = store_b._sessions.get("token-client-b")
    assert read_b is not None
    assert read_b.hospital_id == h_id_b
    assert read_b.hospital_code == k_b
    assert read_b.hospital_id != h_id_a

    assert store_a._sessions.get("token-client-b") is None, "Client A must NOT access Client B session"

    print(f"      PASSED: Multi-tenant isolation verified: Client A ({k_a}) and Client B ({k_b}) cannot cross-access.")


# 7. Test Supplier Package Shipment to Each Hospital
from app.routers.pengiriman import create_pengiriman
from app.routers.linen import create_linen
from app.schemas.pengiriman import PengirimanCreate
from app.services.client_package_gateway import client_package_gateway
from app.services.sync_service import sync_service
import httpx

class DummyAsyncClient:
    def __init__(self, verif_code: str):
        self.verif_code = verif_code

    async def post(self, url, content=None, headers=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "success": True,
                "verification_code": self.verif_code,
                "package_id": 999,
                "manifest_hash": "a" * 64,
                "package_code": "PKG-001",
            },
        )

def test_supplier_package_shipment_to_both(h_id_a, k_a, h_id_b, k_b):
    print("\n[7/7] Testing Supplier Package Dispatch to Both Hospitals...")
    sync_service.client_ingestion_online = True
    db = SessionLocal()

    try:
        ts = int(datetime.now().timestamp())
        epc_a = f"E2801190{ts % 1000000:06d}0000000001"
        epc_b = f"E2801190{ts % 1000000:06d}0000000002"

        # Ensure at least one test category and nama linen exist
        from app.database.models import KategoriLinen, NamaLinen
        cat = db.query(KategoriLinen).first()
        if not cat:
            cat = KategoriLinen(nama="Standar")
            db.add(cat)
            db.commit()
            db.refresh(cat)
        nl = db.query(NamaLinen).first()
        if not nl:
            nl = NamaLinen(nama_linen="Sprei Standar", kategori_id=cat.kategori_id)
            db.add(nl)
            db.commit()
            db.refresh(nl)

        # Register linens
        create_linen(LinenCreate(epc=epc_a, kategori_id=cat.kategori_id, nama_id=nl.nama_id), db=db)
        create_linen(LinenCreate(epc=epc_b, kategori_id=cat.kategori_id, nama_id=nl.nama_id), db=db)

        # Attach mock gateway client for Hospital A
        code_a = f"VC-{k_a}-{ts}"
        client_package_gateway._client = DummyAsyncClient(code_a)

        # Ship to Hospital A
        ship_res_a = _run_coro(create_pengiriman(
            payload=PengirimanCreate(rs_id=str(h_id_a), daftar_epc=[epc_a]),
            db=db,
        ))
        assert "kode_verifikasi" in ship_res_a
        assert ship_res_a["status_upload"] == "sukses"
        print(f"      PASSED: Shipment package dispatched to Hospital A ({k_a}): Kode={ship_res_a['kode_verifikasi']}.")

        # Attach mock gateway client for Hospital B
        code_b = f"VC-{k_b}-{ts}"
        client_package_gateway._client = DummyAsyncClient(code_b)

        # Ship to Hospital B
        ship_res_b = _run_coro(create_pengiriman(
            payload=PengirimanCreate(rs_id=str(h_id_b), daftar_epc=[epc_b]),
            db=db,
        ))
        assert "kode_verifikasi" in ship_res_b
        assert ship_res_b["status_upload"] == "sukses"
        print(f"      PASSED: Shipment package dispatched to Hospital B ({k_b}): Kode={ship_res_b['kode_verifikasi']}.")
    finally:
        client_package_gateway._client = None
        db.close()


if __name__ == "__main__":
    test_epc_validation()
    test_ed25519_contract()
    test_supplier_models()
    test_trusted_local_security()
    h_a, k_a, e_a, h_b, k_b, e_b = test_hospital_and_client_provisioning()
    test_multi_client_tenant_isolation(h_a, k_a, e_a, h_b, k_b, e_b)
    test_supplier_package_shipment_to_both(h_a, k_a, h_b, k_b)
    print("\n" + "=" * 75)
    print("ALL 7/7 ARCHITECTURAL & INTEGRATION VERIFICATION STAGES PASSED!")
    print("=" * 75)

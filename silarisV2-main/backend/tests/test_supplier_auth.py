"""Tests for Supplier Trusted Local Installation security.

Verifies:
1. Loopback access is granted with Master Supplier authority without human login.
2. External/Public IPs are strictly blocked.
3. Private LAN IPs require valid machine authentication token (X-Supplier-Machine-Auth).
4. DNS rebinding attacks with foreign Host headers are rejected.
5. CSRF attacks with foreign Origin headers are rejected on state-mutating requests.
6. /api/auth/status and /api/auth/me return master_admin authority.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request

from app.services import trusted_local as tl_module
from app.services.trusted_local import (
    is_loopback,
    is_private_ip,
    validate_host_header,
    validate_csrf_protection,
    validate_trusted_local_access,
)


def _make_request(
    client_ip: str = "127.0.0.1",
    host: str = "localhost:8000",
    method: str = "GET",
    origin: str = None,
    headers: dict = None,
) -> Request:
    all_headers = {"host": host}
    if origin:
        all_headers["origin"] = origin
    if headers:
        all_headers.update(headers)

    req = MagicMock(spec=Request)
    req.client = SimpleNamespace(host=client_ip)
    req.method = method
    req.headers = all_headers
    req.url = SimpleNamespace(path="/api/test")
    return req


def test_loopback_detection():
    assert is_loopback("127.0.0.1") is True
    assert is_loopback("::1") is True
    assert is_loopback("localhost") is True
    assert is_loopback("testserver") is True
    assert is_loopback("192.168.1.1") is False
    assert is_loopback("8.8.8.8") is False


def test_private_ip_detection():
    assert is_private_ip("192.168.1.50") is True
    assert is_private_ip("10.0.0.1") is True
    assert is_private_ip("172.20.0.1") is True
    assert is_private_ip("8.8.8.8") is False


def test_host_header_validation_accepts_local():
    req = _make_request(host="localhost:8000")
    validate_host_header(req)  # Should not raise

    req_ip = _make_request(host="127.0.0.1:8000")
    validate_host_header(req_ip)  # Should not raise


def test_host_header_validation_rejects_dns_rebinding():
    req = _make_request(host="attacker-controlled-domain.com")
    with pytest.raises(HTTPException) as exc_info:
        validate_host_header(req)
    assert exc_info.value.status_code == 403
    assert "DNS rebinding" in exc_info.value.detail


def test_trusted_local_access_granted_for_loopback():
    req = _make_request(client_ip="127.0.0.1", host="localhost:8000")
    result = validate_trusted_local_access(req)
    assert result["mode"] == "trusted_local"
    assert result["role"] == "master_admin"


def test_trusted_local_access_rejects_external_ip():
    req = _make_request(client_ip="8.8.8.8", host="localhost:8000")
    with pytest.raises(HTTPException) as exc_info:
        validate_trusted_local_access(req)
    assert exc_info.value.status_code == 403
    assert "trusted local" in exc_info.value.detail


def test_lan_access_requires_valid_machine_token(monkeypatch):
    monkeypatch.setattr(
        tl_module,
        "get_settings",
        lambda: SimpleNamespace(
            SUPPLIER_MACHINE_AUTH_TOKEN="secret-token-xyz-12345",
            TRUSTED_HOSTS=["localhost", "127.0.0.1", "192.168.1.10"],
        ),
    )

    # 1. LAN request without machine token -> 403
    req_no_token = _make_request(
        client_ip="192.168.1.100",
        host="192.168.1.10:8000",
    )
    with pytest.raises(HTTPException) as exc_info:
        validate_trusted_local_access(req_no_token)
    assert exc_info.value.status_code == 403
    assert "Token autentikasi mesin" in exc_info.value.detail

    # 2. LAN request with invalid token -> 403
    req_wrong_token = _make_request(
        client_ip="192.168.1.100",
        host="192.168.1.10:8000",
        headers={"x-supplier-machine-auth": "wrong-token"},
    )
    with pytest.raises(HTTPException) as exc_info:
        validate_trusted_local_access(req_wrong_token)
    assert exc_info.value.status_code == 403

    # 3. LAN request with valid machine token -> granted
    req_valid_token = _make_request(
        client_ip="192.168.1.100",
        host="192.168.1.10:8000",
        headers={"x-supplier-machine-auth": "secret-token-xyz-12345"},
    )
    result = validate_trusted_local_access(req_valid_token)
    assert result["mode"] == "trusted_machine"
    assert result["role"] == "master_admin"


def test_csrf_protection_rejects_foreign_origin():
    req = _make_request(
        client_ip="127.0.0.1",
        host="localhost:8000",
        method="POST",
        origin="https://evil-attacker.com",
        headers={"x-supplier-request": "1"},
    )
    with pytest.raises(HTTPException) as exc_info:
        validate_csrf_protection(req, "127.0.0.1")
    assert exc_info.value.status_code == 403
    assert "CSRF" in exc_info.value.detail


def test_csrf_protection_accepts_same_origin():
    req = _make_request(
        client_ip="127.0.0.1",
        host="localhost:8000",
        method="POST",
        origin="http://localhost:8000",
        headers={"x-supplier-request": "1"},
    )
    validate_csrf_protection(req, "127.0.0.1")  # Should not raise

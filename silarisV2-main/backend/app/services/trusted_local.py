"""Trusted Local Installation security service.

Enforces trusted local machine security:
1. Host / IP restriction: Only loopback addresses (127.0.0.1, ::1, localhost, testserver)
   or private LAN clients with valid machine token (X-Supplier-Machine-Auth) are allowed.
   Public/Internet IPs are strictly blocked.
2. DNS Rebinding protection: Validates the Host header against trusted local hosts.
3. CSRF protection: Validates Origin and Referer headers for mutating requests (POST, PUT, DELETE, PATCH).
4. Defense-in-depth: Requires X-Supplier-Request header for state changes.
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
from urllib.parse import urlparse
from typing import Optional

from fastapi import HTTPException, Request, status

from app.config import get_settings

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver", "testclient"}


def is_loopback(host: str) -> bool:
    """Check if host string is a loopback address."""
    clean = (host or "").strip().lower()
    if clean in LOOPBACK_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(clean)
        return ip.is_loopback
    except ValueError:
        return False


def is_private_ip(host: str) -> bool:
    """Check if host string is a private/local network address."""
    try:
        ip = ipaddress.ip_address((host or "").strip())
        return ip.is_private
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, ignoring untrusted forwarded headers unless loopback."""
    if request.client and request.client.host:
        return request.client.host.strip()
    return ""


def validate_host_header(request: Request) -> None:
    """Validate Host header against DNS rebinding attacks."""
    host_header = request.headers.get("host", "").strip()
    if not host_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header Host tidak ditemukan.",
        )

    # Strip port if present: localhost:8000 -> localhost
    hostname = host_header.split(":")[0].strip().lower()
    if hostname.startswith("[") and "]" in hostname:
        hostname = hostname[1:hostname.index("]")].lower()

    settings = get_settings()
    allowed_hosts = {h.lower() for h in settings.TRUSTED_HOSTS} | LOOPBACK_HOSTS

    if hostname not in allowed_hosts and not is_loopback(hostname):
        logger.warning("DNS rebinding attempt blocked for host: %s", host_header)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Host permintaan tidak diizinkan (DNS rebinding protection).",
        )


def validate_csrf_protection(request: Request, client_ip: str) -> None:
    """Validate Origin/Referer and request headers for state-mutating operations."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return

    # Check Origin header if present
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if origin:
        parsed = urlparse(origin)
        origin_host = (parsed.hostname or "").lower()
        settings = get_settings()
        allowed_hosts = {h.lower() for h in settings.TRUSTED_HOSTS} | LOOPBACK_HOSTS
        if origin_host not in allowed_hosts and not is_loopback(origin_host):
            logger.warning("CSRF origin validation failed: %s (host: %s)", origin, host)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Origin permintaan tidak diizinkan (CSRF protection).",
            )

    # Check Referer if Origin is not present
    elif request.headers.get("referer"):
        referer = request.headers.get("referer")
        parsed = urlparse(referer)
        referer_host = (parsed.hostname or "").lower()
        settings = get_settings()
        allowed_hosts = {h.lower() for h in settings.TRUSTED_HOSTS} | LOOPBACK_HOSTS
        if referer_host not in allowed_hosts and not is_loopback(referer_host):
            logger.warning("CSRF referer validation failed: %s", referer)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Referer permintaan tidak diizinkan (CSRF protection).",
            )

    # Validate X-Supplier-Request header for state-mutating browser requests
    # Machine-to-machine requests with valid machine auth token are exempt
    machine_token = request.headers.get("x-supplier-machine-auth", "").strip()
    settings = get_settings()
    is_valid_machine = bool(
        settings.SUPPLIER_MACHINE_AUTH_TOKEN
        and machine_token
        and hmac.compare_digest(machine_token, settings.SUPPLIER_MACHINE_AUTH_TOKEN)
    )

    if not is_valid_machine and request.headers.get("x-supplier-request") != "1":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Header keamanan permintaan X-Supplier-Request wajib disertakan.",
        )


def validate_trusted_local_access(request: Request) -> dict[str, str]:
    """Validate that the request arrives from a trusted local installation or authorized machine."""
    # 1. DNS rebinding check
    validate_host_header(request)

    # 2. Client host verification
    client_ip = get_client_ip(request)
    settings = get_settings()

    # Loopback is always trusted for local master application
    if is_loopback(client_ip):
        validate_csrf_protection(request, client_ip)
        return {
            "mode": "trusted_local",
            "role": "master_admin",
            "client_ip": client_ip,
            "access_type": "loopback",
        }

    # LAN access requires machine auth token
    if is_private_ip(client_ip):
        machine_token = request.headers.get("x-supplier-machine-auth", "").strip()
        configured_token = settings.SUPPLIER_MACHINE_AUTH_TOKEN.strip()

        if not configured_token or not machine_token or not hmac.compare_digest(machine_token, configured_token):
            logger.warning("LAN request from %s rejected: missing or invalid machine auth token", client_ip)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses jaringan lokal ditolak: Token autentikasi mesin (X-Supplier-Machine-Auth) tidak valid.",
            )

        validate_csrf_protection(request, client_ip)
        return {
            "mode": "trusted_machine",
            "role": "master_admin",
            "client_ip": client_ip,
            "access_type": "lan_authorized",
        }

    # Public/Internet IP access is strictly prohibited
    logger.warning("Untrusted external request rejected from IP: %s", client_ip)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Akses ditolak: API Supplier hanya dapat diakses melalui instalasi lokal terpercaya (trusted local).",
    )


async def require_trusted_supplier_access(request: Request) -> dict[str, str]:
    """FastAPI dependency: ensures caller has Master Supplier authority via trusted local access."""
    return validate_trusted_local_access(request)

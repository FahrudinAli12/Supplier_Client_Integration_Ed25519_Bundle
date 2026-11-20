"""Supplier Authentication & Security Router.

Under the Trusted Local Installation architecture:
- Supplier operates as Master Application without requiring human email/password login.
- Access is secured at the local machine layer (loopback / trusted host / LAN machine auth).
- Endpoints return master_admin authority status.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.services.trusted_local import require_trusted_supplier_access

router = APIRouter(prefix="/api/auth", tags=["Supplier Auth"])


@router.get("/status")
@router.get("/me")
async def get_auth_status(
    actor: dict[str, str] = Depends(require_trusted_supplier_access),
):
    """Return Master Supplier authority status for trusted local installation."""
    return {
        "status": "ok",
        "mode": actor.get("mode", "trusted_local"),
        "authenticated": True,
        "user": {
            "id": "supplier-master",
            "email": "master@supplier.local",
            "role": "master_admin",
        },
        "role": "master_admin",
        "client_ip": actor.get("client_ip", "127.0.0.1"),
    }


@router.post("/login")
async def login_deprecated(
    actor: dict[str, str] = Depends(require_trusted_supplier_access),
):
    """Backward-compatible endpoint: Supplier uses trusted local installation, human login not required."""
    return {
        "status": "ok",
        "message": "Supplier Master Application aktif melalui instalasi lokal terpercaya (tanpa login pengguna).",
        "user": {
            "id": "supplier-master",
            "email": "master@supplier.local",
            "role": "master_admin",
        },
        "role": "master_admin",
    }


@router.post("/logout")
async def logout_deprecated(
    actor: dict[str, str] = Depends(require_trusted_supplier_access),
):
    """Backward-compatible endpoint: no session cookie to invalidate in trusted local installation."""
    return {
        "status": "ok",
        "message": "Instalasi lokal terpercaya tetap aktif.",
    }


# Backwards compatibility aliases for any internal router imports
get_supplier_actor = require_trusted_supplier_access
require_supplier_admin = require_trusted_supplier_access

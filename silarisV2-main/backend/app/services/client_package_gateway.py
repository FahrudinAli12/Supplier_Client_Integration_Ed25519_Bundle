"""Ed25519-authenticated Supplier ingestion gateway to the shared Supabase project.

The private key stays on the Supplier backend. The deployed Edge Function
verifies signatures, timestamp skew, device-key validity and one-time nonces,
then calls public.ingest_supplier_package(...). This path does not use user JWTs
or a service-role key in the Supplier application.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
import uuid
from typing import Any, Optional

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import get_settings
from app.services.supabase_config import resolve_project_url, resolve_publishable_key

logger = logging.getLogger(__name__)
TRIM_CHARS = (
    " \t\n\r\v\f"
    "\u0085\u00A0\u1680\u180E"
    "\u2000\u2001\u2002\u2003\u2004"
    "\u2005\u2006\u2007\u2008\u2009\u200A"
    "\u200B\u200C\u200D"
    "\u2028\u2029\u202F\u205F\u3000\uFEFF"
)


def _clean_text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip(TRIM_CHARS)



def _normalize_items(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(items, list) or not items or len(items) > 5000:
        raise ValueError("Manifest harus berisi 1 sampai 5000 item.")

    normalized: list[dict[str, str]] = []
    seen_epcs: set[str] = set()

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item manifest ke-{index} bukan objek JSON.")

        # 1. Trim whitespace tanpa mengubah karakter.
        epc_raw = str(item.get("epc") or "").strip(TRIM_CHARS)

        # 2. Reject non-ASCII BEFORE uppercase.
        if any(ord(ch) > 127 for ch in epc_raw):
            raise ValueError(
                f"EPC item ke-{index} mengandung karakter non-ASCII."
            )

        # 3. ASCII uppercase.
        epc = epc_raw.upper()

        # 4. Legacy EPC prefix normalization.
        if len(epc) == 28 and epc.startswith("3000"):
            epc = epc[4:]

        # 5. Strict hexadecimal validation.
        if not re.fullmatch(r"[0-9A-F]{24}", epc):
            raise ValueError(
                f"EPC item ke-{index} harus menjadi 24 karakter hex setelah normalisasi."
            )

        # 6. Duplicate detection.
        if epc in seen_epcs:
            raise ValueError(f"EPC duplikat ditemukan: {epc}")

        seen_epcs.add(epc)

        normalized.append({
            "epc": epc,
            "kategori": _clean_text(item.get("kategori")),
            "nama_linen": _clean_text(item.get("nama_linen")),
        })

    # 7. Deterministic ordering.
    normalized.sort(key=lambda row: row["epc"])

    return normalized

def canonical_payload_bytes(
    *, package_code: str, hospital_code: str, idempotency_key: str,
    catatan: str, items: list[dict[str, str]],
) -> bytes:
    canonical = {
        "catatan": _clean_text(catatan),
        "hospital_code": _clean_text(hospital_code),
        "idempotency_key": _clean_text(idempotency_key),
        "items": items,
        "package_code": _clean_text(package_code),
    }
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ClientPackageGateway:
    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self.settings = get_settings()
        self._client = client

    @property
    def function_url(self) -> str:
        base = resolve_project_url(self.settings).strip().rstrip("/")
        return f"{base}/functions/v1/supplier-ingest" if base else ""

    def _private_key(self) -> Ed25519PrivateKey:
        raw = self.settings.CLIENT_SUPPLIER_PRIVATE_KEY_HEX.strip()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
            raise ValueError("CLIENT_SUPPLIER_PRIVATE_KEY_HEX harus berisi 64 karakter hex (32 byte).")
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))

    def is_configured(self) -> bool:
        try:
            self._private_key()
            return bool(
                self.function_url
                and resolve_publishable_key(self.settings)
                and self.settings.CLIENT_SUPPLIER_DEVICE_ID.strip()
            )
        except Exception:
            return False

    def _headers(self, timestamp: str, nonce: str, payload_digest: str) -> dict[str, str]:
        device_id = self.settings.CLIENT_SUPPLIER_DEVICE_ID.strip()
        canonical_message = f"{device_id}:{timestamp}:{nonce}:{payload_digest.lower()}".encode("utf-8")
        signature = self._private_key().sign(canonical_message).hex()
        return {
            "Content-Type": "application/json",
            "apikey": resolve_publishable_key(self.settings),
            "X-Supplier-Device-Id": device_id,
            "X-Supplier-Timestamp": timestamp,
            "X-Supplier-Nonce": nonce,
            "X-Supplier-Signature": signature,
        }

    async def health_check(self) -> bool:
        if not self.is_configured():
            return False
        headers = {"apikey": resolve_publishable_key(self.settings)}
        try:
            if self._client:
                response = await self._client.get(self.function_url, headers=headers, timeout=5.0)
            else:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(self.function_url, headers=headers)
            return response.status_code == 200
        except Exception as exc:
            logger.debug("Supplier ingestion health check failed: %s", exc)
            return False

    async def upload_package(
        self,
        *,
        hospital_code: str,
        package_code: str,
        items: list[dict[str, Any]],
        idempotency_key: str,
        catatan: str | None = None,
    ) -> Optional[dict[str, Any]]:
        if not self.is_configured():
            logger.error(
                "Gateway ingestion belum dikonfigurasi. Periksa SUPABASE_URL, "
                "SUPABASE_PUBLISHABLE_KEY, CLIENT_SUPPLIER_DEVICE_ID, dan private key Ed25519."
            )
            return None

        clean_hospital_code = _clean_text(hospital_code)
        clean_package_code = _clean_text(package_code).upper()
        clean_idempotency_key = _clean_text(idempotency_key)
        clean_catatan = _clean_text(catatan)
        if not clean_hospital_code or not clean_package_code or not clean_idempotency_key:
            logger.error("Kode RS, package_code, dan idempotency_key wajib diisi.")
            return None

        try:
            normalized_items = _normalize_items(items)
            digest_source = canonical_payload_bytes(
                package_code=clean_package_code,
                hospital_code=clean_hospital_code,
                idempotency_key=clean_idempotency_key,
                catatan=clean_catatan,
                items=normalized_items,
            )
            payload_digest = hashlib.sha256(digest_source).hexdigest()
            body = {
                "package_code": clean_package_code,
                "hospital_code": clean_hospital_code,
                "idempotency_key": clean_idempotency_key,
                "payload_digest": payload_digest,
                "catatan": clean_catatan,
                "items": normalized_items,
            }
            raw_body = json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            timestamp = str(int(time.time()))
            nonce = uuid.uuid4().hex
            headers = self._headers(timestamp, nonce, payload_digest)
        except Exception as exc:
            logger.error("Paket tidak dapat disiapkan untuk ingestion: %s", exc)
            return None

        try:
            if self._client:
                response = await self._client.post(
                    self.function_url, content=raw_body, headers=headers, timeout=20.0
                )
            else:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(self.function_url, content=raw_body, headers=headers)

            try:
                result = response.json()
            except Exception:
                result = {"message": response.text[:500]}

            if (
                response.status_code in (200, 201)
                and isinstance(result, dict)
                and result.get("success") is True
                and result.get("verification_code")
                and result.get("package_id") is not None
                and result.get("manifest_hash")
            ):
                logger.info(
                    "Paket %s berhasil masuk ke Supabase. cloud_package_id=%s status=%s",
                    clean_package_code, result.get("package_id"), result.get("status")
                )
                self.last_rejection_error = None
                return result

            err_msg = result.get("error") if isinstance(result, dict) else str(result)
            self.last_rejection_error = err_msg or f"HTTP {response.status_code}"
            logger.warning(
                "Supabase menolak paket %s (HTTP %s): %s",
                clean_package_code, response.status_code, result,
            )
            return None
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            self.last_rejection_error = f"Koneksi gagal: {exc}"
            logger.warning("Koneksi ingestion gagal untuk paket %s: %s", clean_package_code, exc)
            return None
        except Exception as exc:
            self.last_rejection_error = str(exc)
            logger.exception("Kesalahan ingestion paket %s: %s", clean_package_code, exc)
            return None


client_package_gateway = ClientPackageGateway()

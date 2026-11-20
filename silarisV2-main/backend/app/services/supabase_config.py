"""Resolve and validate the single Supabase project configuration."""
from __future__ import annotations

from urllib.parse import urlparse
from typing import Any


class SupabaseConfigurationError(RuntimeError):
    pass


def _clean(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def resolve_project_url(settings: Any) -> str:
    primary = _clean(getattr(settings, "SUPABASE_URL", ""))
    legacy = _clean(getattr(settings, "CLIENT_SUPABASE_URL", ""))

    if primary.endswith("your-project.supabase.co"):
        primary = ""

    if primary and legacy:
        primary_host = (urlparse(primary).hostname or "").lower()
        legacy_host = (urlparse(legacy).hostname or "").lower()
        if not primary_host or primary_host != legacy_host:
            raise SupabaseConfigurationError(
                "Arsitektur satu project aktif, tetapi SUPABASE_URL dan "
                "CLIENT_SUPABASE_URL masih menunjuk ke project berbeda. "
                "Samakan keduanya atau kosongkan CLIENT_SUPABASE_URL."
            )

    result = primary or legacy
    if not result:
        raise SupabaseConfigurationError("SUPABASE_URL belum dikonfigurasi.")
    parsed = urlparse(result)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SupabaseConfigurationError("SUPABASE_URL harus berupa URL HTTPS Supabase yang valid.")
    return result


def resolve_publishable_key(settings: Any) -> str:
    key = (
        _clean(getattr(settings, "SUPABASE_PUBLISHABLE_KEY", ""))
        or _clean(getattr(settings, "CLIENT_SUPABASE_PUBLISHABLE_KEY", ""))
        or _clean(getattr(settings, "SUPABASE_ANON_KEY", ""))
    )
    if not key or key.lower() in {"your-anon-key-here", "your-publishable-key-here", "changeme"}:
        raise SupabaseConfigurationError(
            "SUPABASE_PUBLISHABLE_KEY belum dikonfigurasi. Gunakan publishable key project tunggal."
        )
    if key.startswith("sb_secret_"):
        raise SupabaseConfigurationError("Secret key tidak boleh digunakan sebagai publishable key aplikasi.")
    return key

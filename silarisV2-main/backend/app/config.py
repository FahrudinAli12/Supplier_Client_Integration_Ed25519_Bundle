"""Application configuration for the single Supabase project architecture."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # One canonical Supabase project for Supplier and Client.
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    # Supabase Admin / Service Role Key (Backend only, never exposed to frontend)
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Trusted Local Installation Security
    SUPPLIER_MACHINE_AUTH_TOKEN: str = ""
    TRUSTED_HOSTS: list[str] = ["localhost", "127.0.0.1", "::1", "testserver"]

    # Deprecated compatibility fields. If set, these MUST point to the same project.
    SUPABASE_ANON_KEY: str = ""
    CLIENT_SUPABASE_URL: str = ""
    CLIENT_SUPABASE_PUBLISHABLE_KEY: str = ""

    # Supplier device identity for Ed25519 package ingestion.
    CLIENT_SUPPLIER_DEVICE_ID: str = ""
    # Raw 32-byte Ed25519 private key encoded as 64 hexadecimal characters.
    CLIENT_SUPPLIER_PRIVATE_KEY_HEX: str = ""

    # Supplier web session. Cookie is HttpOnly; set secure=True behind HTTPS.
    SUPPLIER_SESSION_COOKIE_NAME: str = "silaris_supplier_session"
    SUPPLIER_SESSION_COOKIE_SECURE: bool = False
    SUPPLIER_SESSION_MAX_AGE_SECONDS: int = 2592000

    # Serial / RFID
    ALLOWED_DRIVERS: str = "cp210"

    # Sync Worker
    SYNC_LOOP_INTERVAL_SECONDS: int = 30
    SYNC_MAX_RETRY_BEFORE_PERMANENT_FAIL: int = 10

    # HTTP Timeouts
    HTTPX_TIMEOUT_SYNC_SECONDS: int = 10
    HTTPX_TIMEOUT_ADMIN_SECONDS: int = 15

    # Local SQLite
    DATABASE_URL: str = "sqlite:///./local.db"

    model_config = {
        "env_file": (
            str(Path(__file__).resolve().parent.parent / ".env"),
            ".env",
        ),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()

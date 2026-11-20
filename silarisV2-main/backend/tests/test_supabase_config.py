from types import SimpleNamespace

import pytest

from app.services.supabase_config import (
    SupabaseConfigurationError,
    resolve_project_url,
    resolve_publishable_key,
)


def test_resolve_single_shared_project_url():
    settings = SimpleNamespace(
        SUPABASE_URL="https://bgtxpdydljfeltdimmxr.supabase.co",
        CLIENT_SUPABASE_URL="",
    )
    assert resolve_project_url(settings) == "https://bgtxpdydljfeltdimmxr.supabase.co"


def test_rejects_two_different_supabase_projects():
    settings = SimpleNamespace(
        SUPABASE_URL="https://suhdejzcneeaozlmtguf.supabase.co",
        CLIENT_SUPABASE_URL="https://bgtxpdydljfeltdimmxr.supabase.co",
    )
    with pytest.raises(SupabaseConfigurationError):
        resolve_project_url(settings)


def test_publishable_key_uses_legacy_client_key_only_as_transition_fallback():
    settings = SimpleNamespace(
        SUPABASE_PUBLISHABLE_KEY="",
        CLIENT_SUPABASE_PUBLISHABLE_KEY="sb_publishable_shared_project",
        SUPABASE_ANON_KEY="",
    )
    assert resolve_publishable_key(settings) == "sb_publishable_shared_project"

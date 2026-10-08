"""
Unit tests for the small helpers in settings.py and for settings invariants
that production depends on.
"""

import pytest

from pacemis_inclusive_ed.settings import env_bool


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("true", True),
        ("True", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_env_bool_parses_common_spellings(monkeypatch, raw, expected):
    monkeypatch.setenv("X_FLAG", raw)
    assert env_bool("X_FLAG") is expected


def test_env_bool_default_when_unset(monkeypatch):
    monkeypatch.delenv("X_FLAG", raising=False)
    assert env_bool("X_FLAG") is False
    assert env_bool("X_FLAG", default=True) is True


def test_required_context_processors_and_apps(settings):
    cps = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
    for cp in (
        "core.context_processors.staff_context",
        "pacemis_inclusive_ed.context_processors.emis_context",
        "pacemis_inclusive_ed.context_processors.app_name",
        "pacemis_inclusive_ed.context_processors.terminology",
    ):
        assert cp in cps
    for app in ("core", "accounts", "integrations", "allauth.account", "allauth.socialaccount"):
        assert app in settings.INSTALLED_APPS


def test_auth_redirects_point_at_router(settings):
    assert settings.LOGIN_URL == "account_login"
    assert settings.LOGIN_REDIRECT_URL == "accounts:post_login_router"
    assert settings.LOGOUT_REDIRECT_URL == "account_login"


def test_emis_urls_derive_from_base_url(settings):
    base = settings.EMIS["BASE_URL"]
    assert settings.EMIS["LOGIN_URL"] == f"{base}/api/token"
    assert settings.EMIS["LOOKUPS_URL"] == f"{base}/api/lookups/collection/core"
    assert settings.EMIS["ODATA_URL"] == f"{base}/api/odata/warehouse"

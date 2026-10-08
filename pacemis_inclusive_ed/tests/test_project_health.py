"""
Project-level health checks that guard against the most common silent
regressions: a model change without a migration, a broken system check,
and a settings module that no longer imports.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError


@pytest.mark.django_db
def test_no_missing_migrations():
    """Every model change must ship with its migration."""
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
    except SystemExit as exc:  # makemigrations --check exits 1 when changes exist
        pytest.fail(f"Model changes without migrations detected:\n{out.getvalue()}")
    assert "No changes detected" in out.getvalue()


@pytest.mark.django_db
def test_system_checks_pass():
    try:
        call_command("check", stdout=StringIO())
    except SystemCheckError as exc:
        pytest.fail(str(exc))


def test_test_settings_keep_email_and_http_offline(settings):
    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
    assert settings.EMIS["BASE_URL"].startswith("http://emis.invalid")
    assert settings.CACHES["default"]["BACKEND"].endswith("LocMemCache")

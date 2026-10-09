"""
Settings used by the automated test suite.

Imports the real settings so tests exercise the production configuration,
then overrides only what tests need: in-memory email and cache, fast
password hashing, and an EMIS endpoint that can never be reached. The test
database is created and destroyed by the test runner and is separate from
the development database named in .env.
"""

from pathlib import Path

from dotenv import load_dotenv

# manage.py loads .env before Django starts; pytest does not go through
# manage.py, so load it here before the base settings read the environment.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .settings import *  # noqa: E402,F401,F403

SECRET_KEY = "test-only-secret-key"
DEBUG = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "noreply@example.org"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ADMINS = [("Test Admin", "admin@example.org")]

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

# Point EMIS at an unresolvable host. conftest.py additionally blocks all
# outbound HTTP, so a test that forgets to mock the EMIS API fails fast.
EMIS = {
    **EMIS,  # noqa: F405
    "CONTEXT": "Test EMIS",
    "BASE_URL": "http://emis.invalid",
    "USERNAME": "emis-test-user",
    "PASSWORD": "emis-test-password",
    "TIMEOUT_SECONDS": 1,
    "MAX_RETRIES": 0,
    "VERIFY_SSL": True,
}
EMIS["LOGIN_URL"] = f'{EMIS["BASE_URL"]}/api/token'
EMIS["LOOKUPS_URL"] = f'{EMIS["BASE_URL"]}/api/lookups/collection/core'
EMIS["ODATA_URL"] = f'{EMIS["BASE_URL"]}/api/odata/warehouse'

# The login template renders a Google sign-in link, which needs a social app.
# Configure it from settings so no SocialApp row is required in the test DB.
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        **SOCIALACCOUNT_PROVIDERS["google"],  # noqa: F405
        "APP": {"client_id": "test-client-id", "secret": "test-secret", "key": ""},
    }
}

APP_NAME = "Disability Inclusive Education"
TERMINOLOGY = {
    "SYSTEM_USERS_SINGULAR": "System User",
    "SYSTEM_USERS_PLURAL": "System Users",
}

# Quiet, console-only logging. No mail_admins handler so a deliberate 500 in
# a test never lands in the email outbox being asserted on.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}

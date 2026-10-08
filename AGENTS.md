# Agent Instructions

Guidance for coding agents working in this repository. Keep this file
vendor-neutral; see https://agents.md.

## Python Environment

Conda is no longer used. The project runs from a `uv`-managed virtual
environment at `.venv/` in the repository root (Python 3.12).

- Windows: `.venv/Scripts/python.exe manage.py <command>`
- macOS/Linux: `.venv/bin/python manage.py <command>`
- Install or update dependencies with `uv pip install --python <that python> -r requirements.txt`
  (add `-r requirements-dev.txt` for the test tooling).

Never invoke a bare `python`; always use the interpreter inside `.venv/`.

## Database Migrations

Never run migrations automatically. When a change needs a migration, say so
and let the user run it.

## Tests

The test suite uses pytest with pytest-django and runs against a throwaway
PostgreSQL test database (`test_<PG_NAME>`) that the runner creates and drops.
It never touches the development database. See the "Testing" section of
README.md for how to run it and the conventions for adding tests.

- Run the suite before proposing a commit: `.venv/Scripts/python.exe -m pytest`
- Every new view needs an entry in `core/tests/test_smoke_urls.py`; a meta-test
  fails otherwise.
- Outbound HTTP is blocked in tests. Mock the EMIS clients or use `responses`.
- A change to `core/permissions.py` must be mirrored in `core/tests/test_permissions.py`.
- CI (`.github/workflows/tests.yml`) enforces the coverage floor in `.coveragerc`.
  Raise the floor when coverage grows; never lower it.
- Test work is additive. If a test reveals an application bug, report it (or record it
  as a strict `xfail`) rather than silently changing behaviour in the same change.

## Project Structure

- Django 5.x project
- Apps: `accounts`, `core`, `integrations`
- Templates: `templates/` (project-level) and app-specific template directories
- Static files: `static/`

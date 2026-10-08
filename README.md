# Pacific EMIS – Disability-Inclusive Education Module

This repository hosts a Django-based application that extends the **Pacific Education Management Information System (EMIS)** to support **disability-inclusive education** data management and analytics.  
It is designed to integrate closely with the main Pacific EMIS Core while remaining deployable as a standalone service.

---

## 🌍 Purpose & Scope

The module enables Ministries of Education across the Pacific to:
- Record and monitor learners with disabilities and functional needs.
- Track teacher training and support staff involved in inclusive education.
- Capture school accessibility indicators.
- Produce analytical dashboards and reports that feed into national EMIS data.

---

## 🧭 Context within Pacific EMIS

The Disability-Inclusive Education module complements existing national EMIS implementations such as **KEMIS** (in Kiriabti), providing a shared data model and integration endpoints.  
It follows the same data governance and design principles used throughout the Pacific EMIS ecosystem.

---

## 🧩 Development Status

- ✅ Core data models: `StaffSchoolMembership`, `Student`, `DisabilityType`
- ✅ Administrative interface and initial dashboard
- 🚧 Next: Enhanced frontend UI and analytics integration
- 📈 Planned: CSV import/export and sync with Pacific EMIS API

---

## 🧠 Design Principles

- Modular and decoupled architecture  
- Data integrity and accessibility compliance  
- Clean Bootstrap-based UI (migration toward htmx / Alpine.js planned)  
- Shared visual identity with other Pacific EMIS modules  

---

## 🗂️ Repository Notes

This project follows standard Django conventions (`models.py`, `views.py`, `templates/`, etc.).  
See the generated bundle manifest (`dist/*.manifest.txt`) for up-to-date structure details.  

---

## ⚙️ Quick Setup (for developers)

The project uses [uv](https://docs.astral.sh/uv/) to manage a virtual environment in `.venv/` (Python 3.12).

```bash
# create the environment and install dependencies
uv venv --python 3.12
uv pip install -r requirements.txt

# apply migrations and start server
# (Windows: .venv/Scripts/python.exe, macOS/Linux: .venv/bin/python)
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py runserver
```

Configuration uses the same conventions as Pacific EMIS Core (database URL, authentication, etc.).  
Environment variables are read from a local `.env` file when present.

---

## 🧪 Seeding Sample Data

To quickly populate your **Inclusive Education** app with randomized sample data, use the included Django management command:

```bash
python manage.py seed_inclusive_ed --year 2025
```

This command creates:
- Random **students** with realistic names and date of birth close to their class level’s official age.  
- A single **enrolment record per student**, linked to schools and class levels appropriate for their school code pattern.  
- Randomized **disability indicators** (`cft1_wears_glasses`, `cft20_depressed_frequency`, cft2_difficulty_seeing_with_glasses, etc.).  
- Only schools with codes starting with `KPS`, `KJSS`, or `KSSS` are included.  
- Schools with codes starting with `KECE` are **ignored**.  

### Command Options

| Option | Description | Example |
|:--------|:-------------|:---------|
| `--year <code>` | The `EmisWarehouseYear.code` to seed against (default: `2025`). | `--year 2024` |
| `--seed <int>` | Optional random seed for reproducibility. | `--seed 1234` |
| `--dry-run` | Prints the plan (how many students per school) without writing to the database. | `--dry-run` |

### Example Usage

```bash
# Preview the plan
python manage.py seed_inclusive_ed --year 2025 --dry-run

# Generate deterministic data for testing
python manage.py seed_inclusive_ed --year 2025 --seed 42
```

### Output Example

```text
--- DRY RUN ---
Target year: 2025
Schools: KPS=12  KJSS=5  KSSS=3
Total new students planned: 286
Sample (first 10 rows):
  KPS001 → 4 students across levels ['P1', 'P2', 'P3', 'P4', 'P5', 'P6']
  KPS002 → 9 students across levels ['P1', 'P2', 'P3', 'P4', 'P5', 'P6']
  ...
```

### Notes
- Each student gets exactly **one enrolment** (no duplicates for the same school/year).  
- Random student DOBs correspond roughly to the **official age** for each class level (e.g., `P1 → 6 years`, `SS4 → 18 years`).  
- Data generation uses `transaction.atomic()` to ensure atomic creation — nothing is saved if an error occurs.  

---

## 🧪 Testing

The automated test suite uses [pytest](https://docs.pytest.org/) with
[pytest-django](https://pytest-django.readthedocs.io/). It runs against a
throwaway PostgreSQL database named `test_<PG_NAME>` that the runner creates
and drops on every run, so the development database is never touched. The
PostgreSQL role in `.env` needs the `CREATEDB` privilege for this.

```bash
# one-time: install the test tooling on top of the runtime dependencies
uv pip install -r requirements-dev.txt

# run everything
.venv/Scripts/python.exe -m pytest

# faster re-runs while developing (keeps the test database between runs;
# add --create-db after changing migrations)
.venv/Scripts/python.exe -m pytest --reuse-db

# with a coverage report
.venv/Scripts/python.exe -m pytest --cov --cov-report=term-missing
```

### Layout and conventions

| Location | Purpose |
|:---|:---|
| `pytest.ini`, `.coveragerc` | Runner and coverage configuration. |
| `pacemis_inclusive_ed/settings_test.py` | Imports the real settings, then overrides only what tests need: in-memory email and cache, fast password hashing, an unreachable EMIS endpoint. |
| `conftest.py` | Shared `factory_boy` factories and fixtures. One fixture per role (`superuser`, `admin_user`, `system_admin_user`, `system_staff_user`, `school_admin_user`, `teacher_user`, `school_staff_user`, `pending_user`), plus `school_a` (the school every school-level role is assigned to) and `school_b` (a school they are not). |
| `<app>/tests/` | Tests live in a `tests/` package per app, not a `tests.py` module. |
| `core/tests/test_smoke_urls.py` | Every named URL is exercised as superuser, anonymous and a locked-out user. A meta-test fails if a URL name is missing from the inventory, so each new view must be added there. |
| `pacemis_inclusive_ed/tests/test_project_health.py` | Fails when a model change has no migration or a system check breaks. |

Safety nets that apply to every test:

- **No outbound HTTP.** An autouse fixture blocks `requests` at the adapter level. Tests that exercise the EMIS integration mock the client or use the `responses` library.
- **No real email.** The locmem backend captures messages in `django.core.mail.outbox`.
- **Groups match production.** The `seed_groups` management command runs once per session, so group names and permissions are the real ones.

---

## 📜 Licensing & Acknowledgement

- **License:** Refer to LICENSE

---

_Last updated: October 2026_

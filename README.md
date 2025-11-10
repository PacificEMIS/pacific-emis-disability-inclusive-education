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

```bash
# create or activate environment
conda create -n pacific-emis-disability-inclusive-education python=3.12.12
conda activate pacific-emis-disability-inclusive-education

# install dependencies
pip install -r requirements.txt

# apply migrations and start server
python manage.py migrate
python manage.py runserver
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
- Randomized **disability indicators** (`seeing_flag`, `hearing_flag`, etc.).  
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

## 📜 Licensing & Acknowledgement

- **License:** Refer to LICENSE

---

_Last updated: November 2025_

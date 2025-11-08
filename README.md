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

## 📜 Licensing & Acknowledgement

- **License:** Refer to LICENSE

---

_Last updated: November 2025_

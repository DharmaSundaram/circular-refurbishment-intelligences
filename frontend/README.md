# Refurbishment Intelligence Platform

A production-ready Python Flask backend and API-connected intelligence application for circular e-waste assessment and recovery decisions. Serves the approved, unchanged compiled React UI while providing a complete, database-backed domain model and partner REST APIs.

---

## 1. Architecture

```text
Collection Application
        │
        │ POST /api/v1/refurbishment/devices
        ▼
Refurbishment Intelligence (Flask + SQLAlchemy)
   ├── Incoming Devices & Queue
   ├── Deterministic Assessment Engine
   │     ├── Repairability Score (0-100)
   │     ├── Circular Recovery Score (0-100)
   │     ├── Repair Cost & Refurbished Value
   │     ├── Component Recovery Breakdown
   │     └── Avoided CO2 Benefit (kg)
   ├── Real ReportLab PDF & CSV Exports
   ├── Bidirectional Transfer Audit Log
   └── Callback Dispatcher
        │
        │ POST /api/v1/assessment-results
        ▼
Collection Application
```

- **Frontend:** Preserved approved React UI (compiled bundle served by Flask without layout/theme changes).
- **Backend:** Python Flask with blueprints for devices, assessments, transfers, reports, and analytics.
- **ORM / Database:** SQLAlchemy supporting SQLite locally and PostgreSQL on Render.
- **Migrations:** Flask-Migrate / Alembic with migration scripts (`flask db upgrade`).
- **Reports:** ReportLab generating professional PDF assessment reports; CSV summary export.
- **Production WSGI:** Gunicorn with multi-threading and timeout management.

---

## 2. Directory Structure

```text
frontend/
  app.py                         # Application factory & static UI serving
  config.py                      # Database, secret keys, and partner URLs
  extensions.py                  # db (SQLAlchemy) & migrate (Migrate)
  seed.py                        # Database seed CLI & helper
  requirements.txt               # Production dependencies
  render.yaml                    # Render Blueprint deployment config
  API_CONTRACT.md                # Full API contract and specifications
  README.md                      # Architecture and setup guide
  models/                        # Relational database models
    __init__.py
    device.py                    # Device domain model
    transfer.py                  # Inbound & outbound transfer audit log
    assessment.py                # Assessment & component breakdown
    recovery.py                  # Recovery economic valuation
    report.py                    # Report metadata & tracking
    idempotency.py               # Idempotent request ledger
    device_file.py               # File reference tracking
  services/                      # Domain logic services
    __init__.py
    assessment_engine.py         # Multi-factor deterministic assessment
    callback_service.py          # Partner callback & retry dispatcher
    report_service.py            # ReportLab PDF & CSV generation
    file_service.py              # Safe filesystem storage & traversal prevention
  api/                           # API blueprints
    __init__.py
    auth.py                      # API key authentication decorator
    devices.py                   # Ingest device & list/queue endpoints
    assessments.py               # Assessment evaluation & callback trigger
    transfers.py                 # Transfer log querying & retries
    reports.py                   # PDF and CSV download endpoints
    analytics.py                 # Dashboard KPIs & recovery aggregations
  migrations/                    # Alembic migration scripts
  tests/                         # Comprehensive unit & integration tests
    test_flask_app.py            # Static UI and route tests
    test_database.py             # Schema & transaction tests
    test_incoming_device.py      # Inbound API & idempotency tests
    test_assessment_engine.py    # Deterministic calculation tests
    test_reports_and_callbacks.py# PDF, CSV, and callback mock tests
    test_security.py             # Path traversal & isolation tests
  ui/                            # Compiled React frontend
    index.html
    favicon.svg
    assets/
```

---

## 3. Environment Variables

| Variable | Description | Default / Local Development |
|---|---|---|
| `DATABASE_URL` | PostgreSQL or SQLite connection string | `sqlite:///instance/refurbishment.sqlite3` |
| `SECRET_KEY` | Flask session secret key | Configurable secret string |
| `CIRCULAR_API_KEY` | Partner API authentication key (`X-API-Key`) | `circ-refurb-secret-key-2026` |
| `COLLECTION_API_URL` | Base URL of partner Collection Application | Optional (e.g. `https://collection-app.onrender.com`) |
| `COLLECTION_API_KEY` | Partner API authentication key for outbound calls | Optional |
| `UPLOAD_STORAGE_PATH` | Storage directory for local device files | `frontend/uploads` |
| `IS_PRODUCTION` | Production environment flag | `false` |

---

## 4. Local Setup & Execution

### 4.1 Prerequisites
- Python 3.10+ (tested with Python 3.11, 3.12, 3.13)

### 4.2 Installation

```bash
# Navigate to application directory
cd frontend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4.3 Database Migrations & Seeding

```bash
# Run migrations
flask db upgrade

# Seed baseline baseline devices and assessments (optional, recommended for local dev)
flask seed-db
```

### 4.4 Start Server

```bash
flask --app app run --port 5000
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## 5. Production Deployment (Render)

### 5.1 Render Blueprint
The project includes `render.yaml` configured with Render PostgreSQL and persistent disk storage:

- **Build Command:** `pip install -r frontend/requirements.txt`
- **Start Command:** `cd frontend && flask db upgrade && gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 app:app`
- **Health Check Path:** `/api/health`

### 5.2 Persistent Storage
Configured at `/var/data/uploads` via Render persistent disk.

---

## 6. Testing & Verification

Run the test suite with `pytest` or `unittest`:

```bash
# Run with pytest
python -m pytest -q

# Run with unittest
python -m unittest discover -s tests
```
All 26 test cases cover startup, database constraints, API authentication, idempotency, calculation determinism, ReportLab PDF output, partner callbacks, and security.

# Refurbishment Intelligence — Backend Service

A dedicated Python Flask backend providing REST APIs, multi-factor deterministic Assessment Intelligence, ReportLab PDF generation, SQLAlchemy ORM with Alembic migrations, and upstream partner integration for the Circular E-Waste Platform.

---

## 1. Directory Structure

```text
backend/
  ├── app.py                      # Application factory & UI serving
  ├── config.py                   # Environment configuration (DB, keys, storage)
  ├── extensions.py               # db (SQLAlchemy) & migrate (Migrate)
  ├── seed.py                     # Database seeding CLI (flask seed-db)
  ├── requirements.txt            # Python dependencies
  ├── API_CONTRACT.md             # Complete API contract and schemas
  ├── README.md                   # Backend documentation
  │
  ├── api/                        # REST API Blueprints
  │   ├── __init__.py             # Blueprint registration
  │   ├── auth.py                 # X-API-Key authentication decorator
  │   ├── devices.py              # Ingest & query devices (/api/v1/devices, /queue)
  │   ├── assessments.py          # Run assessment & callback dispatch
  │   ├── transfers.py            # API transfer log & retry
  │   ├── reports.py              # Binary PDF & CSV downloads
  │   └── analytics.py            # Dashboard KPIs & recovery aggregations
  │
  ├── services/                   # Business Logic & Calculation Engines
  │   ├── __init__.py
  │   ├── assessment_engine.py    # Deterministic repairability (0-100), costs, CO2
  │   ├── callback_service.py     # Outbound callback dispatcher to Collection App
  │   ├── report_service.py       # ReportLab PDF & CSV generation
  │   └── file_service.py         # Safe filesystem storage with traversal protection
  │
  ├── models/                     # SQLAlchemy Relational Models
  │   ├── __init__.py
  │   ├── device.py               # Device status and physical conditions
  │   ├── assessment.py           # Assessment & component breakdown
  │   ├── recovery.py             # RecoveryAnalysis economic metrics
  │   ├── transfer.py             # Transfer audit log (Inbound / Outbound)
  │   ├── idempotency.py          # IdempotencyEvent duplicate ledger
  │   ├── device_file.py          # Local and remote file references
  │   └── report.py               # Report metadata
  │
  ├── migrations/                 # Alembic database migration scripts
  └── tests/                      # 26 automated unit and integration tests
```

---

## 2. Quick Start

### 2.1 Virtual Environment & Dependencies

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2.2 Database Migrations & Seeding

```bash
flask db upgrade
flask seed-db
```

### 2.3 Run Backend Server

```bash
flask --app app run --port 5000
```

---

## 3. Running Tests

```bash
python -m pytest -q
# or
python -m unittest discover -s tests
```
All 26 tests validate database constraints, idempotency, calculation determinism, ReportLab PDF generation, partner callbacks, and security.

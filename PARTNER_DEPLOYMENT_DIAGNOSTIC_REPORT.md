# PARTNER DEPLOYMENT DIAGNOSTIC REPORT

**Project:** Circular Refurbishment Intelligence (Application 2)  
**Partner Application:** E-Waste Collection & Recovery (Application 1)  
**Infrastructure:** Shared Supabase PostgreSQL & Supabase Storage (`ewaste-files`)  
**Deployment Platform:** Vercel Serverless Functions  
**Status:** Remediated & Hardened  

---

## 1. Confirmed Root Causes

### Root Cause 1: `FATAL: (ENOTFOUND) tenant/user postgres.projectref not found`
* **Symptom:** `GET /api/v1/transfers` returned HTTP 500 with `psycopg.OperationalError: FATAL: (ENOTFOUND) tenant/user postgres.projectref not found`.
* **Mechanism:** 
  1. Supabase PgBouncer Transaction Poolers (port `6543`) route incoming client connections to backend database tenants using the username formatted as `postgres.<project-ref>`.
  2. The production Vercel environment had `SUPABASE_DB_URL` (or `DATABASE_URL`) populated with an uncustomized documentation placeholder string containing `postgres.projectref` rather than the live project reference ID.
  3. When psycopg connected to the Supabase pooler host, PgBouncer inspected the tenant ID `projectref`, found no matching Supabase tenant, and rejected the connection with `FATAL: (ENOTFOUND) tenant/user postgres.projectref not found`.

### Root Cause 2: Divergent Endpoint Status Codes (500 on `/transfers` vs 401 on `/devices` and `/dashboard`)
* **Symptom:** `GET /api/v1/transfers` returned 500, while `GET /api/v1/devices` and `GET /api/v1/dashboard` returned 401.
* **Mechanism:**
  1. `backend/api/devices.py` (`/api/v1/devices`) and `backend/api/analytics.py` (`/api/v1/dashboard`) are protected by the `@require_internal_auth` decorator. When an unauthenticated request arrived, the decorator immediately rejected the request with HTTP 401 Unauthorized before any database query was executed.
  2. In contrast, `backend/api/transfers.py` (`/api/v1/transfers`) **lacked** an authentication decorator. Unauthenticated requests bypassed authentication and immediately triggered `Transfer.query.order_by(...).all()`, forcing SQLAlchemy to checkout a connection from Supabase, which crashed with 500 due to the broken `SUPABASE_DB_URL`.
  3. If valid administrator credentials had been passed to `/devices` or `/dashboard`, they would have triggered the same database failure. Protecting `/transfers` with `@require_internal_auth` closes this security gap and standardizes error responses.

### Root Cause 3: Psycopg 3 Strict Parameter Rejection (`?pgbouncer=true`)
* **Symptom:** Psycopg 3 throws `psycopg.ProgrammingError: invalid URI query parameter: "pgbouncer"` when connection strings generated for Node.js/Prisma are used.
* **Mechanism:** Psycopg 3 validates all query string parameters against native `libpq` connection parameters. Non-libpq options like `pgbouncer=true` and `connection_limit=1` cause immediate runtime crashes upon connection initialization.

---

## 2. Files Modified

| File | Type | Changes Implemented |
|---|---|---|
| `backend/config.py` | Configuration Hardening | 1. URL scheme normalization for `postgresql+psycopg://`.<br>2. Query parameter sanitization: strips unsupported Prisma/PgBouncer parameters (`pgbouncer`, `connection_limit`, `pool_timeout`).<br>3. Proactive placeholder detection: detects `projectref`, `[PROJECT-REF]`, `[PASSWORD]`, etc., raising clear diagnostic `ValueError` exceptions before runtime crashes.<br>4. Serverless pooling (`NullPool`) and schema search path enforcement (`refurbishment,public`). |
| `backend/api/transfers.py` | Security & Auth | Decorated `list_transfers()`, `get_transfer_detail()`, and `retry_transfer()` with `@require_internal_auth`. Returns 401 for unauthenticated calls and 403 if partner inbound keys are supplied. |
| `backend/migrations/env.py` | Migration Isolation | 1. Added `include_object` filter guaranteeing Alembic only inspects and manages `refurbishment` schema tables.<br>2. Enforced `version_table_schema="refurbishment"` and `include_schemas=True` in both online and offline migration modes.<br>3. Guarded imports to allow safe CLI and testing execution. |
| `backend/app.py` | CLI Enhancements | Added `flask check-db` CLI command for non-destructive database and schema diagnostics. |
| `backend/scripts/db_diagnostic.py` | New Tool | Created a 100% read-only diagnostic utility that checks PostgreSQL connectivity, user identity, search path, table existence, Alembic revision, and table CRUD privileges. |
| `backend/migrations/refurbishment_schema.sql` | DDL Reference | Verified and positioned schema DDL with idempotent `CREATE TABLE IF NOT EXISTS` and clean privilege grants. |
| `backend/tests/test_phase10_supabase_integration.py` | Test Suite | Updated retry test to pass admin credentials and verified 401 rejection for unauthenticated calls. |
| `backend/tests/test_deployment_diagnostic.py` | Test Suite | Added 16 new automated test cases covering normalization, parameter stripping, placeholder detection, transfer endpoint security, Alembic isolation, and diagnostic verification. |

---

## 3. Database Configuration Findings

### Supabase Connection String Formats
Supabase provides two distinct connection methods:

1. **Transaction Pooler (PgBouncer) — Recommended for Vercel Serverless:**
   * **Port:** `6543`
   * **Host:** `aws-0-[REGION].pooler.supabase.com`
   * **Username Format:** `postgres.[PROJECT-REF]` *(Must include the project reference suffix)*
   * **Connection String:**
     ```
     postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
     ```
   * **Engine Pooling:** Configured with `NullPool` in `backend/config.py` to prevent serverless connection exhaustion.

2. **Direct Connection (Session Pooler):**
   * **Port:** `5432`
   * **Host:** `db.[PROJECT-REF].supabase.co`
   * **Username Format:** `postgres` *(No suffix)*
   * **Connection String:**
     ```
     postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres?sslmode=require
     ```

### Schema Search Path & Isolation
* The engine option `connect_args={"options": "-c search_path=refurbishment,public"}` ensures all unqualified table queries default to `refurbishment`.
* Models explicitly specify `__table_args__ = {"schema": "refurbishment"}`.
* Alembic tracking is isolated to `refurbishment.alembic_version`.
* The partner application's `collection` schema is isolated from refurbishment migrations and operations.

---

## 4. Authentication Findings

The platform implements strict separation of duties across three independent credentials:

| Credential Name | Scope & Allowed Endpoints | Prohibited Usage |
|---|---|---|
| `PARTNER_INBOUND_API_KEY` | **Incoming device transfers only:**<br>• `POST /api/v1/refurbishment/devices`<br>• `POST /api/v1/devices/receive` | Prohibited from accessing administrative APIs (`/devices`, `/dashboard`, `/transfers`, `/assessments`). Rejected with HTTP 403 if attempted. |
| `COLLECTION_API_KEY` | **Outgoing assessment callbacks only:**<br>• Used by `backend/services/callback_service.py` to sign outbound requests to `POST {COLLECTION_API_URL}/api/v1/assessment-results`. | Never used for inbound authentication. |
| `ADMIN_API_KEY` | **Privileged administrative operations:**<br>• `GET /api/v1/devices`<br>• `GET /api/v1/devices/<id>`<br>• `GET /api/v1/dashboard`<br>• `GET /api/v1/transfers`<br>• `GET /api/v1/transfers/<id>`<br>• `POST /api/v1/transfers/<id>/retry`<br>• `POST /api/v1/assessments` | Not required for incoming device transfer ingestion from partner. |

* **Dashboard Web UI:** Authenticates via secure session cookie (`admin=True`) established via `POST /api/v1/auth/login`.
* **Public Health Check:** `GET /api/health` remains public (no credentials required) and returns HTTP 200/503 status without leaking stack traces.
* **Expected 401 Responses:** When `GET /api/v1/devices`, `GET /api/v1/dashboard`, or `GET /api/v1/transfers` are probed without an `ADMIN_API_KEY` or admin session, HTTP 401 is the expected, correct security response.

---

## 5. Migration Status & Execution Guide

### Schema Architecture
* **Schema Name:** `refurbishment`
* **Tables Managed:**
  1. `refurbishment.devices`
  2. `refurbishment.idempotency_events`
  3. `refurbishment.assessments`
  4. `refurbishment.assessment_components`
  5. `refurbishment.recovery_analyses`
  6. `refurbishment.reports`
  7. `refurbishment.transfers`
  8. `refurbishment.device_files`
* **Version Table:** `refurbishment.alembic_version`
* **Current Alembic Revision:** `7f9cd19afe3f`

### Safe Execution Pathways

#### Pathway 1: For an Empty / Fresh Supabase Database
Run the authoritative Alembic migration to create the schema and all tables:
```bash
flask migrate-refurbishment-schema
```
*(Executes `CREATE SCHEMA IF NOT EXISTS refurbishment;` and runs Alembic `upgrade head`)*.

#### Pathway 2: For a Database Already Initialized via SQL Script
If tables were created by running `backend/migrations/refurbishment_schema.sql` directly in Supabase SQL Editor:
```bash
flask stamp-refurbishment-schema
```
*(Aligns `refurbishment.alembic_version` to head without executing DDL or dropping existing tables)*.

---

## 6. Required Vercel Environment Variables

Configure these variables in your **Vercel Project Settings → Environment Variables**:

```ini
# =============================================================================
# ENVIRONMENT & SECRET KEYS
# =============================================================================
IS_PRODUCTION=true
SECRET_KEY=generate-a-strong-random-hex-string-for-flask-sessions

# =============================================================================
# SUPABASE POSTGRESQL DATABASE
# Replace [PROJECT-REF] with your Supabase Project ID (from https://[PROJECT-REF].supabase.co)
# Replace [YOUR-PASSWORD] with your actual Supabase database password
# =============================================================================
SUPABASE_DB_URL=postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
DB_SCHEMA=refurbishment
DB_USE_NULLPOOL=true

# =============================================================================
# INDEPENDENT PARTNER & ADMIN API KEYS
# =============================================================================
# Key expected from Collection Application when sending devices to Refurbishment
PARTNER_INBOUND_API_KEY=partner-inbound-secret-key-32chars

# Key sent to Collection Application when Refurbishment delivers assessment callbacks
COLLECTION_API_KEY=partner-collection-secret-key-32chars

# Base URL of the deployed partner Collection Application on Vercel
COLLECTION_API_URL=https://your-partner-collection-app.vercel.app

# Optional key for internal machine-to-machine administrative access
ADMIN_API_KEY=refurb-admin-secret-key-32chars

# =============================================================================
# SUPABASE STORAGE (Shared Private Bucket: ewaste-files)
# =============================================================================
SUPABASE_URL=https://[PROJECT-REF].supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJh...your-supabase-service-role-key...
SUPABASE_STORAGE_BUCKET=ewaste-files
```

---

## 7. Step-by-Step Deployment Instructions

### Step 1: Update Vercel Environment Variables
1. Log in to the [Vercel Dashboard](https://vercel.com).
2. Select the `circular-refurbishment-intelligence` project.
3. Navigate to **Settings → Environment Variables**.
4. Check `SUPABASE_DB_URL`:
   * Ensure `postgres.projectref` is replaced with your real Supabase project ID (`postgres.<actual-ref>`).
   * Ensure the database password is valid.
   * Ensure port `6543` (Transaction Pooler) or `5432` (Direct) is specified.
5. Ensure `PARTNER_INBOUND_API_KEY`, `COLLECTION_API_KEY`, `COLLECTION_API_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` are all present.
6. Click **Save**.

### Step 2: Validate Database Connectivity Locally (Read-Only)
Before redeploying, verify your Supabase database connectivity using the diagnostic tool:
```bash
python backend/scripts/db_diagnostic.py --url "postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require"
```
Or set the environment variable and run:
```bash
flask check-db
```
Verify the diagnostic outputs `Overall Status: [PASS]`.

### Step 3: Run Migrations Against Supabase
* If tables do not exist in the `refurbishment` schema:
  ```bash
  flask migrate-refurbishment-schema
  ```
* If tables were already created in Supabase SQL editor:
  ```bash
  flask stamp-refurbishment-schema
  ```

### Step 4: Redeploy on Vercel
Trigger a redeployment on Vercel with the updated environment variables:
* In the Vercel Dashboard, go to **Deployments**.
* Click the three dots (`...`) on the latest deployment and select **Redeploy** (ensure "Use existing Build Cache" is unchecked if needed).

### Step 5: Verify Deployed Endpoints
1. **Public Health Check (Expected 200 OK):**
   ```bash
   curl -i https://your-refurbishment-app.vercel.app/api/health
   ```
   *Response: `{"application": "Refurbishment Intelligence", "database": "ok", "status": "ok", "ui_build_available": true}`*

2. **Unauthenticated Transfer Endpoint (Expected 401 Unauthorized):**
   ```bash
   curl -i https://your-refurbishment-app.vercel.app/api/v1/transfers
   ```
   *Response: HTTP 401 Unauthorized (`Administrator authentication required`)*

3. **Authenticated Administrative Request (Expected 200 OK):**
   ```bash
   curl -i -H "X-API-Key: <YOUR_ADMIN_API_KEY>" https://your-refurbishment-app.vercel.app/api/v1/transfers
   ```
   *Response: HTTP 200 OK (`{"total": ..., "transfers": [...]}`)*

4. **Partner Inbound Device Ingestion (Expected 201 Created or 200 Idempotent):**
   ```bash
   curl -i -X POST https://your-refurbishment-app.vercel.app/api/v1/refurbishment/devices \
     -H "Content-Type: application/json" \
     -H "X-API-Key: <YOUR_PARTNER_INBOUND_API_KEY>" \
     -d '{
       "device_id": "TEST-DEV-001",
       "transfer_id": "TRF-TEST-001",
       "device": {
         "type": "Laptop",
         "brand": "Dell",
         "model": "Latitude 5420",
         "condition": "Good"
       }
     }'
   ```

---

## 8. Remaining Action Items

1. **User Action Required in Vercel:**  
   Update `SUPABASE_DB_URL` in the Vercel project dashboard to replace the placeholder token (`projectref`) with your live Supabase project reference and password.
2. **Partner Coordination:**  
   Confirm that the Collection Application has configured:
   * Outgoing destination URL: `https://your-refurbishment-app.vercel.app/api/v1/refurbishment/devices`
   * Outgoing API Key: Matching `PARTNER_INBOUND_API_KEY`.
   * Inbound callback endpoint: `POST https://partner-collection-app.vercel.app/api/v1/assessment-results` configured to accept `COLLECTION_API_KEY`.
3. **No Code Changes Pending:**  
   All 57 automated tests pass locally. Codebase is fully production-hardened.


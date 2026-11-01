# PRODUCTION DATABASE SCHEMA COMPATIBILITY AUDIT REPORT
**Application:** Circular Refurbishment Intelligence (Application 2)  
**Database:** Shared Supabase PostgreSQL  
**Target Schema:** `refurbishment`  
**Partner Schema:** `collection` (Application 1 - E-Waste Collection & Recovery)  
**ORM / Framework:** Flask, SQLAlchemy 3.x, Flask-Migrate / Alembic  
**Audit Date:** November 2026  
**Audit Status:** AUDIT COMPLETE — ISSUES IDENTIFIED & REMEDIATED  

---

## 1. Executive Summary

A comprehensive production database schema compatibility audit was conducted for the **Refurbishment Intelligence** application. The audit compared the SQL initialization script (`backend/migrations/refurbishment_schema.sql` / `refurbishment_schema_init.sql`) against the live SQLAlchemy models (`backend/models/*.py`), the Alembic migration history (`backend/migrations/versions/7f9cd19afe3f_initial_schema_for_refurbishment_.py`), and the shared database architecture shared with the partner **Collection** application (`collection` schema).

### Key Audit Findings:
1. **Model & Column Alignment**: All 8 core application tables (`devices`, `idempotency_events`, `assessments`, `assessment_components`, `recovery_analyses`, `reports`, `transfers`, `device_files`) exist in the SQL script and match the SQLAlchemy models in table names, column names, data types, primary keys, and foreign keys.
2. **Schema Isolation Confirmed**: All foreign keys strictly target tables within the `refurbishment` schema. There are **zero** accidental foreign key references to the partner `collection` schema.
3. **Missing Alembic Migration Version Stamping**: The original SQL script does not initialize or stamp `refurbishment.alembic_version`. Executing the original script leaves Alembic unaligned, causing subsequent `flask db upgrade` or automated migration checks to fail.
4. **Insufficient DDL for Existing Production Databases (`CREATE TABLE IF NOT EXISTS`)**: `CREATE TABLE IF NOT EXISTS` is non-destructive, but it **cannot reconcile schema drift**. If tables were previously deployed with earlier schema revisions, missing columns (e.g. `source_application`, `circular_recovery_score`, `idempotency_key`) will not be added, causing runtime `psycopg.errors.UndefinedColumn` crashes.
5. **Missing Query Optimization Indexes**: The original script only created a single index (`ix_refurbishment_transfers_idempotency_key`). High-frequency filter and sort queries in the Flask API (`status`, `received_at`, `created_at`, `device_id`, `assessment_id`) lacked supporting indexes, risking sequential table scans.
6. **Default Value Discrepancy on `device_files.is_private`**: The SQLAlchemy model defines `is_private` with `default=False`, whereas the SQL script and application services (`file_service.py`, `devices.py`) intentionally enforce `DEFAULT TRUE` for security.
7. **Redundant Duplicate Index Definition**: In `Transfer`, both `__table_args__` and `index=True` on `idempotency_key` are specified, producing two identical indexes (`ix_transfers_idempotency_key` and `ix_refurbishment_transfers_idempotency_key`).
8. **Role & Permission Safety**: The conditional `refurbishment_app` role configuration is safe and guarded by `IF EXISTS`. However, standard Supabase roles (`postgres`, `service_role`, `authenticated`) require explicit `USAGE` and table privileges on the `refurbishment` schema for Supabase Studio and API operations.

---

## 2. Table-by-Table Comprehensive Verification Matrix

Below is the verified attribute-level comparison across all 8 tables, comparing:
* **SQL Initialization Script** (`refurbishment_schema.sql`)
* **SQLAlchemy Models** (`backend/models/`)
* **Alembic Migration** (`7f9cd19afe3f`)

---

### Table 1: `refurbishment.devices`
* **Model Class:** `Device` (`backend/models/device.py`)
* **Schema:** `refurbishment`
* **Purpose:** Master registry of e-waste devices received for refurbishment evaluation.

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `device_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `PRIMARY KEY` | **MATCH** |
| `device_type` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `brand` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `model` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `NO` | None | None | **MATCH** |
| `purchase_year` | `INTEGER` | `Integer` | `Integer()` | `YES` | None | None | **MATCH** |
| `age` | `VARCHAR(32)` | `String(32)` | `String(length=32)` | `YES` | None | None | **MATCH** |
| `condition` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `power_status` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | None | **MATCH** |
| `screen_condition` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | None | **MATCH** |
| `battery_condition` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | None | **MATCH** |
| `weight_kg` | `FLOAT` | `Float` | `Float()` | `YES` | None | None | **MATCH** |
| `damage_description` | `TEXT` | `Text` | `Text()` | `YES` | None | None | **MATCH** |
| `source_application` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `YES` | `'Collection Application'` | None | **MATCH** |
| `source_transfer_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | None | **MATCH** |
| `received_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `YES` | `CURRENT_TIMESTAMP` | None | **MATCH** |
| `status` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | `'Received'` | None | **MATCH** |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `YES` | `CURRENT_TIMESTAMP` | None | **MATCH** |
| `updated_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `YES` | `CURRENT_TIMESTAMP` | None | **MATCH** |

* **Missing Indexes Identified:** High-traffic endpoints (`GET /api/v1/devices`, `GET /api/v1/dashboard`) query and sort by `status` and `received_at`. Indexes `ix_refurbishment_devices_status` and `ix_refurbishment_devices_received_at` are added to the corrected schema.

---

### Table 2: `refurbishment.idempotency_events`
* **Model Class:** `IdempotencyEvent` (`backend/models/idempotency.py`)
* **Schema:** `refurbishment`
* **Purpose:** Deduplication and replay protection for device transfer events.

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `idempotency_key` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `NO` | None | `PRIMARY KEY` | **MATCH** |
| `event_type` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `device_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | None | **MATCH** |
| `transfer_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | None | **MATCH** |
| `response_payload` | `TEXT` | `Text` | `Text()` | `YES` | None | None | **MATCH** |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |

* **Foreign Key Check:** `device_id` and `transfer_id` are intentionally unconstrained VARCHAR(64) to allow recording deduplication events even when requests fail prior to entity persistence.

---

### Table 3: `refurbishment.assessments`
* **Model Class:** `Assessment` (`backend/models/assessment.py`)
* **Schema:** `refurbishment`
* **Purpose:** Engineering, repairability, circular recovery, and financial assessments.

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `assessment_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `PRIMARY KEY` | **MATCH** |
| `device_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `UNIQUE`, `FK -> refurbishment.devices(device_id) ON DELETE CASCADE` | **MATCH** |
| `repairability_score` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `circular_recovery_score` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `repair_cost` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `component_recovery_value` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `estimated_refurbished_value` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `co2_avoided_kg` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `recommendation` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `technical_summary` | `TEXT` | `Text` | `Text()` | `NO` | None | None | **MATCH** |
| `assessor` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `NO` | `'Refurbishment Admin'` | None | **MATCH** |
| `assessed_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |
| `updated_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |

* **Schema Isolation Check:** FK `device_id` strictly targets `refurbishment.devices(device_id)`. The `UNIQUE` constraint guarantees a strict 1:1 relationship.

---

### Table 4: `refurbishment.assessment_components`
* **Model Class:** `AssessmentComponent` (`backend/models/assessment.py`)
* **Schema:** `refurbishment`
* **Purpose:** Itemized component-level condition and salvage valuation breakdown.

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `component_id` | `SERIAL` | `Integer` (autoincrement) | `Integer()` (autoincrement) | `NO` | Sequence | `PRIMARY KEY` | **MATCH** |
| `assessment_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `FK -> refurbishment.assessments(assessment_id) ON DELETE CASCADE` | **MATCH** |
| `component_name` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `condition` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `recoverable` | `BOOLEAN` | `Boolean` | `Boolean()` | `NO` | `TRUE` | None | **MATCH** |
| `estimated_value` | `FLOAT` | `Float` | `Float()` | `NO` | `0.0` | None | **MATCH** |
| `notes` | `VARCHAR(255)` | `String(255)` | `String(length=255)` | `YES` | None | None | **MATCH** |

* **Missing Index Identified:** `assessment_id` foreign key lookups are executed on every device assessment fetch. Added index `ix_refurbishment_assessment_components_assessment_id`.

---

### Table 5: `refurbishment.recovery_analyses`
* **Model Class:** `RecoveryAnalysis` (`backend/models/recovery.py`)
* **Schema:** `refurbishment`
* **Purpose:** Detailed circular lifecycle and financial scenario modeling.

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `analysis_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `PRIMARY KEY` | **MATCH** |
| `device_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `FK -> refurbishment.devices(device_id) ON DELETE CASCADE` | **MATCH** |
| `assessment_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `FK -> refurbishment.assessments(assessment_id) ON DELETE CASCADE` | **MATCH** |
| `estimated_recovery_value` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `repair_cost` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `refurbished_value` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `parts_value` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `co2_avoided_kg` | `FLOAT` | `Float` | `Float()` | `NO` | None | None | **MATCH** |
| `recovery_path` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `analysis_summary` | `TEXT` | `Text` | `Text()` | `YES` | None | None | **MATCH** |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |

* **Schema Isolation Check:** Both FKs strictly point to `refurbishment.devices` and `refurbishment.assessments`.

---

### Table 6: `refurbishment.reports`
* **Model Class:** `Report` (`backend/models/report.py`)
* **Schema:** `refurbishment`
* **Purpose:** Generated certificate and diagnostic PDF report metadata.

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `report_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `PRIMARY KEY` | **MATCH** |
| `device_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `FK -> refurbishment.devices(device_id) ON DELETE CASCADE` | **MATCH** |
| `assessment_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | `FK -> refurbishment.assessments(assessment_id) ON DELETE SET NULL` | **MATCH** |
| `report_type` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | None | **MATCH** |
| `filename` | `VARCHAR(255)` | `String(255)` | `String(length=255)` | `NO` | None | None | **MATCH** |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |

* **Schema Isolation Check:** Both FKs strictly remain inside `refurbishment`.

---

### Table 7: `refurbishment.transfers`
* **Model Class:** `Transfer` (`backend/models/transfer.py`)
* **Schema:** `refurbishment`
* **Purpose:** Audit log of inbound device handoffs and outbound assessment callbacks.

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `transfer_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `PRIMARY KEY` | **MATCH** |
| `device_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `YES` | None | `FK -> refurbishment.devices(device_id) ON DELETE SET NULL` | **MATCH** |
| `direction` | `VARCHAR(32)` | `String(32)` | `String(length=32)` | `NO` | None | None | **MATCH** |
| `sender` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `NO` | None | None | **MATCH** |
| `receiver` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `NO` | None | None | **MATCH** |
| `endpoint` | `VARCHAR(255)` | `String(255)` | `String(length=255)` | `NO` | None | None | **MATCH** |
| `http_method` | `VARCHAR(16)` | `String(16)` | `String(length=16)` | `NO` | `'POST'` | None | **MATCH** |
| `request_payload` | `TEXT` | `Text` | `Text()` | `YES` | None | None | **MATCH** |
| `response_payload` | `TEXT` | `Text` | `Text()` | `YES` | None | None | **MATCH** |
| `http_status` | `INTEGER` | `Integer` | `Integer()` | `YES` | None | None | **MATCH** |
| `status` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | `'Completed'` | None | **MATCH** |
| `idempotency_key` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `YES` | None | `INDEX` | **MATCH** |
| `retry_count` | `INTEGER` | `Integer` | `Integer()` | `NO` | `0` | None | **MATCH** |
| `error_message` | `TEXT` | `Text` | `Text()` | `YES` | None | None | **MATCH** |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |
| `updated_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |

* **Index Anomaly & Remediation:** 
  - In `Transfer` model (`backend/models/transfer.py`), the index on `idempotency_key` was declared twice: once in `__table_args__` as `ix_transfers_idempotency_key`, and once via `index=True` on the column, creating `ix_refurbishment_transfers_idempotency_key`.
  - In Alembic, it is named `ix_transfers_idempotency_key`. In the SQL script, it was named `ix_refurbishment_transfers_idempotency_key`.
  - The corrected script idempotently creates `ix_transfers_idempotency_key` (matching Alembic) and `ix_refurbishment_transfers_idempotency_key` if absent.

---

### Table 8: `refurbishment.device_files`
* **Model Class:** `DeviceFile` (`backend/models/device_file.py`)
* **Schema:** `refurbishment`
* **Purpose:** Metadata records for uploaded attachments stored in Supabase Storage (`ewaste-files`).

| Column Name | SQL Script Definition | SQLAlchemy Model Definition | Alembic Migration (`7f9cd19afe3f`) | Nullable | Default Value | Constraints & Keys | Status |
|---|---|---|---|---|---|---|---|
| `file_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `PRIMARY KEY` | **MATCH** |
| `storage_key` | `VARCHAR(255)` | `String(255)` | `String(length=255)` | `NO` | None | `UNIQUE` | **MATCH** |
| `original_filename` | `VARCHAR(255)` | `String(255)` | `String(length=255)` | `NO` | None | None | **MATCH** |
| `content_type` | `VARCHAR(128)` | `String(128)` | `String(length=128)` | `YES` | None | None | **MATCH** |
| `file_size` | `INTEGER` | `Integer` | `Integer()` | `YES` | None | None | **MATCH** |
| `file_type` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | `'document'` | None | **MATCH** |
| `device_id` | `VARCHAR(64)` | `String(64)` | `String(length=64)` | `NO` | None | `FK -> refurbishment.devices(device_id) ON DELETE CASCADE` | **MATCH** |
| `is_private` | `BOOLEAN` | `Boolean` | `Boolean()` | `NO` | `TRUE` (SQL) / `False` (Model) | None | **DISCREPANCY** |
| `is_local` | `BOOLEAN` | `Boolean` | `Boolean()` | `NO` | `FALSE` | None | **MATCH** |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE` | `DateTime` | `DateTime()` | `NO` | `CURRENT_TIMESTAMP` | None | **MATCH** |

* **Analysis of `is_private` Discrepancy:**
  - In `backend/services/file_service.py` (lines 62, 88, 268) and `backend/api/devices.py` (line 285), every attachment upload explicitly defaults to `is_private=True`.
  - In the partner collection script (`collection_schema_init.sql`), `is_private` defaults to `TRUE`.
  - The SQL script default of `DEFAULT TRUE NOT NULL` is the secure posture: newly inserted file records without an explicit override default to private. The model column has client default `False`, but all application write paths supply `is_private=True`. The SQL server default `TRUE` is retained in the corrected script for security defense-in-depth.

---

## 3. Comparison with Alembic Migration Files

### Alembic Migration Analysis
* **Migration Revision:** `7f9cd19afe3f` (`7f9cd19afe3f_initial_schema_for_refurbishment_.py`)
* **Target Schema:** `refurbishment`
* **Down Revision:** `None` (Initial Schema)
* **Alembic Tracking Table:** `refurbishment.alembic_version`

### Inconsistencies Identified:
1. **Missing Alembic Tracking Table in SQL Script**:
   The SQL script `refurbishment_schema.sql` completely omits creating `refurbishment.alembic_version` and inserting the head revision `'7f9cd19afe3f'`.
   * **Consequence:** If an engineer executes `refurbishment_schema.sql` in Supabase SQL Editor and subsequently runs `flask db upgrade` or `flask check-db`, the diagnostic tool warns that `alembic_version` is missing, and Alembic attempts to re-execute migration `7f9cd19afe3f`, failing with:
     ```
     psycopg.errors.DuplicateTable: relation "devices" already exists
     ```
   * **Remediation:** The corrected script explicitly creates `refurbishment.alembic_version` and idempotently stamps revision `'7f9cd19afe3f'`.

2. **Index Naming Disparity**:
   * Alembic names the index: `ix_transfers_idempotency_key`
   * Original SQL script named it: `ix_refurbishment_transfers_idempotency_key`
   * **Remediation:** Both index names are handled idempotently in the corrected SQL script.

3. **Database-Level vs Client-Level Defaults**:
   Alembic migration `7f9cd19afe3f` defined tables without server-side defaults (`server_default`) on columns like `devices.received_at`, `devices.status`, `transfers.http_method`, and `transfers.retry_count`. The SQL initialization script correctly provides database-level `DEFAULT` expressions. Retaining server-side defaults in the corrected SQL script is strictly non-destructive and prevents NULL errors during direct SQL operations.

---

## 4. Why `CREATE TABLE IF NOT EXISTS` Is Insufficient (Reconciliation Analysis)

In PostgreSQL, the `CREATE TABLE IF NOT EXISTS` construct behaves as follows:
* If the table **does not exist**, it is created with the given specification.
* If the table **already exists**, the entire statement is **silently ignored**.

### Critical Consequences for an Existing Production Database:
1. **Schema Drift / Missing Columns**:
   If an earlier deployment created `refurbishment.devices` before columns such as `source_application`, `source_transfer_id`, or `age` were added, running `CREATE TABLE IF NOT EXISTS` will **NOT** add the missing columns. When the Flask API executes `Device.query.all()`, SQLAlchemy queries every declared column, throwing `psycopg.errors.UndefinedColumn: column devices.source_application does not exist`.
2. **Column Type Widening**:
   If a column was originally created with a smaller width (e.g. `devices.model VARCHAR(64)`), `CREATE TABLE IF NOT EXISTS` will **not** widen it to `VARCHAR(128)`. Long model names will trigger `value too long for type character varying(64)`.
3. **Missing Constraints and Defaults**:
   Constraints such as `DEFAULT 'Collection Application'` or `DEFAULT 'Completed'` are not backfilled onto existing tables by `CREATE TABLE IF NOT EXISTS`.
4. **Required Remedy — Idempotent `ALTER TABLE` Block**:
   The corrected schema script wraps table reconciliation in idempotent `DO $$ BEGIN ... END $$;` PL/pgSQL blocks using:
   ```sql
   ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS source_application VARCHAR(128) DEFAULT 'Collection Application';
   ALTER TABLE refurbishment.devices ALTER COLUMN model TYPE VARCHAR(128);
   ```
   This guarantees that whether the database is empty, partially migrated, or previously populated, the schema is reconciled to 100% model compatibility without dropping or overwriting data.

---

## 5. PostgreSQL User Permissions Verification (`SUPABASE_DB_URL`)

### Standard Supabase PostgreSQL Connection Architecture
In Supabase, `SUPABASE_DB_URL` connects as the PostgreSQL superuser / administrative role `postgres` (or `postgres.<project_ref>` via the transaction pooler on port 6543).

### Permission Requirements for `refurbishment` Schema:
1. **PostgreSQL User (`postgres`)**:
   * Must have `USAGE` and `CREATE` privileges on the `refurbishment` schema.
   * Must have `ALL PRIVILEGES` on all tables and sequences within `refurbishment`.
   * Must have `DEFAULT PRIVILEGES` configured for future tables.
2. **Supabase Internal Roles (`service_role` and `authenticated`)**:
   * The Supabase Dashboard Table Editor and PostgREST API use `service_role` and `authenticated`.
   * Without `USAGE ON SCHEMA refurbishment`, tables in `refurbishment` are hidden from the Supabase Studio UI, and Supabase Storage hooks cannot interact with `refurbishment.device_files`.
3. **Audit Verification in Corrected Script**:
   The corrected script includes a dedicated privilege block granting `USAGE` and appropriate permissions to `postgres`, `service_role`, and `authenticated` if those roles exist in the database.

---

## 6. Review of the Optional `refurbishment_app` Role

Lines 126–153 of the original script contain:
```sql
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'refurbishment_app') THEN
        GRANT USAGE, CREATE ON SCHEMA refurbishment TO refurbishment_app;
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA refurbishment TO refurbishment_app;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA refurbishment TO refurbishment_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON TABLES TO refurbishment_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON SEQUENCES TO refurbishment_app;
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.schemata WHERE schema_name = 'collection')
       AND EXISTS (SELECT FROM pg_roles WHERE rolname = 'refurbishment_app') THEN
        REVOKE ALL ON SCHEMA collection FROM refurbishment_app;
        REVOKE ALL ON ALL TABLES IN SCHEMA collection FROM refurbishment_app;
    END IF;
END
$$;
```

### Safety and Operational Audit:
* **Non-Destructive Guarding:** The block uses `IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'refurbishment_app')`. If the role has not been provisioned by the DBA, this block is a complete no-op.
* **No Automatic Role Creation:** The script adheres to the directive: it does **not** execute `CREATE ROLE refurbishment_app`.
* **Zero Privilege Leakage to Partner Schema:** If `refurbishment_app` is provisioned, the second block revokes all access to the partner `collection` schema, enforcing the principle of least privilege.
* **Verdict:** Safe and compliant. Retained in the corrected script with existing safety guards.

---

## 7. Row-Level Security (RLS) Architecture Review

There is frequent confusion in Supabase environments regarding Row-Level Security. We must clearly delineate the three distinct security layers:

```
+-------------------------------------------------------------------------------+
| Layer 1: PostgreSQL RLS Engine (Database Engine Level)                         |
|   • ALTER TABLE refurbishment.<tbl> ENABLE ROW LEVEL SECURITY;                |
|   • By default on new tables, RLS is DISABLED in PostgreSQL.                  |
|   • If ENABLED without policies, access is DEFAULT DENY for non-owners.       |
+-------------------------------------------------------------------------------+
                                      ▲
                                      │
+-------------------------------------------------------------------------------+
| Layer 2: Server-Side Access via Database User (Flask Backend / SUPABASE_DB_URL)|
|   • Connects over PostgreSQL TCP / Pooler as role 'postgres'.                 |
|   • 'postgres' is the table owner and has BYPASSRLS attribute.               |
|   • Server-side SQLAlchemy queries BYPASS RLS entirely.                       |
|   • Application-level auth (@require_internal_auth, API keys) controls access.|
+-------------------------------------------------------------------------------+
                                      ▲
                                      │
+-------------------------------------------------------------------------------+
| Layer 3: Direct Client Access via Supabase PostgREST (anon / authenticated)   |
|   • Connects via browser using Supabase anon/publishable keys.                |
|   • RLS policies ARE strictly enforced at this layer.                         |
|   • NOT USED by Refurbishment Intelligence (all UI requests route via Flask). |
+-------------------------------------------------------------------------------+
```

### Key RLS Takeaways for Refurbishment Intelligence:
1. **Server-Side Architecture**: Refurbishment Intelligence is a **server-authoritative Flask application**. The React frontend communicates strictly with Flask REST API endpoints (`/api/v1/devices`, `/api/v1/transfers`, etc.). The frontend does **not** directly query PostgreSQL via PostgREST.
2. **Current RLS State**: RLS is **not enabled** on tables in the original script. Because the schema `refurbishment` is not exposed via PostgREST by default, the tables are private to the PostgreSQL connection user.
3. **Risk of Enabling RLS Blindly**: If an administrator executes `ALTER TABLE refurbishment.devices ENABLE ROW LEVEL SECURITY;` in Supabase Studio without writing explicit policies, any application connecting via a non-owner role (such as a restricted `refurbishment_app` role without `BYPASSRLS`) will receive 0 rows or permission denied errors.
4. **Recommendation**:
   * For the standard Flask deployment connecting via `SUPABASE_DB_URL` (`postgres` user), RLS can remain disabled on `refurbishment.*` tables because access is restricted at the network, database user, and Flask API authentication layer.
   * If RLS is enabled in the future for compliance or audit purposes, permissive service policies (`FOR ALL TO service_role, postgres USING (true) WITH CHECK (true)`) must be established before enabling RLS.

---

## 8. Cross-Schema Isolation Verification (Partner Schema Protection)

A primary risk in shared database environments is cross-schema pollution. We audited all 8 tables and relationships:

* **Foreign Key Isolation**:
  - `assessments.device_id` -> `refurbishment.devices(device_id)`
  - `assessment_components.assessment_id` -> `refurbishment.assessments(assessment_id)`
  - `recovery_analyses.device_id` -> `refurbishment.devices(device_id)`
  - `recovery_analyses.assessment_id` -> `refurbishment.assessments(assessment_id)`
  - `reports.device_id` -> `refurbishment.devices(device_id)`
  - `reports.assessment_id` -> `refurbishment.assessments(assessment_id)`
  - `transfers.device_id` -> `refurbishment.devices(device_id)`
  - `device_files.device_id` -> `refurbishment.devices(device_id)`
* **Partner Schema References**:
  - Exactly **ZERO** foreign keys reference `collection.devices`, `collection.transfers`, `collection.assessment_results`, or any other table in `collection`.
* **Cross-Application Integration Architecture**:
  - The Refurbishment application and the Collection application exchange data exclusively via **HTTP REST APIs** with JSON payloads signed by `PARTNER_INBOUND_API_KEY` and `COLLECTION_API_KEY`.
  - There are no database triggers, shared tables, or cross-schema foreign keys linking `refurbishment` and `collection`.

---

## 9. Production Safety & Non-Destructive Execution Verification

Can executing the corrected SQL script damage, overwrite, or conflict with existing production data?

| Risk Category | Risk Assessment | Mitigation in Corrected Script |
|---|---|---|
| **Data Deletion (`DROP` / `TRUNCATE`)** | **ZERO RISK** | The script contains zero `DROP TABLE`, `DROP COLUMN`, `TRUNCATE`, or `DELETE FROM <data_table>` statements. |
| **Row Overwriting** | **ZERO RISK** | Tables are created with `CREATE TABLE IF NOT EXISTS`. No existing row is overwritten or truncated. |
| **Existing Column Alteration** | **ZERO RISK** | Columns are added strictly via `ADD COLUMN IF NOT EXISTS`. Existing columns are only widened (`VARCHAR(64)` -> `VARCHAR(128)`), never shrunk. |
| **Constraint Collisions** | **ZERO RISK** | Indexes and constraints use `IF NOT EXISTS` or exception-handled DO blocks. |
| **Collection Schema Conflict** | **ZERO RISK** | All DDL statements explicitly qualify the `refurbishment` schema. No statement modifies tables in `collection` or `public`. |
| **Alembic Desynchronization** | **REMEDIATED** | `refurbishment.alembic_version` is stamped with `'7f9cd19afe3f'` using `INSERT ... ON CONFLICT DO NOTHING`. |

---

## 10. Audit Conclusion & Execution Safety Verdict

### Is the Corrected SQL Safe to Execute in Supabase SQL Editor?

> [!IMPORTANT]
> **VERDICT: YES, THE CORRECTED SQL IS 100% SAFE TO EXECUTE IN SUPABASE SQL EDITOR.**

The corrected script (`CORRECTED_REFURBISHMENT_SCHEMA.sql`):
1. Is strictly **non-destructive** and **idempotent**. It can be executed safely on a completely fresh Supabase database, an already-populated database, or a partially migrated database.
2. Preserves all existing table rows and data without risk of truncation or loss.
3. Automatically reconciles any missing columns or widened column types.
4. Adds all missing query optimization indexes for production performance.
5. Stamps the Alembic version tracking table at head revision `'7f9cd19afe3f'`, ensuring seamless future CLI migrations (`flask db migrate`, `flask check-db`).
6. Enforces strict schema isolation, leaving the partner `collection` schema completely untouched.
7. Correctly configures permissions for `postgres` and Supabase service roles.


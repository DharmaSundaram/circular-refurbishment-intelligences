# DATABASE PRE-DEPLOYMENT & VERIFICATION CHECKLIST
**Application:** Circular Refurbishment Intelligence (Application 2)  
**Database Infrastructure:** Shared Supabase PostgreSQL  
**Dedicated Application Schema:** `refurbishment`  
**Partner Application Schema:** `collection` (Application 1 - Isolated)  
**Authoritative Migration Script:** `CORRECTED_REFURBISHMENT_SCHEMA.sql`  

---

## 1. Pre-Deployment Environmental Verification

Before running any script in the Supabase SQL Editor, verify that your environment variables and connection strings are configured correctly.

- [ ] **1.1 Verify Shared Database Target**
  - Confirm you are connecting to the correct Supabase Project instance shared between Application 1 (Collection) and Application 2 (Refurbishment).
  - Confirm the existing `collection` schema is present in the database (Application 1 tables must remain completely untouched).

- [ ] **1.2 Verify `SUPABASE_DB_URL` Format**
  - **Transaction Pooler (Recommended for Vercel Serverless / Flask):**
    ```
    postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
    ```
    *Ensure `postgres.[PROJECT-REF]` contains your live project ID, not the placeholder `postgres.projectref`.*
  - **Direct Connection:**
    ```
    postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres?sslmode=require
    ```

- [ ] **1.3 Verify Vercel / Production Environment Variables**
  - [ ] `SUPABASE_DB_URL` is configured with valid live credentials.
  - [ ] `DB_SCHEMA` is set to `refurbishment` (defaults to `refurbishment` in `backend/config.py`).
  - [ ] `DB_USE_NULLPOOL` is set to `true` (enforces `NullPool` to prevent pool exhaustion on serverless cold starts).
  - [ ] `PARTNER_INBOUND_API_KEY` is configured for incoming device handoffs from Collection.
  - [ ] `COLLECTION_API_KEY` is configured for outbound assessment callbacks.
  - [ ] `ADMIN_API_KEY` is configured for administrative queries and web UI session management.
  - [ ] `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are configured for file attachment storage (`ewaste-files` bucket).

---

## 2. Supabase SQL Editor Execution Guide

The corrected script (`CORRECTED_REFURBISHMENT_SCHEMA.sql`) is 100% idempotent and non-destructive. It can be run directly in the Supabase SQL Editor web interface.

### Step-by-Step Execution:
1. Open your browser and navigate to the **Supabase Dashboard**: `https://supabase.com/dashboard/project/<your-project-ref>`.
2. In the left navigation sidebar, click on **SQL Editor**.
3. Click **+ New query**.
4. Open `CORRECTED_REFURBISHMENT_SCHEMA.sql` from this repository, copy its entire contents, and paste them into the SQL Editor.
5. Click the green **Run** button (or press `Ctrl + Enter` / `Cmd + Enter`).
6. Observe the query results pane at the bottom of the screen.

### Expected Result Output from Step 7 Verification Query:
```text
schema_name   | total_tables | total_indexes | alembic_head_revision
--------------+--------------+---------------+-----------------------
refurbishment | 9            | 18            | 7f9cd19afe3f
```
*(9 tables = 8 application tables + 1 alembic_version tracking table)*

---

## 3. Schema & Isolation Verification Checklist

After executing `CORRECTED_REFURBISHMENT_SCHEMA.sql`, run the following validation queries in the Supabase SQL Editor to confirm proper isolation and schema alignment:

- [ ] **3.1 Confirm All 8 Core Tables Exist in `refurbishment` Schema**
  ```sql
  SELECT table_name 
  FROM information_schema.tables 
  WHERE table_schema = 'refurbishment'
  ORDER BY table_name;
  ```
  *Required tables:*
  1. `alembic_version`
  2. `assessment_components`
  3. `assessments`
  4. `device_files`
  5. `devices`
  6. `idempotency_events`
  7. `recovery_analyses`
  8. `reports`
  9. `transfers`

- [ ] **3.2 Confirm Zero Foreign Keys Leak into `collection` Schema**
  ```sql
  SELECT
      tc.table_schema, 
      tc.table_name, 
      kcu.column_name, 
      ccu.table_schema AS foreign_table_schema,
      ccu.table_name AS foreign_table_name,
      ccu.column_name AS foreign_column_name 
  FROM information_schema.table_constraints AS tc 
  JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
      AND tc.table_schema = kcu.table_schema
  JOIN information_schema.constraint_column_usage AS ccu
      ON ccu.constraint_name = tc.constraint_name
  WHERE tc.constraint_type = 'FOREIGN KEY' 
    AND tc.table_schema = 'refurbishment';
  ```
  *Verification:* Every returned row must show `foreign_table_schema = 'refurbishment'`. There must be **0** rows targeting `collection`.

- [ ] **3.3 Confirm Partner `collection` Schema Remains Unchanged**
  ```sql
  SELECT table_name 
  FROM information_schema.tables 
  WHERE table_schema = 'collection'
  ORDER BY table_name;
  ```
  *Verification:* Collection application tables (`devices`, `transfers`, `assessment_results`, `device_files`, `metadata`, `alembic_version`) must remain intact and unaltered.

- [ ] **3.4 Confirm Alembic Head Revision Is Stamped**
  ```sql
  SELECT * FROM refurbishment.alembic_version;
  ```
  *Expected Output:* Exactly 1 row with `version_num = '7f9cd19afe3f'`.

---

## 4. Permissions & Row-Level Security (RLS) Checklist

- [ ] **4.1 PostgreSQL User Privileges (`postgres`)**
  - Verify `has_schema_privilege('postgres', 'refurbishment', 'USAGE')` returns `true`.
  - Verify `has_table_privilege('postgres', 'refurbishment.devices', 'SELECT')` returns `true`.
  - Verify `has_table_privilege('postgres', 'refurbishment.devices', 'INSERT')` returns `true`.

- [ ] **4.2 Supabase Studio / Table Editor Visibility (`service_role`)**
  - Navigate to **Table Editor** in the Supabase Dashboard.
  - In the schema dropdown at the top, select `refurbishment`.
  - Confirm all 8 tables are visible in the sidebar and browseable.

- [ ] **4.3 Row-Level Security (RLS) Posture**
  - Confirm RLS status on `refurbishment` tables:
    ```sql
    SELECT tablename, rowsecurity 
    FROM pg_tables 
    WHERE schemaname = 'refurbishment';
    ```
  - **Understanding RLS in this Deployment:**
    * `rowsecurity = false`: Standard for server-side Flask backend applications. Tables are protected by PostgreSQL user authentication, network isolation, and Flask API endpoint decorators (`@require_internal_auth`).
    * If `rowsecurity = true` is ever enabled for compliance, ensure explicit policies are attached (`CREATE POLICY ... ON refurbishment.<tbl> FOR ALL TO service_role, postgres USING (true)`). **Never enable RLS without policies**, as this causes total query denial for non-owner database connections.

---

## 5. Post-Deployment Application Health Check

Once the SQL script has executed successfully in Supabase:

- [ ] **5.1 Execute CLI Read-Only Diagnostic**
  From the project backend directory, execute:
  ```bash
  flask check-db
  ```
  *Expected Output:*
  ```text
  [PASS] PostgreSQL Connected
  [PASS] Current Database: postgres | User: postgres | Schema: refurbishment
  [PASS] Dedicated 'refurbishment' schema exists
  [PASS] All 8 required tables present in 'refurbishment'
  [PASS] Alembic version aligned at 7f9cd19afe3f
  [PASS] Table CRUD privileges verified
  [PASS] Partner 'collection' schema isolated
  STATUS: PASS
  ```

- [ ] **5.2 Verify Public Health Endpoint**
  Test the live health endpoint:
  ```bash
  curl -i https://<your-refurbishment-app>.vercel.app/api/health
  ```
  *Expected Response:* HTTP 200 OK
  ```json
  {
    "application": "Refurbishment Intelligence",
    "status": "ok",
    "database": "ok",
    "ui_build_available": true
  }
  ```

- [ ] **5.3 Test Protected Inbound Device Handoff (Partner Integration)**
  Send an authenticated test transfer request using `PARTNER_INBOUND_API_KEY`:
  ```bash
  curl -X POST https://<your-refurbishment-app>.vercel.app/api/v1/refurbishment/devices \
    -H "Content-Type: application/json" \
    -H "X-API-Key: <YOUR_PARTNER_INBOUND_API_KEY>" \
    -d '{
      "device_id": "TEST-AUDIT-001",
      "device_type": "Laptop",
      "brand": "Dell",
      "model": "Latitude 5420",
      "purchase_year": 2021,
      "condition": "Working",
      "status": "Received"
    }'
  ```
  *Expected Response:* HTTP 201 Created with JSON confirmation.

- [ ] **5.4 Clean Up Test Record**
  If test record `TEST-AUDIT-001` was inserted, remove it cleanly:
  ```sql
  DELETE FROM refurbishment.devices WHERE device_id = 'TEST-AUDIT-001';
  ```

---

## 6. Disaster Recovery & Rollback Plan

Because `CORRECTED_REFURBISHMENT_SCHEMA.sql` is strictly non-destructive (uses `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, and safe type widening):
* **It does not drop or alter any existing data.**
* **It does not require rolling back existing tables.**
* If a rollback of new columns or indexes is ever needed:
  - Indexes can be dropped harmlessly with `DROP INDEX IF EXISTS refurbishment.<index_name>;`.
  - Columns can be kept as nullable without disrupting earlier application code.
  - The partner `collection` schema is never touched and requires zero rollback actions.


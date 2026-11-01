-- =============================================================================
-- CIRCULAR REFURBISHMENT INTELLIGENCE — PRODUCTION SCHEMA MIGRATION & RECONCILIATION
-- Application: Refurbishment Intelligence (Application 2)
-- Target: Shared Supabase PostgreSQL Database
-- Schema: refurbishment
-- Isolation: Exclusively owns 'refurbishment' schema; zero access to 'collection'
-- Revision: Aligned with SQLAlchemy Models and Alembic Revision '7f9cd19afe3f'
-- Safety: 100% IDEMPOTENT & NON-DESTRUCTIVE (No DROP, No TRUNCATE, No DATA LOSS)
-- =============================================================================

-- =============================================================================
-- STEP 1: CREATE DEDICATED SCHEMA
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS refurbishment;

-- =============================================================================
-- STEP 2: CREATE BASE TABLES (IF NOT EXISTS)
-- Exact match with backend/models/*.py and Alembic 7f9cd19afe3f
-- =============================================================================

-- 1. Master Devices Table
CREATE TABLE IF NOT EXISTS refurbishment.devices (
    device_id VARCHAR(64) PRIMARY KEY,
    device_type VARCHAR(64) NOT NULL,
    brand VARCHAR(64) NOT NULL,
    model VARCHAR(128) NOT NULL,
    purchase_year INTEGER,
    age VARCHAR(32),
    condition VARCHAR(64) NOT NULL,
    power_status VARCHAR(64),
    screen_condition VARCHAR(64),
    battery_condition VARCHAR(64),
    weight_kg FLOAT,
    damage_description TEXT,
    source_application VARCHAR(128) DEFAULT 'Collection Application',
    source_transfer_id VARCHAR(64),
    received_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(64) DEFAULT 'Received' NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Idempotency Events Table (Deduplication Log)
CREATE TABLE IF NOT EXISTS refurbishment.idempotency_events (
    idempotency_key VARCHAR(128) PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    device_id VARCHAR(64),
    transfer_id VARCHAR(64),
    response_payload TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 3. Engineering & Circularity Assessments Table
CREATE TABLE IF NOT EXISTS refurbishment.assessments (
    assessment_id VARCHAR(64) PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL UNIQUE REFERENCES refurbishment.devices(device_id) ON DELETE CASCADE,
    repairability_score FLOAT NOT NULL,
    circular_recovery_score FLOAT NOT NULL,
    repair_cost FLOAT NOT NULL,
    component_recovery_value FLOAT NOT NULL,
    estimated_refurbished_value FLOAT NOT NULL,
    co2_avoided_kg FLOAT NOT NULL,
    recommendation VARCHAR(64) NOT NULL,
    technical_summary TEXT NOT NULL,
    assessor VARCHAR(128) DEFAULT 'Refurbishment Admin' NOT NULL,
    assessed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 4. Itemized Assessment Components Table
CREATE TABLE IF NOT EXISTS refurbishment.assessment_components (
    component_id SERIAL PRIMARY KEY,
    assessment_id VARCHAR(64) NOT NULL REFERENCES refurbishment.assessments(assessment_id) ON DELETE CASCADE,
    component_name VARCHAR(64) NOT NULL,
    condition VARCHAR(64) NOT NULL,
    recoverable BOOLEAN DEFAULT TRUE NOT NULL,
    estimated_value FLOAT DEFAULT 0.0 NOT NULL,
    notes VARCHAR(255)
);

-- 5. Recovery Analyses Table (Lifecycle Scenario Modeling)
CREATE TABLE IF NOT EXISTS refurbishment.recovery_analyses (
    analysis_id VARCHAR(64) PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL REFERENCES refurbishment.devices(device_id) ON DELETE CASCADE,
    assessment_id VARCHAR(64) NOT NULL REFERENCES refurbishment.assessments(assessment_id) ON DELETE CASCADE,
    estimated_recovery_value FLOAT NOT NULL,
    repair_cost FLOAT NOT NULL,
    refurbished_value FLOAT NOT NULL,
    parts_value FLOAT NOT NULL,
    co2_avoided_kg FLOAT NOT NULL,
    recovery_path VARCHAR(64) NOT NULL,
    analysis_summary TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 6. Generated Reports Table
CREATE TABLE IF NOT EXISTS refurbishment.reports (
    report_id VARCHAR(64) PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL REFERENCES refurbishment.devices(device_id) ON DELETE CASCADE,
    assessment_id VARCHAR(64) REFERENCES refurbishment.assessments(assessment_id) ON DELETE SET NULL,
    report_type VARCHAR(64) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 7. Partner Transfers Audit Table
CREATE TABLE IF NOT EXISTS refurbishment.transfers (
    transfer_id VARCHAR(64) PRIMARY KEY,
    device_id VARCHAR(64) REFERENCES refurbishment.devices(device_id) ON DELETE SET NULL,
    direction VARCHAR(32) NOT NULL,
    sender VARCHAR(128) NOT NULL,
    receiver VARCHAR(128) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    http_method VARCHAR(16) DEFAULT 'POST' NOT NULL,
    request_payload TEXT,
    response_payload TEXT,
    http_status INTEGER,
    status VARCHAR(64) DEFAULT 'Completed' NOT NULL,
    idempotency_key VARCHAR(128),
    retry_count INTEGER DEFAULT 0 NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 8. Device File Attachments Table (Supabase Storage Metadata)
CREATE TABLE IF NOT EXISTS refurbishment.device_files (
    file_id VARCHAR(64) PRIMARY KEY,
    storage_key VARCHAR(255) NOT NULL UNIQUE,
    original_filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(128),
    file_size INTEGER,
    file_type VARCHAR(64) DEFAULT 'document' NOT NULL,
    device_id VARCHAR(64) NOT NULL REFERENCES refurbishment.devices(device_id) ON DELETE CASCADE,
    is_private BOOLEAN DEFAULT TRUE NOT NULL,
    is_local BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- =============================================================================
-- STEP 3: IDEMPOTENT SCHEMA RECONCILIATION FOR EXISTING DEPLOYMENTS
-- Ensures any existing tables are seamlessly upgraded to current model specs
-- =============================================================================

DO $$
BEGIN
    -- -------------------------------------------------------------------------
    -- 1. Reconcile refurbishment.devices
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'devices') THEN
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS purchase_year INTEGER;
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS age VARCHAR(32);
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS power_status VARCHAR(64);
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS screen_condition VARCHAR(64);
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS battery_condition VARCHAR(64);
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS weight_kg FLOAT;
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS damage_description TEXT;
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS source_application VARCHAR(128) DEFAULT 'Collection Application';
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS source_transfer_id VARCHAR(64);
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS received_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS status VARCHAR(64) DEFAULT 'Received';
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE refurbishment.devices ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

        -- Safe column width widening
        ALTER TABLE refurbishment.devices ALTER COLUMN device_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.devices ALTER COLUMN device_type TYPE VARCHAR(64);
        ALTER TABLE refurbishment.devices ALTER COLUMN brand TYPE VARCHAR(64);
        ALTER TABLE refurbishment.devices ALTER COLUMN model TYPE VARCHAR(128);
        ALTER TABLE refurbishment.devices ALTER COLUMN condition TYPE VARCHAR(64);
        ALTER TABLE refurbishment.devices ALTER COLUMN status TYPE VARCHAR(64);
    END IF;

    -- -------------------------------------------------------------------------
    -- 2. Reconcile refurbishment.idempotency_events
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'idempotency_events') THEN
        ALTER TABLE refurbishment.idempotency_events ADD COLUMN IF NOT EXISTS device_id VARCHAR(64);
        ALTER TABLE refurbishment.idempotency_events ADD COLUMN IF NOT EXISTS transfer_id VARCHAR(64);
        ALTER TABLE refurbishment.idempotency_events ADD COLUMN IF NOT EXISTS response_payload TEXT;
        ALTER TABLE refurbishment.idempotency_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

        ALTER TABLE refurbishment.idempotency_events ALTER COLUMN idempotency_key TYPE VARCHAR(128);
        ALTER TABLE refurbishment.idempotency_events ALTER COLUMN event_type TYPE VARCHAR(64);
    END IF;

    -- -------------------------------------------------------------------------
    -- 3. Reconcile refurbishment.assessments
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'assessments') THEN
        ALTER TABLE refurbishment.assessments ADD COLUMN IF NOT EXISTS circular_recovery_score FLOAT DEFAULT 0.0;
        ALTER TABLE refurbishment.assessments ADD COLUMN IF NOT EXISTS assessor VARCHAR(128) DEFAULT 'Refurbishment Admin';
        ALTER TABLE refurbishment.assessments ADD COLUMN IF NOT EXISTS assessed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE refurbishment.assessments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE refurbishment.assessments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

        ALTER TABLE refurbishment.assessments ALTER COLUMN assessment_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.assessments ALTER COLUMN device_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.assessments ALTER COLUMN recommendation TYPE VARCHAR(64);
        ALTER TABLE refurbishment.assessments ALTER COLUMN assessor TYPE VARCHAR(128);
    END IF;

    -- -------------------------------------------------------------------------
    -- 4. Reconcile refurbishment.assessment_components
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'assessment_components') THEN
        ALTER TABLE refurbishment.assessment_components ADD COLUMN IF NOT EXISTS recoverable BOOLEAN DEFAULT TRUE;
        ALTER TABLE refurbishment.assessment_components ADD COLUMN IF NOT EXISTS estimated_value FLOAT DEFAULT 0.0;
        ALTER TABLE refurbishment.assessment_components ADD COLUMN IF NOT EXISTS notes VARCHAR(255);

        ALTER TABLE refurbishment.assessment_components ALTER COLUMN assessment_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.assessment_components ALTER COLUMN component_name TYPE VARCHAR(64);
        ALTER TABLE refurbishment.assessment_components ALTER COLUMN condition TYPE VARCHAR(64);
        ALTER TABLE refurbishment.assessment_components ALTER COLUMN notes TYPE VARCHAR(255);
    END IF;

    -- -------------------------------------------------------------------------
    -- 5. Reconcile refurbishment.recovery_analyses
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'recovery_analyses') THEN
        ALTER TABLE refurbishment.recovery_analyses ADD COLUMN IF NOT EXISTS analysis_summary TEXT;
        ALTER TABLE refurbishment.recovery_analyses ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

        ALTER TABLE refurbishment.recovery_analyses ALTER COLUMN analysis_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.recovery_analyses ALTER COLUMN device_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.recovery_analyses ALTER COLUMN assessment_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.recovery_analyses ALTER COLUMN recovery_path TYPE VARCHAR(64);
    END IF;

    -- -------------------------------------------------------------------------
    -- 6. Reconcile refurbishment.reports
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'reports') THEN
        ALTER TABLE refurbishment.reports ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

        ALTER TABLE refurbishment.reports ALTER COLUMN report_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.reports ALTER COLUMN device_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.reports ALTER COLUMN assessment_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.reports ALTER COLUMN report_type TYPE VARCHAR(64);
        ALTER TABLE refurbishment.reports ALTER COLUMN filename TYPE VARCHAR(255);
    END IF;

    -- -------------------------------------------------------------------------
    -- 7. Reconcile refurbishment.transfers
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'transfers') THEN
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS http_method VARCHAR(16) DEFAULT 'POST';
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS request_payload TEXT;
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS response_payload TEXT;
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS http_status INTEGER;
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS status VARCHAR(64) DEFAULT 'Completed';
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS error_message TEXT;
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE refurbishment.transfers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

        ALTER TABLE refurbishment.transfers ALTER COLUMN transfer_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.transfers ALTER COLUMN device_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.transfers ALTER COLUMN direction TYPE VARCHAR(32);
        ALTER TABLE refurbishment.transfers ALTER COLUMN sender TYPE VARCHAR(128);
        ALTER TABLE refurbishment.transfers ALTER COLUMN receiver TYPE VARCHAR(128);
        ALTER TABLE refurbishment.transfers ALTER COLUMN endpoint TYPE VARCHAR(255);
        ALTER TABLE refurbishment.transfers ALTER COLUMN status TYPE VARCHAR(64);
    END IF;

    -- -------------------------------------------------------------------------
    -- 8. Reconcile refurbishment.device_files
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'refurbishment' AND table_name = 'device_files') THEN
        ALTER TABLE refurbishment.device_files ADD COLUMN IF NOT EXISTS is_private BOOLEAN DEFAULT TRUE;
        ALTER TABLE refurbishment.device_files ADD COLUMN IF NOT EXISTS is_local BOOLEAN DEFAULT FALSE;
        ALTER TABLE refurbishment.device_files ADD COLUMN IF NOT EXISTS file_type VARCHAR(64) DEFAULT 'document';
        ALTER TABLE refurbishment.device_files ADD COLUMN IF NOT EXISTS content_type VARCHAR(128);
        ALTER TABLE refurbishment.device_files ADD COLUMN IF NOT EXISTS file_size INTEGER;
        ALTER TABLE refurbishment.device_files ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

        ALTER TABLE refurbishment.device_files ALTER COLUMN file_id TYPE VARCHAR(64);
        ALTER TABLE refurbishment.device_files ALTER COLUMN storage_key TYPE VARCHAR(255);
        ALTER TABLE refurbishment.device_files ALTER COLUMN original_filename TYPE VARCHAR(255);
        ALTER TABLE refurbishment.device_files ALTER COLUMN file_type TYPE VARCHAR(64);
        ALTER TABLE refurbishment.device_files ALTER COLUMN device_id TYPE VARCHAR(64);
    END IF;
END $$;

-- =============================================================================
-- STEP 4: PRODUCTION PERFORMANCE & QUERY INTEGRITY INDEXES
-- Supports fast filtering, sorting, and foreign-key join operations
-- =============================================================================

-- Devices query indexes (filtering on status, sorting on received_at)
CREATE INDEX IF NOT EXISTS ix_refurbishment_devices_status 
    ON refurbishment.devices (status);
CREATE INDEX IF NOT EXISTS ix_refurbishment_devices_received_at 
    ON refurbishment.devices (received_at DESC);
CREATE INDEX IF NOT EXISTS ix_refurbishment_devices_condition 
    ON refurbishment.devices (condition);
CREATE INDEX IF NOT EXISTS ix_refurbishment_devices_device_type 
    ON refurbishment.devices (device_type);
CREATE INDEX IF NOT EXISTS ix_refurbishment_devices_source_transfer 
    ON refurbishment.devices (source_transfer_id);

-- Transfers query indexes (idempotency, device association, status, sorting)
CREATE INDEX IF NOT EXISTS ix_transfers_idempotency_key 
    ON refurbishment.transfers (idempotency_key);
CREATE INDEX IF NOT EXISTS ix_refurbishment_transfers_idempotency_key 
    ON refurbishment.transfers (idempotency_key);
CREATE INDEX IF NOT EXISTS ix_refurbishment_transfers_device_id 
    ON refurbishment.transfers (device_id);
CREATE INDEX IF NOT EXISTS ix_refurbishment_transfers_status 
    ON refurbishment.transfers (status);
CREATE INDEX IF NOT EXISTS ix_refurbishment_transfers_created_at 
    ON refurbishment.transfers (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_refurbishment_transfers_direction 
    ON refurbishment.transfers (direction);

-- Assessments & Components FK query indexes
CREATE INDEX IF NOT EXISTS ix_refurbishment_assessment_components_assessment_id 
    ON refurbishment.assessment_components (assessment_id);

-- Recovery Analyses & Reports FK indexes
CREATE INDEX IF NOT EXISTS ix_refurbishment_recovery_analyses_device_id 
    ON refurbishment.recovery_analyses (device_id);
CREATE INDEX IF NOT EXISTS ix_refurbishment_recovery_analyses_assessment_id 
    ON refurbishment.recovery_analyses (assessment_id);
CREATE INDEX IF NOT EXISTS ix_refurbishment_reports_device_id 
    ON refurbishment.reports (device_id);
CREATE INDEX IF NOT EXISTS ix_refurbishment_reports_assessment_id 
    ON refurbishment.reports (assessment_id);

-- Device Files FK & lookup indexes
CREATE INDEX IF NOT EXISTS ix_refurbishment_device_files_device_id 
    ON refurbishment.device_files (device_id);

-- Idempotency Events cleanup & lookup index
CREATE INDEX IF NOT EXISTS ix_refurbishment_idempotency_events_created_at 
    ON refurbishment.idempotency_events (created_at);

-- =============================================================================
-- STEP 5: ALEMBIC MIGRATION TRACKING TABLE SYNCHRONIZATION
-- Stamping head revision '7f9cd19afe3f' guarantees Alembic CLI & flask db commands align
-- =============================================================================

CREATE TABLE IF NOT EXISTS refurbishment.alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

-- Idempotently stamp revision 7f9cd19afe3f
INSERT INTO refurbishment.alembic_version (version_num)
VALUES ('7f9cd19afe3f')
ON CONFLICT (version_num) DO NOTHING;

-- If an existing older version row is present, ensure it points to 7f9cd19afe3f
UPDATE refurbishment.alembic_version
SET version_num = '7f9cd19afe3f'
WHERE version_num != '7f9cd19afe3f';

-- =============================================================================
-- STEP 6: SUPABASE ROLES & PRIVILEGES (NON-DESTRUCTIVE)
-- Grants required privileges to standard Supabase roles and optional app role
-- =============================================================================

DO $$
BEGIN
    -- 1. Standard PostgreSQL / Supabase Admin Role
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
        GRANT USAGE, CREATE ON SCHEMA refurbishment TO postgres;
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA refurbishment TO postgres;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA refurbishment TO postgres;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON TABLES TO postgres;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON SEQUENCES TO postgres;
    END IF;

    -- 2. Supabase service_role (Used by Supabase Dashboard Table Editor & Storage hooks)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT USAGE ON SCHEMA refurbishment TO service_role;
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA refurbishment TO service_role;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA refurbishment TO service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON TABLES TO service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON SEQUENCES TO service_role;
    END IF;

    -- 3. Supabase authenticated role (Optional dashboard read/write if used)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT USAGE ON SCHEMA refurbishment TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA refurbishment TO authenticated;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA refurbishment TO authenticated;
    END IF;

    -- 4. Optional dedicated application role 'refurbishment_app' (if provisioned)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'refurbishment_app') THEN
        GRANT USAGE, CREATE ON SCHEMA refurbishment TO refurbishment_app;
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA refurbishment TO refurbishment_app;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA refurbishment TO refurbishment_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON TABLES TO refurbishment_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA refurbishment GRANT ALL PRIVILEGES ON SEQUENCES TO refurbishment_app;
    END IF;

    -- 5. Strict Partner Schema Isolation:
    -- Guarantee refurbishment_app has ZERO access to the partner 'collection' schema
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'collection')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'refurbishment_app') THEN
        REVOKE ALL ON SCHEMA collection FROM refurbishment_app;
        REVOKE ALL ON ALL TABLES IN SCHEMA collection FROM refurbishment_app;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA collection FROM refurbishment_app;
    END IF;
END $$;

-- =============================================================================
-- STEP 7: POST-EXECUTION VERIFICATION SUMMARY
-- Returns real-time diagnostic counts in Supabase SQL Editor results pane
-- =============================================================================

SELECT 
    'refurbishment' AS schema_name,
    COUNT(t.table_name) AS total_tables,
    (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'refurbishment') AS total_indexes,
    (SELECT version_num FROM refurbishment.alembic_version LIMIT 1) AS alembic_head_revision
FROM information_schema.tables t
WHERE t.table_schema = 'refurbishment';


-- =============================================================================
-- CIRCULAR REFURBISHMENT INTELLIGENCE — SUPABASE POSTGRESQL SCHEMA MIGRATION
-- Schema: refurbishment
-- Ownership: Refurbishment Intelligence Application
-- =============================================================================

-- 1. Create dedicated schema
CREATE SCHEMA IF NOT EXISTS refurbishment;

-- 2. Create tables within refurbishment schema
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

CREATE TABLE IF NOT EXISTS refurbishment.idempotency_events (
    idempotency_key VARCHAR(128) PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    device_id VARCHAR(64),
    transfer_id VARCHAR(64),
    response_payload TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

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

CREATE TABLE IF NOT EXISTS refurbishment.assessment_components (
    component_id SERIAL PRIMARY KEY,
    assessment_id VARCHAR(64) NOT NULL REFERENCES refurbishment.assessments(assessment_id) ON DELETE CASCADE,
    component_name VARCHAR(64) NOT NULL,
    condition VARCHAR(64) NOT NULL,
    recoverable BOOLEAN DEFAULT TRUE NOT NULL,
    estimated_value FLOAT DEFAULT 0.0 NOT NULL,
    notes VARCHAR(255)
);

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

CREATE TABLE IF NOT EXISTS refurbishment.reports (
    report_id VARCHAR(64) PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL REFERENCES refurbishment.devices(device_id) ON DELETE CASCADE,
    assessment_id VARCHAR(64) REFERENCES refurbishment.assessments(assessment_id) ON DELETE SET NULL,
    report_type VARCHAR(64) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

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

CREATE INDEX IF NOT EXISTS ix_refurbishment_transfers_idempotency_key 
    ON refurbishment.transfers (idempotency_key);

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
-- 3. Dedicated role privileges (Optional if using Supabase standard postgres user)
-- To create a dedicated role, provision the role with an administrator password first:
-- CREATE ROLE refurbishment_app WITH LOGIN PASSWORD '<STRONG_PASSWORD>';
-- =============================================================================

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

-- Ensure refurbishment_app cannot alter or query partner collection schema
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.schemata WHERE schema_name = 'collection')
       AND EXISTS (SELECT FROM pg_roles WHERE rolname = 'refurbishment_app') THEN
        REVOKE ALL ON SCHEMA collection FROM refurbishment_app;
        REVOKE ALL ON ALL TABLES IN SCHEMA collection FROM refurbishment_app;
    END IF;
END
$$;


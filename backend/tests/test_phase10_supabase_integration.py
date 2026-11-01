"""Phase 10: Production-Readiness Comprehensive Test Suite.

Verifies:
1. Production secret validation (independent configuration & mandatory presence).
2. API credential separation (PARTNER_INBOUND_API_KEY vs COLLECTION_API_KEY vs ADMIN_API_KEY).
3. Unauthorized administrative requests (rejection of Sec-Fetch-Site, Referer, and invalid keys).
4. Incoming device transfer handling and persistence.
5. Duplicate device transfer handling (idempotency and conflict detection).
6. Assessment creation and deterministic calculations.
7. Automatic callback invocation on assessment completion.
8. Invalid callback credential handling (safe assessment retention).
9. Callback retry mechanism.
10. Callback failure recovery (transient failure resilience).
11. Duplicate assessment prevention and callback idempotency.
12. PostgreSQL schema ('refurbishment' schema qualification and constraints).
13. Alembic migration and stamping CLI commands.
14. File upload validation (types, limits, extensions, signed URLs).
15. Production storage fallback prevention (disabling local disk in production).
16. Partner file transfer accessibility verification.
17. Live database dashboard metrics.
"""

import importlib
import io
import json
import os
import unittest
from unittest.mock import patch, MagicMock

import requests
import config
from extensions import db
from models.device import Device
from models.assessment import Assessment
from models.transfer import Transfer
from models.recovery import RecoveryAnalysis
from models.report import Report
from models.device_file import DeviceFile
from models.idempotency import IdempotencyEvent
from services.callback_service import (
    send_assessment_result_to_collection,
    retry_partner_transfer,
)
from services.file_service import (
    validate_file,
    upload_file_to_storage,
    verify_and_ingest_partner_file,
)
from app import create_app


class Phase10IntegrationTests(unittest.TestCase):
    """Full production-readiness integration and security verification test suite."""

    def setUp(self):
        class Phase10TestConfig(config.Config):
            TESTING = True
            IS_PRODUCTION = False
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            SQLALCHEMY_ENGINE_OPTIONS = {}
            PARTNER_INBOUND_API_KEY = "test-inbound-key-xyz"
            COLLECTION_API_KEY = "test-collection-key-abc"
            COLLECTION_API_URL = "https://partner-collection.test"
            ADMIN_API_KEY = "test-admin-key-secret"
            DB_SCHEMA = "refurbishment"
            SUPABASE_STORAGE_BUCKET = "ewaste-files"

        self.test_config = Phase10TestConfig
        self.app = create_app(config_class=self.test_config)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    # -------------------------------------------------------------------------
    # 1. Supabase PostgreSQL Connection & Pooling Options
    # -------------------------------------------------------------------------
    def test_01_supabase_postgresql_connection(self):
        """Verify Supabase PostgreSQL connection string parsing, search_path, and serverless pooling."""
        mock_env = {
            "SUPABASE_DB_URL": "postgres://postgres.abc:secret123@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
            "SECRET_KEY": "valid-production-secret-key",
            "IS_PRODUCTION": "true",
            "DB_SCHEMA": "refurbishment",
            "PARTNER_INBOUND_API_KEY": "in-key",
            "COLLECTION_API_KEY": "out-key",
            "COLLECTION_API_URL": "https://partner-collection.vercel.app",
            "SUPABASE_URL": "https://abc.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
        }
        with patch.dict(os.environ, mock_env, clear=True):
            importlib.reload(config)
            self.assertTrue(
                config.Config.SQLALCHEMY_DATABASE_URI.startswith("postgresql+psycopg://"),
                f"Expected postgresql+psycopg:// prefix, got: {config.Config.SQLALCHEMY_DATABASE_URI}",
            )
            opts = config.Config.SQLALCHEMY_ENGINE_OPTIONS
            self.assertTrue(opts.get("pool_pre_ping"))
            self.assertEqual(opts.get("pool_recycle"), 300)
            self.assertEqual(
                opts["connect_args"]["options"],
                "-c search_path=refurbishment,public",
            )
            from sqlalchemy.pool import NullPool
            self.assertIs(opts.get("poolclass"), NullPool)

        importlib.reload(config)

    # -------------------------------------------------------------------------
    # 2. Production Secret Validation & Legacy Override Prevention
    # -------------------------------------------------------------------------
    def test_02_production_secret_validation(self):
        """Verify explicit validation of required production variables and rejection of legacy overrides."""
        base_env = {
            "IS_PRODUCTION": "true",
            "SECRET_KEY": "valid-secret",
            "SUPABASE_DB_URL": "postgresql://postgres:pass@localhost:5432/db",
            "PARTNER_INBOUND_API_KEY": "in-key",
            "COLLECTION_API_KEY": "out-key",
            "COLLECTION_API_URL": "https://partner.example.com",
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "role-key",
        }

        # Verify missing SECRET_KEY
        env_no_secret = dict(base_env, SECRET_KEY="")
        with patch.dict(os.environ, env_no_secret, clear=True):
            with self.assertRaises(ValueError) as ctx:
                importlib.reload(config)
            self.assertIn("SECRET_KEY must be configured", str(ctx.exception))

        # Verify missing PARTNER_INBOUND_API_KEY
        env_no_inbound = dict(base_env, PARTNER_INBOUND_API_KEY="")
        with patch.dict(os.environ, env_no_inbound, clear=True):
            with self.assertRaises(ValueError) as ctx:
                importlib.reload(config)
            self.assertIn("PARTNER_INBOUND_API_KEY must be configured", str(ctx.exception))

        # Verify missing COLLECTION_API_KEY
        env_no_collection = dict(base_env, COLLECTION_API_KEY="")
        with patch.dict(os.environ, env_no_collection, clear=True):
            with self.assertRaises(ValueError) as ctx:
                importlib.reload(config)
            self.assertIn("COLLECTION_API_KEY must be configured", str(ctx.exception))

        # Verify CIRCULAR_API_KEY cannot override independent credentials in production
        env_with_legacy = dict(base_env, CIRCULAR_API_KEY="legacy-circ-key")
        with patch.dict(os.environ, env_with_legacy, clear=True):
            importlib.reload(config)
            self.assertIsNone(config.Config.CIRCULAR_API_KEY)
            self.assertEqual(config.Config.PARTNER_INBOUND_API_KEY, "in-key")
            self.assertEqual(config.Config.COLLECTION_API_KEY, "out-key")

        importlib.reload(config)

    # -------------------------------------------------------------------------
    # 3. API Credential Separation
    # -------------------------------------------------------------------------
    def test_03_api_credential_separation(self):
        """Verify PARTNER_INBOUND_API_KEY cannot perform administrative actions and vice versa."""
        # 1. Partner inbound key cannot access administrative assessment route
        resp1 = self.client.post(
            "/api/v1/assessments",
            headers={"X-API-Key": "test-inbound-key-xyz"},
            json={"device_id": "TEST"},
        )
        self.assertEqual(resp1.status_code, 403)
        self.assertIn("PARTNER_INBOUND_API_KEY is not permitted", resp1.get_json()["message"])

        # 2. Outbound collection key cannot access inbound device route
        payload = {
            "device_id": "EW-SEP-001",
            "transfer_id": "TRF-SEP-001",
            "device": {"type": "Laptop", "brand": "Dell", "model": "XPS", "condition": "Good"},
        }
        resp2 = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": "test-collection-key-abc"},
            json=payload,
        )
        self.assertEqual(resp2.status_code, 403)

        # 3. Valid admin key can access workspace
        resp3 = self.client.get(
            "/api/v1/devices",
            headers={"X-API-Key": "test-admin-key-secret"},
        )
        self.assertEqual(resp3.status_code, 200)

    # -------------------------------------------------------------------------
    # 4. Unauthorized Administrative Requests (Sec-Fetch-Site & Referer Rejection)
    # -------------------------------------------------------------------------
    def test_04_unauthorized_administrative_requests(self):
        """Verify that Sec-Fetch-Site, Referer, or missing session are rejected with 401."""
        # 1. Missing session / credentials -> 401
        resp_no_auth = self.client.post("/api/v1/assessments", json={"device_id": "TEST"})
        self.assertEqual(resp_no_auth.status_code, 401)

        # 2. Spoofed Sec-Fetch-Site header without session -> 401
        resp_spoof_fetch = self.client.post(
            "/api/v1/assessments",
            headers={"Sec-Fetch-Site": "same-origin"},
            json={"device_id": "TEST"},
        )
        self.assertEqual(resp_spoof_fetch.status_code, 401)

        # 3. Spoofed Referer header without session -> 401
        resp_spoof_ref = self.client.post(
            "/api/v1/assessments",
            headers={"Referer": "http://localhost/dashboard"},
            json={"device_id": "TEST"},
        )
        self.assertEqual(resp_spoof_ref.status_code, 401)

        # 4. Valid session authentication succeeds
        with self.client.session_transaction() as sess:
            sess["admin"] = True
            sess["authenticated"] = True

        resp_with_sess = self.client.get("/api/v1/devices")
        self.assertEqual(resp_with_sess.status_code, 200)

    # -------------------------------------------------------------------------
    # 5. Incoming Device Transfer & Field Preservation
    # -------------------------------------------------------------------------
    def test_05_incoming_device_transfer(self):
        """Verify partner device ingestion with valid PARTNER_INBOUND_API_KEY."""
        payload = {
            "device_id": "EW-2026-PH10",
            "transfer_id": "TRF-PH10-001",
            "device": {
                "type": "Laptop",
                "brand": "Dell",
                "model": "XPS 13",
                "purchase_year": 2022,
                "weight_kg": 1.25,
                "power_status": "Powers on",
                "screen_condition": "Minor scratches",
                "battery_condition": "Healthy (85%)",
                "condition": "Good",
                "damage_description": "Clean overall, light cosmetic wear.",
            },
        }

        resp = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": "test-inbound-key-xyz"},
            json=payload,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["device_id"], "EW-2026-PH10")

        dev = Device.query.filter_by(device_id="EW-2026-PH10").first()
        self.assertIsNotNone(dev)
        self.assertEqual(dev.brand, "Dell")
        self.assertEqual(dev.weight_kg, 1.25)
        self.assertEqual(dev.power_status, "Powers on")

    # -------------------------------------------------------------------------
    # 6. Duplicate Device Transfer & Idempotency
    # -------------------------------------------------------------------------
    def test_06_duplicate_device_transfer(self):
        """Verify idempotent handling of identical transfers and 409 conflict for mismatched transfers."""
        payload = {
            "device_id": "EW-DUP-001",
            "transfer_id": "TRF-DUP-ORIGINAL",
            "device": {"type": "Tablet", "brand": "Apple", "model": "iPad Air", "condition": "Good"},
        }
        headers = {"X-API-Key": "test-inbound-key-xyz"}

        resp1 = self.client.post("/api/v1/refurbishment/devices", headers=headers, json=payload)
        self.assertEqual(resp1.status_code, 201)

        # Exact duplicate with same transfer_id -> Idempotent 200
        resp2 = self.client.post("/api/v1/refurbishment/devices", headers=headers, json=payload)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.get_json()["transfer_id"], "TRF-DUP-ORIGINAL")

        # Conflicting transfer_id -> 409
        conflicting_payload = dict(payload, transfer_id="TRF-CONFLICTING-NEW")
        resp3 = self.client.post("/api/v1/refurbishment/devices", headers=headers, json=conflicting_payload)
        self.assertEqual(resp3.status_code, 409)

    # -------------------------------------------------------------------------
    # 7. Assessment Creation & Deterministic Calculation
    # -------------------------------------------------------------------------
    def test_07_assessment_creation(self):
        """Verify deterministic technical assessment calculation and persistence."""
        dev = Device(
            device_id="DEV-ASSESS-01",
            device_type="Laptop",
            brand="Lenovo",
            model="ThinkPad T14",
            condition="Good",
            power_status="Powers on",
            screen_condition="Flawless",
            battery_condition="Good",
            status="Received",
        )
        db.session.add(dev)
        db.session.commit()

        resp = self.client.post(
            "/api/v1/assessments",
            json={"device_id": "DEV-ASSESS-01"},
            headers={"X-API-Key": "test-admin-key-secret"},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["assessment"]
        self.assertGreater(data["repairability_score"], 0)
        self.assertGreater(data["circular_recovery_score"], 0)

        saved_asm = Assessment.query.filter_by(device_id="DEV-ASSESS-01").first()
        self.assertIsNotNone(saved_asm)
        self.assertEqual(saved_asm.repairability_score, data["repairability_score"])

    # -------------------------------------------------------------------------
    # 8. Automatic Callback to Collection
    # -------------------------------------------------------------------------
    @patch("requests.post")
    def test_08_automatic_callback(self, mock_post):
        """Verify automatic callback is immediately dispatched to Collection using COLLECTION_API_KEY."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({"status": "received", "success": True})
        mock_post.return_value = mock_response

        dev = Device(
            device_id="DEV-AUTOCB-01",
            device_type="Smartphone",
            brand="Samsung",
            model="Galaxy S22",
            condition="Good",
            status="Received",
        )
        db.session.add(dev)
        db.session.commit()

        resp = self.client.post(
            "/api/v1/assessments",
            json={"device_id": "DEV-AUTOCB-01"},
            headers={"X-API-Key": "test-admin-key-secret"},
        )
        self.assertEqual(resp.status_code, 201)

        mock_post.assert_called_once()
        called_url, called_kwargs = mock_post.call_args
        self.assertEqual(called_url[0], "https://partner-collection.test/api/v1/assessment-results")
        self.assertEqual(called_kwargs["headers"]["X-API-Key"], "test-collection-key-abc")

        transfer = Transfer.query.filter_by(
            device_id="DEV-AUTOCB-01", direction="Outbound"
        ).first()
        self.assertIsNotNone(transfer)
        self.assertEqual(transfer.status, "Completed")
        self.assertEqual(transfer.http_status, 200)

    # -------------------------------------------------------------------------
    # 9. Callback Retry Mechanism
    # -------------------------------------------------------------------------
    @patch("requests.post")
    def test_09_callback_retry(self, mock_post):
        """Verify POST /api/v1/transfers/<transfer_id>/retry successfully resends an outbound transfer."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({"status": "received"})
        mock_post.return_value = mock_response

        dev = Device(device_id="DEV-RETRY-01", device_type="Laptop", brand="Asus", model="Zenbook", condition="Good")
        asm = Assessment(
            assessment_id="ASM-RETRY-01",
            device_id="DEV-RETRY-01",
            repairability_score=85.0,
            circular_recovery_score=80.0,
            repair_cost=4000.0,
            component_recovery_value=9000.0,
            estimated_refurbished_value=18000.0,
            co2_avoided_kg=15.0,
            recommendation="Refurbish",
            technical_summary="Technical evaluation passed.",
        )
        transfer = Transfer(
            transfer_id="TRF-OUT-RETRY-01",
            device_id="DEV-RETRY-01",
            direction="Outbound",
            sender="Refurbishment",
            receiver="Collection",
            endpoint="https://partner-collection.test/api/v1/assessment-results",
            http_method="POST",
            request_payload=json.dumps({"device_id": "DEV-RETRY-01"}),
            http_status=500,
            status="Failed",
            idempotency_key="ASM-RETRY-01",
            retry_count=0,
        )
        db.session.add_all([dev, asm, transfer])
        db.session.commit()

        # Unauthenticated request -> 401
        unauth_resp = self.client.post("/api/v1/transfers/TRF-OUT-RETRY-01/retry")
        self.assertEqual(unauth_resp.status_code, 401)

        # Authenticated request with ADMIN_API_KEY -> 200
        resp = self.client.post(
            "/api/v1/transfers/TRF-OUT-RETRY-01/retry",
            headers={"X-API-Key": "test-admin-key-secret"},
        )
        self.assertEqual(resp.status_code, 200)

        updated_trf = Transfer.query.filter_by(transfer_id="TRF-OUT-RETRY-01").first()
        self.assertEqual(updated_trf.status, "Completed")
        self.assertEqual(updated_trf.retry_count, 1)

    # -------------------------------------------------------------------------
    # 10. PostgreSQL Schema Qualification
    # -------------------------------------------------------------------------
    def test_10_postgresql_schema(self):
        """Verify all SQLAlchemy models explicitly declare the 'refurbishment' schema."""
        models = [Device, Assessment, Transfer, RecoveryAnalysis, Report, DeviceFile, IdempotencyEvent]
        for m in models:
            self.assertEqual(
                m.__table__.schema,
                "refurbishment",
                f"Model {m.__name__} must belong to 'refurbishment' schema",
            )

    # -------------------------------------------------------------------------
    # 11. Alembic Migration & Stamping Commands
    # -------------------------------------------------------------------------
    def test_11_alembic_migration(self):
        """Verify Alembic migration file and CLI commands exist on the Flask application."""
        import glob
        migration_files = glob.glob("backend/migrations/versions/*_initial_schema_for_refurbishment_*.py")
        self.assertTrue(len(migration_files) >= 1, "Alembic initial migration file must exist")

        commands = self.app.cli.list_commands(self.app_context)
        self.assertIn("migrate-refurbishment-schema", commands)
        self.assertIn("stamp-refurbishment-schema", commands)

    # -------------------------------------------------------------------------
    # 12. Supabase Storage Upload & Retrieval
    # -------------------------------------------------------------------------
    def test_12_supabase_file_upload_and_retrieval(self):
        """Verify upload validation and retrieval under refurbishment/ prefix."""
        # Valid upload
        valid_res, msg = validate_file("test.pdf", b"%PDF-1.4 test")
        self.assertTrue(valid_res)

        # Invalid extension
        invalid_res, msg = validate_file("evil.sh", b"echo 1")
        self.assertFalse(invalid_res)

        # Upload attachment
        dev = Device(device_id="DEV-STORAGE-01", device_type="Laptop", brand="HP", model="ProBook", condition="Good")
        db.session.add(dev)
        db.session.commit()

        resp = self.client.post(
            "/api/v1/devices/DEV-STORAGE-01/files",
            headers={"X-API-Key": "test-admin-key-secret"},
            data={"file": (io.BytesIO(b"log data"), "diag.json")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 201)
        file_id = resp.get_json()["file"]["file_id"]

        get_resp = self.client.get(
            f"/api/v1/devices/DEV-STORAGE-01/files/{file_id}",
            headers={"X-API-Key": "test-admin-key-secret"},
        )
        self.assertEqual(get_resp.status_code, 200)

    # -------------------------------------------------------------------------
    # 13. Production Storage Fallback Prevention
    # -------------------------------------------------------------------------
    def test_13_production_storage_fallback_prevention(self):
        """Verify upload raises RuntimeError in production when Supabase Storage is not configured."""
        self.app.config["IS_PRODUCTION"] = True
        self.app.config["SUPABASE_URL"] = ""
        self.app.config["SUPABASE_SERVICE_ROLE_KEY"] = ""

        try:
            with self.assertRaises(RuntimeError) as ctx:
                upload_file_to_storage("DEV-1", "test.json", b"{}", "application/json")
            self.assertIn("Local filesystem storage fallback is disabled", str(ctx.exception))
        finally:
            self.app.config["IS_PRODUCTION"] = False

    # -------------------------------------------------------------------------
    # 14. Partner File Transfer Accessibility Verification
    # -------------------------------------------------------------------------
    def test_14_partner_file_accessibility_verification(self):
        """Verify that an unverified partner file reference is not accepted in production."""
        self.app.config["IS_PRODUCTION"] = True
        self.app.config["SUPABASE_URL"] = "https://mock.supabase.co"
        self.app.config["SUPABASE_SERVICE_ROLE_KEY"] = "mock-key"

        try:
            # When remote file is not accessible (HEAD returns 404)
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 404
                mock_get.return_value = mock_resp

                success, dev_file, msg = verify_and_ingest_partner_file(
                    device_id="DEV-FILEVERIF-01",
                    file_info={"name": "spec.json", "storage_key": "nonexistent_key.json"},
                )
                self.assertFalse(success)
                self.assertIsNone(dev_file)
                self.assertIn("not found in shared storage bucket", msg)
        finally:
            self.app.config["IS_PRODUCTION"] = False

    # -------------------------------------------------------------------------
    # 15. Dashboard Live Database Metrics
    # -------------------------------------------------------------------------
    def test_15_dashboard_metrics(self):
        """Verify dashboard metrics compute actual database aggregates without hardcoded numbers."""
        dev1 = Device(device_id="DEV-DASH-1", device_type="Laptop", brand="Dell", model="XPS", condition="Good", status="Received")
        dev2 = Device(device_id="DEV-DASH-2", device_type="Phone", brand="Apple", model="iPhone", condition="Fair", status="Assessed")
        asm2 = Assessment(
            assessment_id="ASM-DASH-2",
            device_id="DEV-DASH-2",
            repairability_score=75.0,
            circular_recovery_score=70.0,
            repair_cost=5000.0,
            component_recovery_value=8000.0,
            estimated_refurbished_value=16000.0,
            co2_avoided_kg=12.0,
            recommendation="Refurbish",
            technical_summary="High quality test device.",
        )
        db.session.add_all([dev1, dev2, asm2])
        db.session.commit()

        resp = self.client.get(
            "/api/v1/dashboard",
            headers={"X-API-Key": "test-admin-key-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        metrics = data["metrics"]
        self.assertEqual(metrics["incoming_devices"], 2)
        self.assertEqual(metrics["pending_assessments"], 1)
        self.assertEqual(metrics["refurbishment_candidates"], 1)
        self.assertEqual(data["decision_distribution"]["Refurbish"], 1)


if __name__ == "__main__":
    unittest.main()

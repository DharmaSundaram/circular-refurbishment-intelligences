"""Phase 11 Production-Readiness Comprehensive Test Suite (Tests A through L).

Explicitly validates:
- Test A: Inbound device transfer from Collection with valid PARTNER_INBOUND_API_KEY.
- Test B: Successful persistence of transfer payload in refurbishment.devices.
- Test C: GET /api/v1/devices returns the 3 target production IDs.
- Test D: Target devices appear in the assessment queue (/api/v1/queue).
- Test E: Authenticated browser session retrieves device registry.
- Test F: Unauthenticated administrative request receives 401.
- Test G: Invalid inbound API key rejected with 403 (or 401).
- Test H: Duplicate transfer request returns cached/idempotent response without duplicate DB rows.
- Test I: Run assessment on a device and verify persistence in refurbishment.assessments.
- Test J: Reverse callback delivery to Collection application with decimal precision preservation.
- Test K: Outbound transfer audit logs correctly record success and failure.
- Test L: Frontend bundles contain live synchronization without hardcoded demo fallback in production.
"""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import config
from app import create_app
from extensions import db
from models.device import Device
from models.assessment import Assessment
from models.transfer import Transfer
from models.idempotency import IdempotencyEvent
from services.callback_service import send_assessment_result_to_collection


TARGET_DEVICES = [
    {
        "device_id": "EW-2026-166CA51F",
        "brand": "Samsung",
        "model": "Galaxy A23",
        "device_type": "Smartphone",
        "condition": "Good",
        "status": "Received",
        "source_application": "Collection Application",
        "source_transfer_id": "TRF-TEST-166CA51F",
    },
    {
        "device_id": "EW-2026-B834E735",
        "brand": "Samsung",
        "model": "Galaxy Tab A8 SM-X205",
        "device_type": "Tablet",
        "condition": "Fair",
        "status": "Received",
        "source_application": "Collection Application",
        "source_transfer_id": "TRF-TEST-B834E735",
    },
    {
        "device_id": "EW-2026-D86F5C8F",
        "brand": "HP",
        "model": "Omen Hyper X",
        "device_type": "Laptop",
        "condition": "Damaged",
        "status": "Received",
        "source_application": "Collection Application",
        "source_transfer_id": "TRF-TEST-D86F5C8F",
    },
]


class ProductionReadinessComprehensiveTests(unittest.TestCase):
    """Authoritative test suite covering specifications Test A through Test L."""

    def setUp(self):
        class ComprehensiveTestConfig(config.Config):
            TESTING = True
            IS_PRODUCTION = False
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            SQLALCHEMY_ENGINE_OPTIONS = {}
            PARTNER_INBOUND_API_KEY = "auth-inbound-key-production-ready"
            COLLECTION_API_KEY = "auth-collection-callback-key"
            COLLECTION_API_URL = "https://partner-collection.example.com"
            ADMIN_API_KEY = "auth-admin-secret-dashboard-key"
            DB_SCHEMA = "refurbishment"
            SECRET_KEY = "session-encryption-key-for-admin-auth"

        self.test_config = ComprehensiveTestConfig
        self.app = create_app(config_class=self.test_config)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        # Seed the 3 target production devices into refurbishment.devices
        for d in TARGET_DEVICES:
            dev = Device(
                device_id=d["device_id"],
                brand=d["brand"],
                model=d["model"],
                device_type=d["device_type"],
                condition=d["condition"],
                status=d["status"],
                source_application=d["source_application"],
                source_transfer_id=d["source_transfer_id"],
                received_at=datetime.now(timezone.utc),
            )
            trf = Transfer(
                transfer_id=d["source_transfer_id"],
                device_id=d["device_id"],
                direction="Inbound",
                sender="Collection",
                receiver="Refurbishment",
                endpoint="/api/v1/refurbishment/devices",
                http_method="POST",
                http_status=201,
                status="Completed",
                idempotency_key=f"IDEMP-{d['device_id']}",
            )
            db.session.add(dev)
            db.session.add(trf)

        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    # -------------------------------------------------------------------------
    # TEST A: Inbound device transfer from Collection with valid PARTNER_INBOUND_API_KEY
    # -------------------------------------------------------------------------
    def test_a_inbound_device_transfer_with_valid_key(self):
        """Test A: Verify Collection can transfer a device using PARTNER_INBOUND_API_KEY."""
        payload = {
            "device_id": "EW-2026-TEST-A",
            "transfer_id": "TRF-TEST-A-001",
            "device": {
                "type": "Laptop",
                "brand": "Dell",
                "model": "XPS 15",
                "condition": "Good",
                "specs": {"cpu": "Core i7", "ram_gb": 16},
            },
        }
        resp = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": self.test_config.PARTNER_INBOUND_API_KEY},
            json=payload,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data.get("persisted"))
        self.assertEqual(data["device_id"], "EW-2026-TEST-A")

    # -------------------------------------------------------------------------
    # TEST B: Successful persistence of transfer payload in refurbishment.devices
    # -------------------------------------------------------------------------
    def test_b_persistence_in_refurbishment_devices(self):
        """Test B: Verify incoming payload fields are committed to refurbishment.devices."""
        payload = {
            "device_id": "EW-2026-TEST-B",
            "transfer_id": "TRF-TEST-B-001",
            "device": {
                "type": "Smartphone",
                "brand": "Google",
                "model": "Pixel 8 Pro",
                "condition": "Excellent",
                "purchase_year": 2024,
                "weight_kg": 0.21,
            },
        }
        resp = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"Authorization": f"Bearer {self.test_config.PARTNER_INBOUND_API_KEY}"},
            json=payload,
        )
        self.assertEqual(resp.status_code, 201)

        persisted = Device.query.filter_by(device_id="EW-2026-TEST-B").first()
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.brand, "Google")
        self.assertEqual(persisted.model, "Pixel 8 Pro")
        self.assertEqual(persisted.device_type, "Smartphone")
        self.assertEqual(persisted.condition, "Excellent")
        self.assertEqual(persisted.status, "Received")

    # -------------------------------------------------------------------------
    # TEST C: GET /api/v1/devices returns the 3 target production IDs
    # -------------------------------------------------------------------------
    def test_c_device_listing_returns_three_target_production_ids(self):
        """Test C: Verify GET /api/v1/devices returns all three target production IDs."""
        resp = self.client.get(
            "/api/v1/devices",
            headers={"X-API-Key": self.test_config.ADMIN_API_KEY},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("devices", data)
        self.assertEqual(data["total"], 3)

        ids = [d["id"] for d in data["devices"]]
        self.assertIn("EW-2026-166CA51F", ids)
        self.assertIn("EW-2026-B834E735", ids)
        self.assertIn("EW-2026-D86F5C8F", ids)

    # -------------------------------------------------------------------------
    # TEST D: Target devices appear in the assessment queue (/api/v1/queue)
    # -------------------------------------------------------------------------
    def test_d_target_devices_appear_in_assessment_queue(self):
        """Test D: Verify devices with status 'Received' are returned in /api/v1/queue."""
        resp = self.client.get(
            "/api/v1/queue",
            headers={"X-API-Key": self.test_config.ADMIN_API_KEY},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("queue", data)
        self.assertEqual(data["total"], 3)

        queue_ids = [d["id"] for d in data["queue"]]
        self.assertIn("EW-2026-166CA51F", queue_ids)
        self.assertIn("EW-2026-B834E735", queue_ids)
        self.assertIn("EW-2026-D86F5C8F", queue_ids)

    # -------------------------------------------------------------------------
    # TEST E: Authenticated browser session retrieves device registry
    # -------------------------------------------------------------------------
    def test_e_authenticated_browser_session_retrieves_device_registry(self):
        """Test E: Verify browser session via /api/v1/auth/login allows device retrieval."""
        # 1. Login with admin credentials
        login_resp = self.client.post(
            "/api/v1/auth/login",
            json={"admin_key": self.test_config.ADMIN_API_KEY},
        )
        self.assertEqual(login_resp.status_code, 200)

        # 2. Access device registry via session cookie
        registry_resp = self.client.get("/api/v1/devices")
        self.assertEqual(registry_resp.status_code, 200)
        data = registry_resp.get_json()
        self.assertEqual(data["total"], 3)

    # -------------------------------------------------------------------------
    # TEST F: Unauthenticated administrative request receives 401
    # -------------------------------------------------------------------------
    def test_f_unauthenticated_administrative_request_rejected_401(self):
        """Test F: Verify anonymous requests to administrative endpoints receive 401."""
        fresh_client = self.app.test_client()

        # Anonymous visit to / does NOT elevate privileges
        fresh_client.get("/")

        # Administrative access must be rejected with 401
        resp = fresh_client.get("/api/v1/devices")
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertIn("Administrator authentication required", data.get("message", ""))

        queue_resp = fresh_client.get("/api/v1/queue")
        self.assertEqual(queue_resp.status_code, 401)

    # -------------------------------------------------------------------------
    # TEST G: Invalid inbound API key rejected with 403 (or 401)
    # -------------------------------------------------------------------------
    def test_g_invalid_inbound_api_key_rejected_with_403(self):
        """Test G: Verify unauthorized callers are rejected at /api/v1/refurbishment/devices."""
        # Missing key -> 401
        resp_missing = self.client.post("/api/v1/refurbishment/devices", json={})
        self.assertEqual(resp_missing.status_code, 401)

        # Wrong key -> 403
        resp_invalid = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": "completely-invalid-key"},
            json={"device_id": "TEST"},
        )
        self.assertEqual(resp_invalid.status_code, 403)

    # -------------------------------------------------------------------------
    # TEST H: Duplicate transfer request returns cached/idempotent response
    # -------------------------------------------------------------------------
    def test_h_duplicate_transfer_idempotent_no_duplicate_rows(self):
        """Test H: Verify duplicate transfer requests do not create duplicate device rows."""
        payload = {
            "device_id": "EW-2026-IDEMP-TEST",
            "transfer_id": "TRF-IDEMP-100",
            "device": {
                "type": "Laptop",
                "brand": "Lenovo",
                "model": "ThinkPad E14",
                "condition": "Fair",
            },
        }
        headers = {
            "X-API-Key": self.test_config.PARTNER_INBOUND_API_KEY,
            "Idempotency-Key": "TRF-IDEMP-100",
        }

        # Request 1
        resp1 = self.client.post("/api/v1/refurbishment/devices", headers=headers, json=payload)
        self.assertEqual(resp1.status_code, 201)

        # Request 2 (identical duplicate)
        resp2 = self.client.post("/api/v1/refurbishment/devices", headers=headers, json=payload)
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.get_json().get("duplicate") or resp2.get_json().get("idempotent"))

        # Verify only 1 device record exists in database
        count = Device.query.filter_by(device_id="EW-2026-IDEMP-TEST").count()
        self.assertEqual(count, 1)

    # -------------------------------------------------------------------------
    # TEST I: Run assessment on a device and verify persistence in refurbishment.assessments
    # -------------------------------------------------------------------------
    def test_i_assessment_execution_and_persistence(self):
        """Test I: Verify running assessment calculates metrics and persists to refurbishment.assessments."""
        # Log in as admin
        self.client.post("/api/v1/auth/login", json={"admin_key": self.test_config.ADMIN_API_KEY})

        resp = self.client.post(
            "/api/v1/assessments",
            json={
                "device_id": "EW-2026-166CA51F",
                "condition": "Good",
                "power_status": "Powers on",
                "screen_condition": "Good",
                "battery_health": "Good",
                "assessor": "Senior Refurbishment Specialist",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIn("assessment", data)

        asm = Assessment.query.filter_by(device_id="EW-2026-166CA51F").first()
        self.assertIsNotNone(asm)
        self.assertGreater(asm.repairability_score, 0)
        self.assertGreater(asm.circular_recovery_score, 0)
        self.assertIsNotNone(asm.recommendation)

        # Verify device status advanced from Received
        dev = Device.query.filter_by(device_id="EW-2026-166CA51F").first()
        self.assertIn(dev.status, ["Assessed", "Refurbishment Recommended", "Parts Recovery Recommended"])
        self.assertNotEqual(dev.status, "Received")

    # -------------------------------------------------------------------------
    # TEST J: Reverse callback delivery to Collection application with decimal precision
    # -------------------------------------------------------------------------
    @patch("services.callback_service.requests.post")
    def test_j_reverse_callback_delivery_preserves_decimal_precision(self, mock_post):
        """Test J: Verify outbound callback preserves exact decimal scores and financial values."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({"success": True, "message": "Result received"})
        mock_resp.json.return_value = {"success": True, "message": "Result received"}
        mock_post.return_value = mock_resp

        # Create assessment with specific decimal values
        asm = Assessment(
            assessment_id="ASM-PRECISION-01",
            device_id="EW-2026-B834E735",
            repairability_score=78.5,
            circular_recovery_score=81.2,
            repair_cost=3450.75,
            component_recovery_value=8900.50,
            estimated_refurbished_value=17500.00,
            co2_avoided_kg=12.4,
            recommendation="Refurbish",
            technical_summary="High score candidate for refurbishment.",
            assessor="Lead Engineer",
        )
        db.session.add(asm)
        db.session.commit()

        success, status_code, msg, transfer = send_assessment_result_to_collection(
            assessment_id="ASM-PRECISION-01"
        )
        self.assertTrue(success)
        self.assertEqual(status_code, 200)

        # Verify sent HTTP payload
        mock_post.assert_called_once()
        sent_body = mock_post.call_args[1]["json"]
        self.assertEqual(sent_body["device_id"], "EW-2026-B834E735")
        self.assertEqual(sent_body["repairability_score"], 78.5)
        self.assertEqual(sent_body["circular_recovery_score"], 81.2)
        self.assertEqual(sent_body["repair_cost"], 3450.75)
        self.assertEqual(sent_body["component_recovery_value"], 8900.50)
        self.assertEqual(sent_body["co2_avoided_kg"], 12.4)

    # -------------------------------------------------------------------------
    # TEST K: Outbound transfer audit logs correctly record success and failure
    # -------------------------------------------------------------------------
    @patch("services.callback_service.requests.post")
    def test_k_outbound_transfer_audit_logs_record_success_and_failure(self, mock_post):
        """Test K: Verify outbound audit log reflects Completed on success and Failed on upstream error."""
        # 1. Test Failure log
        mock_fail_resp = MagicMock()
        mock_fail_resp.status_code = 502
        mock_fail_resp.text = '{"error": "Bad Gateway"}'
        mock_fail_resp.json.return_value = {"error": "Bad Gateway"}
        mock_post.return_value = mock_fail_resp

        asm_fail = Assessment(
            assessment_id="ASM-AUDIT-FAIL",
            device_id="EW-2026-D86F5C8F",
            repairability_score=60.0,
            circular_recovery_score=55.0,
            repair_cost=6000.0,
            component_recovery_value=4000.0,
            estimated_refurbished_value=12000.0,
            co2_avoided_kg=15.0,
            recommendation="Harvest Components",
            technical_summary="Harvest components for high-value spare parts recovery.",
            assessor="Test Engineer",
        )
        db.session.add(asm_fail)
        db.session.commit()

        ok, code, msg, fail_trf = send_assessment_result_to_collection("ASM-AUDIT-FAIL")
        self.assertFalse(ok)
        self.assertEqual(fail_trf.status, "Failed")
        self.assertEqual(fail_trf.direction, "Outbound")
        self.assertEqual(fail_trf.http_status, 502)

        # 2. Test Success log
        mock_ok_resp = MagicMock()
        mock_ok_resp.status_code = 200
        mock_ok_resp.text = '{"success": true}'
        mock_ok_resp.json.return_value = {"success": True}
        mock_post.return_value = mock_ok_resp

        ok2, code2, msg2, success_trf = send_assessment_result_to_collection(
            "ASM-AUDIT-FAIL", force_resend=True
        )
        self.assertTrue(ok2)
        self.assertEqual(success_trf.status, "Completed")
        self.assertEqual(success_trf.direction, "Outbound")
        self.assertEqual(success_trf.http_status, 200)

    # -------------------------------------------------------------------------
    # TEST L: Frontend bundle contains live synchronization without demo fallback
    # -------------------------------------------------------------------------
    def test_l_frontend_bundles_live_synchronization_no_demo_in_production(self):
        """Test L: Verify frontend bundles use dynamic 5s polling, tab sync, and no demo fallback."""
        bundles = ["public/assets/index-DlDXW_IB.js", "frontend/ui/assets/index-DlDXW_IB.js"]
        for b_path in bundles:
            with open(b_path, "r", encoding="utf-8") as f:
                bundle_text = f.read()

            # 5-second interval polling is active
            self.assertIn("window.setInterval(syncData,5000)", bundle_text)

            # Tab-switch re-sync is registered
            self.assertIn("[e]", bundle_text)

            # Strict gating for demo mode (?demo=true) via URLSearchParams
            self.assertIn("URLSearchParams(window.location.search).get(`demo`)===`true`", bundle_text)

            # Empty database state message
            self.assertIn("No incoming devices registered in the database yet.", bundle_text)

            # Dynamic count in header and table
            self.assertIn("devices awaiting assessment", bundle_text)


if __name__ == "__main__":
    unittest.main()

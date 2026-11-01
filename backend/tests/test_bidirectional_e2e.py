"""End-to-End Bidirectional API Communication and Session Verification Tests.

Verifies:
1. Inbound device transfer from Collection (POST /api/v1/refurbishment/devices)
2. Inbound transfer duplicate idempotency handling
3. Inbound transfer authentication rejection
4. UI session seeding on root page load (GET /)
5. UI device registry retrieval via session cookie (GET /api/v1/devices)
6. Outbound assessment callback dispatch (POST /api/v1/assessment-results/send)
7. Float/decimal score precision preservation in outbound payload
8. UI resend assessment authentication protection
"""

import unittest
from unittest.mock import patch, MagicMock
from config import Config
from extensions import db
from models.device import Device
from models.assessment import Assessment
from models.transfer import Transfer
from models.idempotency import IdempotencyEvent
from app import create_app


class BidirectionalE2ETests(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            PARTNER_INBOUND_API_KEY = "test-partner-inbound-key"
            COLLECTION_API_KEY = "test-collection-callback-key"
            COLLECTION_API_URL = "https://partner-collection.example.com"
            SECRET_KEY = "test-session-secret-key-32-chars-ok"
            ADMIN_API_KEY = "test-session-admin-key"

        self.app = create_app(config_class=TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.inbound_key = "test-partner-inbound-key"
        self.callback_key = "test-collection-callback-key"

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_01_inbound_device_transfer_success(self):
        """Verify device transfer from Collection registers device and file metadata."""
        payload = {
            "device_id": "EW-2026-E2E-01",
            "transfer_id": "TRF-E2E-01",
            "device": {
                "id": "EW-2026-E2E-01",
                "name": "HP EliteBook 840 G8",
                "type": "Laptop",
                "brand": "HP",
                "model": "EliteBook 840 G8",
                "condition": "Good",
                "power_status": "Powers on",
                "screen_condition": "Flawless",
                "battery_condition": "Good",
                "weight_kg": 1.4,
                "damage_description": "Minor scratch on bottom cover.",
            },
            "files": [
                {
                    "name": "hardware_diagnostic.json",
                    "type": "diagnostic",
                    "storage_key": "collection/devices/EW-2026-E2E-01/diagnostic.json",
                }
            ],
        }

        resp = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": self.inbound_key, "Content-Type": "application/json"},
            json=payload,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["device_id"], "EW-2026-E2E-01")
        self.assertTrue(data.get("persisted"))

        # Verify device in DB
        dev = Device.query.filter_by(device_id="EW-2026-E2E-01").first()
        self.assertIsNotNone(dev)
        self.assertEqual(dev.model, "EliteBook 840 G8")

    def test_02_inbound_device_transfer_duplicate_idempotency(self):
        """Verify replaying the same transfer returns 200 with idempotent: True."""
        payload = {
            "device_id": "EW-2026-E2E-IDEMP",
            "transfer_id": "TRF-E2E-IDEMP",
            "device": {
                "id": "EW-2026-E2E-IDEMP",
                "name": "Dell XPS 13",
                "type": "Laptop",
                "brand": "Dell",
                "model": "XPS 13 9310",
                "condition": "Good",
            },
        }

        # First call
        r1 = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={
                "X-API-Key": self.inbound_key,
                "Idempotency-Key": "TRF-E2E-IDEMP",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        self.assertEqual(r1.status_code, 201)

        # Second call (replay)
        r2 = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={
                "X-API-Key": self.inbound_key,
                "Idempotency-Key": "TRF-E2E-IDEMP",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        self.assertEqual(r2.status_code, 200)
        data2 = r2.get_json()
        self.assertTrue(data2.get("idempotent"))
        self.assertTrue(data2.get("persisted"))

    def test_03_inbound_authentication_rejection(self):
        """Verify unauthorized access without valid API key is rejected with 401 or 403."""
        r_missing = self.client.post("/api/v1/refurbishment/devices", json={})
        self.assertEqual(r_missing.status_code, 401)

        r_bad = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": "invalid-key-xyz"},
            json={},
        )
        self.assertEqual(r_bad.status_code, 403)

    def test_04_ui_session_seeding_and_device_registry_access(self):
        """Verify browser UI loads / to obtain session cookie, then accesses /api/v1/devices."""
        # Pre-seed a device
        dev = Device(
            device_id="EW-2026-UI-DEV",
            device_type="Laptop",
            brand="Lenovo",
            model="ThinkPad T14",
            condition="Good",
            status="Received",
        )
        db.session.add(dev)
        db.session.commit()

        # Step 1: UI access loads index with key and receives session cookie
        root_resp = self.client.get("/?key=test-session-admin-key")
        self.assertEqual(root_resp.status_code, 200)

        # Step 2: Browser SPA fetches device registry with session cookie
        dev_resp = self.client.get("/api/v1/devices")
        self.assertEqual(dev_resp.status_code, 200)
        data = dev_resp.get_json()
        self.assertIn("devices", data)
        device_ids = [d.get("device_id") or d.get("id") for d in data["devices"]]
        self.assertIn("EW-2026-UI-DEV", device_ids)

    @patch("services.callback_service.requests.post")
    def test_05_reverse_callback_with_decimal_values(self, mock_post):
        """Verify reverse callback dispatches assessment with decimal scores to Collection."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true, "message": "Assessment acknowledged"}'
        mock_post.return_value = mock_resp

        # Create device and assessment with decimal scores
        dev = Device(
            device_id="EW-2026-CB-DEV",
            device_type="Smartphone",
            brand="Apple",
            model="iPhone 13",
            condition="Good",
            status="Assessed",
        )
        db.session.add(dev)

        asm = Assessment(
            assessment_id="ASM-2026-CB-01",
            device_id="EW-2026-CB-DEV",
            repairability_score=85.5,
            circular_recovery_score=82.3,
            repair_cost=4200.50,
            component_recovery_value=12500.0,
            estimated_refurbished_value=24000.0,
            co2_avoided_kg=14.7,
            recommendation="Refurbish",
            technical_summary="High yield device suitable for immediate refurbishment.",
            assessor="Lead Technician",
        )
        db.session.add(asm)
        db.session.commit()

        # Browser UI triggers 'Send result again'
        self.client.get("/?key=test-session-admin-key")  # Seed session
        resp = self.client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-2026-CB-DEV"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))

        # Verify mock_post called with float/decimal payload
        mock_post.assert_called_once()
        sent_payload = mock_post.call_args[1]["json"]
        self.assertEqual(sent_payload["device_id"], "EW-2026-CB-DEV")
        self.assertEqual(sent_payload["repairability_score"], 85.5)
        self.assertEqual(sent_payload["circular_recovery_score"], 82.3)
        self.assertEqual(sent_payload["repair_cost"], 4200.50)

    def test_06_unauthenticated_ui_send_rejected(self):
        """Verify unauthenticated calls to /api/v1/assessment-results/send fail with 401."""
        fresh_client = self.app.test_client()
        resp = fresh_client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-TEST-ANY"},
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertIn("Administrator authentication required", data.get("message", ""))


if __name__ == "__main__":
    unittest.main()


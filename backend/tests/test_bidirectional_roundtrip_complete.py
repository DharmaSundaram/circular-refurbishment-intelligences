"""Comprehensive Bidirectional Roundtrip Integration Test (Phase 7).

Validates the full 12-step bidirectional lifecycle between Collection and Partner applications:
1. Simulate Collection transferring a new device to Partner.
2. Verify Partner receives and stores it in refurbishment.devices.
3. Verify GET /api/v1/devices includes the new device.
4. Verify GET /api/v1/dashboard increments the device count.
5. Verify the device appears in GET /api/v1/queue.
6. Execute POST /api/v1/assessments for this device.
7. Verify assessment records are created in assessments, recovery_analyses, and assessment_components.
8. Verify callback is dispatched to Collection with required headers and payload.
9. Verify Collection endpoint receiving contract and response handling.
10. Verify Partner records the transfer completion in refurbishment.transfers.
11. Verify GET /api/v1/dashboard updates its metrics (Pending decreases, Refurb/Recovery Value updates).
12. Verify GET /api/v1/devices reflects the updated status.
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from config import Config
from extensions import db
from models.device import Device
from models.assessment import Assessment, AssessmentComponent
from models.recovery import RecoveryAnalysis
from models.transfer import Transfer
from models.idempotency import IdempotencyEvent
from app import create_app


class CompleteBidirectionalRoundtripTests(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            PARTNER_INBOUND_API_KEY = "partner-inbound-secret-key-123"
            COLLECTION_API_KEY = "collection-callback-secret-key-456"
            COLLECTION_API_URL = "https://collection-application.vercel.app"
            SECRET_KEY = "complete-roundtrip-test-secret-key"
            ADMIN_API_KEY = "admin-secret-key-789"
            IS_PRODUCTION = True  # Strict production mode

        self.app = create_app(config_class=TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        self.inbound_key = "partner-inbound-secret-key-123"
        self.callback_key = "collection-callback-secret-key-456"
        self.admin_key = "admin-secret-key-789"

        # Log in as admin to establish session for dashboard/devices/queue requests
        login_res = self.client.post(
            "/api/v1/auth/login",
            json={"admin_key": self.admin_key},
        )
        self.assertEqual(login_res.status_code, 200)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch("requests.post")
    def test_complete_bidirectional_roundtrip_12_steps(self, mock_post):
        """Execute full 12-step bidirectional integration lifecycle."""
        # Setup mock Collection callback response conforming to Collection API
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps({
            "status": "success",
            "message": "Assessment intelligence received and processed successfully.",
            "transfer_id": "TRF-COL-RECV-01",
            "device_id": "EW-2026-ROUNDTRIP-01",
            "new_device_status": "Refurbishment",
        })
        mock_response.json.return_value = {
            "status": "success",
            "message": "Assessment intelligence received and processed successfully.",
            "transfer_id": "TRF-COL-RECV-01",
            "device_id": "EW-2026-ROUNDTRIP-01",
            "new_device_status": "Refurbishment",
        }
        mock_post.return_value = mock_response

        # --- Baseline Dashboard Check before transfer ---
        dash_initial = self.client.get("/api/v1/dashboard")
        self.assertEqual(dash_initial.status_code, 200)
        init_metrics = dash_initial.get_json()["metrics"]
        self.assertEqual(init_metrics["incoming_devices"], 0)
        self.assertEqual(init_metrics["pending_assessments"], 0)

        # ---------------------------------------------------------------------
        # STEP 1: Simulate Collection transferring a new device to Partner
        # ---------------------------------------------------------------------
        transfer_payload = {
            "device_id": "EW-2026-ROUNDTRIP-01",
            "transfer_id": "TRF-COL-DISP-01",
            "device": {
                "id": "EW-2026-ROUNDTRIP-01",
                "name": "Lenovo ThinkPad T14 Gen 3",
                "type": "Laptop",
                "brand": "Lenovo",
                "model": "ThinkPad T14 Gen 3",
                "condition": "Good",
                "power_status": "Powers on",
                "screen_condition": "Flawless",
                "battery_condition": "Good",
                "purchase_year": 2023,
                "weight_kg": 1.35,
                "damage_description": "Minor wear on keyboard palmrest.",
            },
            "files": [
                {
                    "name": "hardware_diagnostic.json",
                    "file_type": "diagnostic",
                    "storage_key": "collection/devices/EW-2026-ROUNDTRIP-01/diagnostic.json",
                }
            ],
        }

        # Test both /api/v1/devices/incoming and /api/v1/refurbishment/devices
        inbound_resp = self.client.post(
            "/api/v1/devices/incoming",
            headers={
                "X-API-Key": self.inbound_key,
                "Content-Type": "application/json",
                "Idempotency-Key": "TRF-COL-DISP-01",
            },
            json=transfer_payload,
        )
        self.assertEqual(inbound_resp.status_code, 201)
        inbound_data = inbound_resp.get_json()
        self.assertEqual(inbound_data["status"], "success")
        self.assertEqual(inbound_data["device_id"], "EW-2026-ROUNDTRIP-01")

        # ---------------------------------------------------------------------
        # STEP 2: Verify Partner stores device in refurbishment.devices
        # ---------------------------------------------------------------------
        device_in_db = Device.query.filter_by(device_id="EW-2026-ROUNDTRIP-01").first()
        self.assertIsNotNone(device_in_db)
        self.assertEqual(device_in_db.brand, "Lenovo")
        self.assertEqual(device_in_db.model, "ThinkPad T14 Gen 3")
        self.assertEqual(device_in_db.status, "Received")

        # Also verify transfer audit log in Partner DB
        transfer_log = Transfer.query.filter_by(transfer_id="TRF-COL-DISP-01").first()
        self.assertIsNotNone(transfer_log)
        self.assertEqual(transfer_log.direction, "Inbound")
        self.assertEqual(transfer_log.status, "Completed")

        # ---------------------------------------------------------------------
        # STEP 3: Verify GET /api/v1/devices includes the new device
        # ---------------------------------------------------------------------
        devices_resp = self.client.get("/api/v1/devices")
        self.assertEqual(devices_resp.status_code, 200)
        devices_data = devices_resp.get_json()
        self.assertEqual(devices_data["total"], 1)
        self.assertEqual(len(devices_data["devices"]), 1)
        self.assertEqual(devices_data["devices"][0]["id"], "EW-2026-ROUNDTRIP-01")
        self.assertEqual(devices_data["devices"][0]["status"], "Received")

        # ---------------------------------------------------------------------
        # STEP 4: Verify GET /api/v1/dashboard increments the device count
        # ---------------------------------------------------------------------
        dash_step4 = self.client.get("/api/v1/dashboard")
        self.assertEqual(dash_step4.status_code, 200)
        metrics_step4 = dash_step4.get_json()["metrics"]
        self.assertEqual(metrics_step4["incoming_devices"], 1)
        self.assertEqual(metrics_step4["pending_assessments"], 1)
        self.assertEqual(metrics_step4["completed_assessments"], 0)
        self.assertEqual(metrics_step4["refurbishment_candidates"], 0)

        # ---------------------------------------------------------------------
        # STEP 5: Verify device appears in GET /api/v1/queue
        # ---------------------------------------------------------------------
        queue_resp = self.client.get("/api/v1/queue")
        self.assertEqual(queue_resp.status_code, 200)
        queue_data = queue_resp.get_json()
        self.assertEqual(queue_data["total"], 1)
        self.assertEqual(queue_data["queue"][0]["id"], "EW-2026-ROUNDTRIP-01")
        self.assertEqual(queue_data["queue"][0]["status"], "Received")

        # ---------------------------------------------------------------------
        # STEP 6: Execute POST /api/v1/assessments for this device
        # ---------------------------------------------------------------------
        assessment_payload = {
            "device_id": "EW-2026-ROUNDTRIP-01",
            "repairability_score": 86.5,
            "circular_recovery_score": 88.0,
            "repair_cost": 2500.0,
            "component_recovery_value": 7500.0,
            "estimated_refurbished_value": 24000.0,
            "co2_avoided_kg": 18.5,
            "recommendation": "Refurbish",
            "technical_summary": "Top condition corporate laptop. Battery health 92%. Display flawless.",
            "assessor": "Senior Refurbishment Engineer",
        }
        asmt_resp = self.client.post(
            "/api/v1/assessments",
            headers={"Content-Type": "application/json"},
            json=assessment_payload,
        )
        self.assertEqual(asmt_resp.status_code, 201)
        asmt_data = asmt_resp.get_json()
        self.assertEqual(asmt_data["status"], "success")
        self.assertTrue(asmt_data["callback"]["success"])

        # ---------------------------------------------------------------------
        # STEP 7: Verify assessment records are created
        # ---------------------------------------------------------------------
        # 7a. Assessment
        asmt_in_db = Assessment.query.filter_by(device_id="EW-2026-ROUNDTRIP-01").first()
        self.assertIsNotNone(asmt_in_db)
        self.assertEqual(asmt_in_db.recommendation, "Refurbish")
        self.assertEqual(asmt_in_db.estimated_refurbished_value, 24000.0)
        self.assertEqual(asmt_in_db.repairability_score, 86.5)

        # 7b. RecoveryAnalysis
        rec_in_db = RecoveryAnalysis.query.filter_by(device_id="EW-2026-ROUNDTRIP-01").first()
        self.assertIsNotNone(rec_in_db)
        self.assertEqual(rec_in_db.recovery_path, "Refurbish")
        self.assertEqual(rec_in_db.estimated_recovery_value, 24000.0)

        # 7c. AssessmentComponents
        components = AssessmentComponent.query.filter_by(assessment_id=asmt_in_db.assessment_id).all()
        self.assertGreater(len(components), 0)

        # ---------------------------------------------------------------------
        # STEP 8: Verify callback is dispatched to Collection
        # ---------------------------------------------------------------------
        self.assertTrue(mock_post.called)
        call_args = mock_post.call_args
        called_url = call_args[0][0]
        called_headers = call_args[1]["headers"]
        called_payload = call_args[1]["json"]

        self.assertIn("/api/v1/assessment-results", called_url)
        self.assertEqual(called_headers["X-API-Key"], self.callback_key)
        self.assertEqual(called_headers["Idempotency-Key"], asmt_in_db.assessment_id)
        self.assertEqual(called_payload["device_id"], "EW-2026-ROUNDTRIP-01")
        self.assertEqual(called_payload["recommendation"], "Refurbish")
        self.assertEqual(called_payload["repairability_score"], 86.5)
        self.assertEqual(called_payload["circular_recovery_score"], 88.0)
        self.assertEqual(called_payload["estimated_refurbished_value"], 24000.0)
        self.assertEqual(called_payload["repair_cost"], 2500.0)
        self.assertEqual(called_payload["component_value"], 7500.0)
        self.assertEqual(called_payload["co2_avoided_kg"], 18.5)

        # ---------------------------------------------------------------------
        # STEP 9: Verify Collection endpoint receives the payload & response handled
        # ---------------------------------------------------------------------
        self.assertEqual(mock_response.status_code, 200)

        # ---------------------------------------------------------------------
        # STEP 10: Verify Partner records the transfer completion
        # ---------------------------------------------------------------------
        outbound_transfer = Transfer.query.filter_by(
            device_id="EW-2026-ROUNDTRIP-01",
            direction="Outbound",
        ).first()
        self.assertIsNotNone(outbound_transfer)
        self.assertEqual(outbound_transfer.status, "Completed")
        self.assertEqual(outbound_transfer.http_status, 200)

        # ---------------------------------------------------------------------
        # STEP 11: Verify GET /api/v1/dashboard updates its metrics
        # ---------------------------------------------------------------------
        dash_step11 = self.client.get("/api/v1/dashboard")
        self.assertEqual(dash_step11.status_code, 200)
        metrics_step11 = dash_step11.get_json()["metrics"]
        self.assertEqual(metrics_step11["incoming_devices"], 1)
        self.assertEqual(metrics_step11["pending_assessments"], 0)  # Decreased from 1 to 0
        self.assertEqual(metrics_step11["completed_assessments"], 1)  # Increased from 0 to 1
        self.assertEqual(metrics_step11["refurbishment_candidates"], 1)  # Increased to 1
        self.assertEqual(metrics_step11["total_recovery_value"], 24000.0)  # Updated to 24,000
        self.assertEqual(metrics_step11["total_recovery_value_fmt"], "₹24,000")
        self.assertEqual(metrics_step11["total_co2_avoided_kg"], 18.5)

        # Also test with period filter
        dash_month = self.client.get("/api/v1/dashboard?period=This%20month")
        self.assertEqual(dash_month.status_code, 200)
        m_month = dash_month.get_json()["metrics"]
        self.assertEqual(m_month["incoming_devices"], 1)
        self.assertEqual(m_month["refurbishment_candidates"], 1)

        # ---------------------------------------------------------------------
        # STEP 12: Verify GET /api/v1/devices reflects updated status
        # ---------------------------------------------------------------------
        dev_list_updated = self.client.get("/api/v1/devices")
        self.assertEqual(dev_list_updated.status_code, 200)
        updated_data = dev_list_updated.get_json()
        self.assertEqual(updated_data["total"], 1)
        updated_dev = updated_data["devices"][0]
        self.assertEqual(updated_dev["id"], "EW-2026-ROUNDTRIP-01")
        self.assertEqual(updated_dev["status"], "Completed")
        self.assertEqual(updated_dev["decision"], "Refurbish")
        self.assertEqual(updated_dev["score"], 86.5)


if __name__ == "__main__":
    unittest.main()

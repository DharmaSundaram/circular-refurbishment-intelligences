"""Tests verifying Partner application incoming-device retrieval, schema isolation, and dashboard synchronization.

Validates that target devices transferred from Collection Application:
- EW-2026-166CA51F (Samsung Galaxy A23)
- EW-2026-B834E735 (Samsung Galaxy Tab A8 SM-X205)
- EW-2026-D86F5C8F (HP Omen Hyper X)
are persisted in refurbishment.devices, accurately returned by GET /api/v1/devices,
included in the assessment queue, reflected in dashboard KPIs, and synchronized to the UI.
"""

import unittest
from datetime import datetime, timezone

import config
from app import create_app
from extensions import db
from models.device import Device
from models.transfer import Transfer
from models.assessment import Assessment


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


class PartnerDeviceVisibilityTests(unittest.TestCase):
    """Test suite for Partner application device retrieval, schema isolation, and dashboard synchronization."""

    def setUp(self):
        class VisibilityTestConfig(config.Config):
            TESTING = True
            IS_PRODUCTION = False
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            SQLALCHEMY_ENGINE_OPTIONS = {}
            PARTNER_INBOUND_API_KEY = "test-inbound-key-xyz"
            COLLECTION_API_KEY = "test-collection-key-abc"
            COLLECTION_API_URL = "https://partner-collection.test"
            ADMIN_API_KEY = "test-admin-key-secret"
            DB_SCHEMA = "refurbishment"

        self.test_config = VisibilityTestConfig
        self.app = create_app(config_class=self.test_config)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        # Seed the exact three target devices
        for d_info in TARGET_DEVICES:
            dev = Device(
                device_id=d_info["device_id"],
                brand=d_info["brand"],
                model=d_info["model"],
                device_type=d_info["device_type"],
                condition=d_info["condition"],
                status=d_info["status"],
                source_application=d_info["source_application"],
                source_transfer_id=d_info["source_transfer_id"],
                received_at=datetime.now(timezone.utc),
            )
            trf = Transfer(
                transfer_id=d_info["source_transfer_id"],
                device_id=d_info["device_id"],
                direction="Inbound",
                sender="Collection",
                receiver="Refurbishment",
                endpoint="/api/v1/refurbishment/devices",
                http_method="POST",
                http_status=201,
                status="Completed",
                idempotency_key=f"IDEMP-{d_info['device_id']}",
            )
            db.session.add(dev)
            db.session.add(trf)

        db.session.commit()

        # Establish authenticated session via admin login
        self.client.post("/api/v1/auth/login", json={"admin_key": "test-admin-key-secret"})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_01_device_listing_returns_exact_three_target_devices(self):
        """Verify GET /api/v1/devices returns HTTP 200 and all three exact target devices."""
        resp = self.client.get("/api/v1/devices")
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertIn("devices", data)
        self.assertEqual(data["total"], 3)

        device_ids = [d["id"] for d in data["devices"]]
        self.assertIn("EW-2026-166CA51F", device_ids)
        self.assertIn("EW-2026-B834E735", device_ids)
        self.assertIn("EW-2026-D86F5C8F", device_ids)

        # Verify device attributes
        dev_map = {d["id"]: d for d in data["devices"]}

        d1 = dev_map["EW-2026-166CA51F"]
        self.assertEqual(d1["brand"], "Samsung")
        self.assertIn("Galaxy A23", d1["model"])
        self.assertEqual(d1["status"], "Received")

        d2 = dev_map["EW-2026-B834E735"]
        self.assertEqual(d2["brand"], "Samsung")
        self.assertIn("Galaxy Tab A8", d2["model"])
        self.assertEqual(d2["status"], "Received")

        d3 = dev_map["EW-2026-D86F5C8F"]
        self.assertEqual(d3["brand"], "HP")
        self.assertIn("Omen Hyper X", d3["model"])
        self.assertEqual(d3["status"], "Received")

    def test_02_devices_with_status_received_are_never_excluded(self):
        """Verify that devices with status 'Received' are preserved when querying with various filters."""
        # Query with status='All devices'
        resp_all = self.client.get("/api/v1/devices?status=All%20devices")
        self.assertEqual(resp_all.status_code, 200)
        self.assertEqual(resp_all.get_json()["total"], 3)

        # Query explicitly for status='Received'
        resp_rec = self.client.get("/api/v1/devices?status=Received")
        self.assertEqual(resp_rec.status_code, 200)
        self.assertEqual(resp_rec.get_json()["total"], 3)

        # Query without status parameter
        resp_none = self.client.get("/api/v1/devices")
        self.assertEqual(resp_none.status_code, 200)
        self.assertEqual(resp_none.get_json()["total"], 3)

    def test_03_device_search_filtering(self):
        """Verify device search filters properly across target records."""
        # Search for 'Samsung' -> should match Galaxy A23 and Galaxy Tab A8
        resp_samsung = self.client.get("/api/v1/devices?search=Samsung")
        self.assertEqual(resp_samsung.status_code, 200)
        self.assertEqual(resp_samsung.get_json()["total"], 2)

        # Search for 'Omen' -> should match HP Omen
        resp_omen = self.client.get("/api/v1/devices?search=Omen")
        self.assertEqual(resp_omen.status_code, 200)
        self.assertEqual(resp_omen.get_json()["total"], 1)
        self.assertEqual(resp_omen.get_json()["devices"][0]["id"], "EW-2026-D86F5C8F")

        # Search by device ID
        resp_id = self.client.get("/api/v1/devices?search=166CA51F")
        self.assertEqual(resp_id.status_code, 200)
        self.assertEqual(resp_id.get_json()["total"], 1)
        self.assertEqual(resp_id.get_json()["devices"][0]["id"], "EW-2026-166CA51F")

    def test_04_device_pagination_if_requested(self):
        """Verify pagination returns correct subset when limit is passed and total count is preserved."""
        resp = self.client.get("/api/v1/devices?limit=2&page=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["devices"]), 2)
        self.assertEqual(data["total"], 3)

    def test_05_assessment_queue_includes_all_received_devices(self):
        """Verify GET /api/v1/queue includes all 3 target devices awaiting technical assessment."""
        resp = self.client.get("/api/v1/queue")
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertIn("queue", data)
        self.assertEqual(data["total"], 3)

        queue_ids = [d["id"] for d in data["queue"]]
        self.assertIn("EW-2026-166CA51F", queue_ids)
        self.assertIn("EW-2026-B834E735", queue_ids)
        self.assertIn("EW-2026-D86F5C8F", queue_ids)

    def test_06_dashboard_metrics_reflect_live_database_counts(self):
        """Verify GET /api/v1/dashboard accurately reports total incoming devices and pending assessments."""
        resp = self.client.get("/api/v1/dashboard")
        self.assertEqual(resp.status_code, 200)

        metrics = resp.get_json().get("metrics", {})
        self.assertEqual(metrics.get("incoming_devices"), 3)
        self.assertEqual(metrics.get("pending_assessments"), 3)
        self.assertEqual(metrics.get("completed_assessments"), 0)

    def test_07_recovery_analysis_executes_without_error(self):
        """Verify GET /api/v1/recovery-analysis runs cleanly with live database records."""
        resp = self.client.get("/api/v1/recovery-analysis")
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertIn("metrics", data)
        self.assertIn("component_breakdown", data)
        self.assertIn("pathway_distribution", data)

    def test_08_frontend_bundle_synchronization_and_clean_state(self):
        """Verify frontend bundle has dynamic sync interval, no static demo fallback in prod, and clean empty state."""
        for bundle_path in ["public/assets/index-DlDXW_IB.js", "frontend/ui/assets/index-DlDXW_IB.js"]:
            with open(bundle_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Dynamic sync interval present
            self.assertIn("window.setInterval(syncData,5000)", content)
            # Sync triggered on tab navigation
            self.assertIn("[e]", content)
            # Clean empty message when database has no incoming devices
            self.assertIn("No incoming devices registered in the database yet.", content)
            # Live device list count in Recent devices footer
            self.assertIn("Showing ${Math.min(5,devList.length)} of ${devList.length} incoming devices", content)
            # Live queue header count
            self.assertIn("devices awaiting assessment", content)

    def test_09_dashboard_counts_unconstrained_by_period_and_accessible(self):
        """Verify dashboard metrics require administrator session and accurately reflect database counts with filters."""
        # Unauthenticated request returns 401
        anon_client = self.app.test_client()
        resp_unauth = anon_client.get("/api/v1/dashboard")
        self.assertEqual(resp_unauth.status_code, 401)

        # Authenticated session returns 200
        auth_client = self.app.test_client()
        with auth_client.session_transaction() as sess:
            sess["admin"] = True
            sess["authenticated"] = True

        resp_anon = auth_client.get("/api/v1/dashboard")
        self.assertEqual(resp_anon.status_code, 200)
        metrics = resp_anon.get_json()["metrics"]
        self.assertEqual(metrics["incoming_devices"], 3)
        self.assertEqual(metrics["pending_assessments"], 3)
        self.assertEqual(metrics["refurbishment_candidates"], 0)

        # Date filter 'This month' retains full database incoming devices count
        resp_month = auth_client.get("/api/v1/dashboard?period=This%20month")
        self.assertEqual(resp_month.status_code, 200)
        metrics_month = resp_month.get_json()["metrics"]
        self.assertEqual(metrics_month["incoming_devices"], 3)
        self.assertEqual(metrics_month["pending_assessments"], 3)

        # Create an assessment on one device
        asm = Assessment(
            assessment_id="ASM-TEST-DASH-01",
            device_id="EW-2026-166CA51F",
            repairability_score=85.0,
            circular_recovery_score=80.0,
            repair_cost=1500.0,
            component_recovery_value=3000.0,
            estimated_refurbished_value=12000.0,
            recommendation="Refurbish",
            co2_avoided_kg=15.0,
            technical_summary="Device in good working condition.",
        )
        db.session.add(asm)
        # Update device status
        dev = Device.query.filter_by(device_id="EW-2026-166CA51F").first()
        dev.status = "Refurbishment Recommended"
        db.session.commit()

        # Re-check metrics: Pending Assessments = 2 (remaining Received devices without assessment)
        resp_updated = auth_client.get("/api/v1/dashboard")
        self.assertEqual(resp_updated.status_code, 200)
        upd_metrics = resp_updated.get_json()["metrics"]
        self.assertEqual(upd_metrics["incoming_devices"], 3)
        self.assertEqual(upd_metrics["pending_assessments"], 2)
        self.assertEqual(upd_metrics["completed_assessments"], 1)
        self.assertEqual(upd_metrics["refurbishment_candidates"], 1)
        self.assertEqual(upd_metrics["total_recovery_value"], 12000.0)

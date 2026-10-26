import unittest
import json
from config import Config
from extensions import db
from models.device import Device
from models.transfer import Transfer
from models.idempotency import IdempotencyEvent
from app import create_app


class IncomingDeviceApiTests(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            CIRCULAR_API_KEY = "test-secret-key-123"

        self.app = create_app(config_class=TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.api_key = "test-secret-key-123"

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_missing_api_key(self):
        resp = self.client.post("/api/v1/refurbishment/devices", json={})
        self.assertEqual(resp.status_code, 401)

    def test_invalid_api_key(self):
        resp = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": "wrong-key"},
            json={},
        )
        self.assertEqual(resp.status_code, 403)

    def test_valid_incoming_device(self):
        payload = {
            "device_id": "EW-2026-9999",
            "transfer_id": "TRF-TEST-001",
            "device": {
                "type": "Laptop",
                "brand": "Lenovo",
                "model": "ThinkPad X1",
                "purchase_year": 2023,
                "age": 3,
                "condition": "Good",
                "power_status": "Powers on",
                "screen_condition": "Good",
                "battery_condition": "Good",
                "weight_kg": 1.3,
                "damage_description": "Clean cosmetic condition.",
            },
            "files": [
                {"name": "specs.json", "type": "diagnostic", "storage_key": "rem_spec_9999"}
            ],
        }

        resp = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": self.api_key},
            json=payload,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["device_id"], "EW-2026-9999")

        # Verify database record
        dev = Device.query.filter_by(device_id="EW-2026-9999").first()
        self.assertIsNotNone(dev)
        self.assertEqual(dev.brand, "Lenovo")

        # Verify transfer log
        trf = Transfer.query.filter_by(transfer_id="TRF-TEST-001").first()
        self.assertIsNotNone(trf)
        self.assertEqual(trf.direction, "Inbound")

    def test_idempotent_duplicate_request(self):
        payload = {
            "device_id": "EW-2026-IDEMP",
            "transfer_id": "TRF-IDEMP-001",
            "device": {
                "type": "Smartphone",
                "brand": "Apple",
                "model": "iPhone 12",
                "condition": "Fair",
            },
        }

        # First request
        resp1 = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": self.api_key, "Idempotency-Key": "TRF-IDEMP-001"},
            json=payload,
        )
        self.assertEqual(resp1.status_code, 201)

        # Second request with identical idempotency key
        resp2 = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": self.api_key, "Idempotency-Key": "TRF-IDEMP-001"},
            json=payload,
        )
        self.assertEqual(resp2.status_code, 200)

        # Ensure no duplicate records created
        self.assertEqual(Device.query.filter_by(device_id="EW-2026-IDEMP").count(), 1)

    def test_malformed_payload(self):
        resp = self.client.post(
            "/api/v1/refurbishment/devices",
            headers={"X-API-Key": self.api_key},
            json={"device_id": "EW-INCOMPLETE"},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()

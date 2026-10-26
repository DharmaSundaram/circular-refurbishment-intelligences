import unittest
from unittest.mock import patch, MagicMock
from config import Config
from extensions import db
from models.device import Device
from models.assessment import Assessment
from models.transfer import Transfer
from services.callback_service import send_assessment_result_to_collection, retry_partner_transfer
from services.report_service import generate_assessment_pdf, generate_summary_csv
from app import create_app


class ReportsAndCallbacksTests(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            CIRCULAR_API_KEY = "test-key"
            COLLECTION_API_URL = "https://partner-collection.example.com"

        self.app = create_app(config_class=TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        # Seed test device and assessment
        self.dev = Device(
            device_id="EW-TEST-REP",
            device_type="Laptop",
            brand="Dell",
            model="Latitude 5420",
            condition="Good",
            status="Assessed",
        )
        db.session.add(self.dev)

        self.asm = Assessment(
            assessment_id="ASM-TEST-REP",
            device_id="EW-TEST-REP",
            repairability_score=85.0,
            circular_recovery_score=80.0,
            repair_cost=5000.0,
            component_recovery_value=11000.0,
            estimated_refurbished_value=22000.0,
            co2_avoided_kg=18.0,
            recommendation="Refurbish",
            technical_summary="High quality device ready for second life.",
            assessor="Refurb Admin",
        )
        db.session.add(self.asm)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_pdf_report_generation(self):
        buf = generate_assessment_pdf("EW-TEST-REP")
        self.assertIsNotNone(buf)
        pdf_bytes = buf.getvalue()
        # PDF files always start with %PDF
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_pdf_endpoint_404_on_missing(self):
        resp = self.client.get("/api/v1/reports/assessment/NON-EXISTENT")
        self.assertEqual(resp.status_code, 404)

    def test_csv_summary_endpoint(self):
        resp = self.client.get("/api/v1/reports/summary")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.content_type)
        self.assertIn("EW-TEST-REP", resp.data.decode("utf-8"))

    @patch("services.callback_service.requests.post")
    def test_successful_collection_callback(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true, "message": "Assessment acknowledged"}'
        mock_post.return_value = mock_resp

        success, status_code, message, transfer = send_assessment_result_to_collection("ASM-TEST-REP")
        self.assertTrue(success)
        self.assertEqual(status_code, 200)
        self.assertEqual(transfer.status, "Completed")
        self.assertEqual(transfer.http_status, 200)

    @patch("services.callback_service.requests.post")
    def test_failed_collection_callback_503(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = '{"error": "Upstream service down"}'
        mock_post.return_value = mock_resp

        success, status_code, message, transfer = send_assessment_result_to_collection("ASM-TEST-REP")
        self.assertFalse(success)
        self.assertEqual(status_code, 503)
        self.assertEqual(transfer.status, "Failed")

    @patch("services.callback_service.requests.post")
    def test_transfer_retry(self, mock_post):
        # Create failed transfer
        trf = Transfer(
            transfer_id="TRF-RETRY-01",
            device_id="EW-TEST-REP",
            direction="Outbound",
            sender="Refurbishment",
            receiver="Collection",
            endpoint="https://partner-collection.example.com/api/v1/assessment-results",
            http_method="POST",
            request_payload='{"device_id": "EW-TEST-REP"}',
            http_status=500,
            status="Failed",
            retry_count=0,
            idempotency_key="ASM-TEST-REP",
        )
        db.session.add(trf)
        db.session.commit()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": "ok"}'
        mock_post.return_value = mock_resp

        success, code, msg, retried = retry_partner_transfer("TRF-RETRY-01")
        self.assertTrue(success)
        self.assertEqual(code, 200)
        self.assertEqual(retried.retry_count, 1)
        self.assertEqual(retried.status, "Completed")


if __name__ == "__main__":
    unittest.main()

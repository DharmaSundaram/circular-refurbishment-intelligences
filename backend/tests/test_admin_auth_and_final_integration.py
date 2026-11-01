"""Targeted integration and regression tests for ADMIN_API_KEY runtime validation,
session security, incoming device synchronization, assessment persistence,
and bidirectional callback delivery.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from extensions import db
from models.device import Device
from models.assessment import Assessment, AssessmentComponent
from models.transfer import Transfer
from models.recovery import RecoveryAnalysis
from api.auth import get_configured_admin_key


class TestFinalConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DB_SCHEMA = "refurbishment"
    SECRET_KEY = "test-secret-key-final"
    ADMIN_API_KEY = "test-prod-admin-key-2026"
    PARTNER_INBOUND_API_KEY = "test-inbound-key-collection"
    COLLECTION_API_KEY = "test-outbound-key-collection"
    COLLECTION_API_URL = "https://mock-collection.vercel.app"


@pytest.fixture
def app():
    test_app = create_app(config_class=TestFinalConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_admin_api_key_read_dynamically_from_environ(app, monkeypatch):
    """Verify ADMIN_API_KEY is read dynamically from os.environ at runtime."""
    with app.app_context():
        monkeypatch.setenv("ADMIN_API_KEY", "dynamic-vercel-key-xyz")
        assert get_configured_admin_key() == "dynamic-vercel-key-xyz"

        # Verify whitespace trimming
        monkeypatch.setenv("ADMIN_API_KEY", "  spaced-key-abc \n")
        assert get_configured_admin_key() == "spaced-key-abc"


def test_missing_admin_key_returns_500_in_production(app, monkeypatch):
    """If ADMIN_API_KEY is missing at runtime in production, return HTTP 500 Configuration Error."""
    test_client = app.test_client()
    with app.app_context():
        app.config["IS_PRODUCTION"] = True
        app.config["ADMIN_API_KEY"] = None
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        monkeypatch.delenv("REFURBISHMENT_ADMIN_API_KEY", raising=False)

        # Attempt administrative request with a key
        resp = test_client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-2026-166CA51F"},
            headers={"X-API-Key": "some-key"},
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["error"] == "Configuration Error"
        assert "ADMIN_API_KEY is not configured" in data["message"]

        # Attempt login endpoint when key is missing in production
        resp_login = test_client.post(
            "/api/v1/auth/login",
            json={"admin_key": "some-key"},
        )
        assert resp_login.status_code == 500


def test_partner_inbound_key_forbidden_for_admin_actions(client, app):
    """PARTNER_INBOUND_API_KEY cannot be used to authenticate admin operations."""
    with app.app_context():
        app.config["IS_PRODUCTION"] = True
        resp = client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-2026-166CA51F"},
            headers={"X-API-Key": "test-inbound-key-collection"},
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "Forbidden"
        assert "PARTNER_INBOUND_API_KEY is not permitted" in data["message"]


def test_admin_authentication_via_headers_and_body(client, app):
    """Verify admin auth succeeds via X-API-Key, X-Admin-Key, Authorization Bearer, and JSON payload."""
    with app.app_context():
        # Setup device and assessment
        dev = Device(
            device_id="EW-TEST-AUTH-DEV",
            device_type="Smartphone",
            brand="Samsung",
            model="Galaxy A23",
            condition="Fair",
            status="Assessed",
        )
        db.session.add(dev)
        asm = Assessment(
            assessment_id="ASM-TEST-AUTH",
            device_id="EW-TEST-AUTH-DEV",
            repairability_score=75.0,
            circular_recovery_score=78.0,
            repair_cost=2500.0,
            component_recovery_value=6000.0,
            estimated_refurbished_value=18000.0,
            co2_avoided_kg=4.5,
            recommendation="Refurbish",
            technical_summary="Test summary",
            assessor="Admin",
        )
        db.session.add(asm)
        db.session.commit()

    with patch("services.callback_service.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = '{"status": "success"}'
        mock_post.return_value.json.return_value = {"status": "success"}

        # 1. X-API-Key
        r1 = client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-TEST-AUTH-DEV"},
            headers={"X-API-Key": "test-prod-admin-key-2026"},
        )
        assert r1.status_code == 200

        # 2. X-Admin-Key
        r2 = client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-TEST-AUTH-DEV", "force": True},
            headers={"X-Admin-Key": "test-prod-admin-key-2026"},
        )
        assert r2.status_code == 200

        # 3. Authorization Bearer
        r3 = client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-TEST-AUTH-DEV", "force": True},
            headers={"Authorization": "Bearer test-prod-admin-key-2026"},
        )
        assert r3.status_code == 200

        # 4. JSON payload admin_key
        r4 = client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-TEST-AUTH-DEV", "admin_key": "test-prod-admin-key-2026", "force": True},
        )
        assert r4.status_code == 200


def test_session_cookie_authentication_flow(client, app):
    """Verify administrator login sets session cookie and authorizes subsequent operations without headers."""
    with app.app_context():
        dev = Device(
            device_id="EW-TEST-SESSION-DEV",
            device_type="Tablet",
            brand="Samsung",
            model="Galaxy Tab A8",
            condition="Good",
            status="Assessed",
        )
        db.session.add(dev)
        asm = Assessment(
            assessment_id="ASM-TEST-SESSION",
            device_id="EW-TEST-SESSION-DEV",
            repairability_score=85.0,
            circular_recovery_score=88.0,
            repair_cost=2000.0,
            component_recovery_value=6000.0,
            estimated_refurbished_value=12000.0,
            co2_avoided_kg=5.0,
            recommendation="Refurbish",
            technical_summary="Test",
        )
        db.session.add(asm)
        db.session.commit()

    with patch("services.callback_service.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = '{"status": "success"}'
        mock_post.return_value.json.return_value = {"status": "success"}

        # Login to establish session
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"admin_key": "test-prod-admin-key-2026"},
        )
        assert login_resp.status_code == 200
        assert login_resp.get_json()["authenticated"] is True

        # Check session status
        sess_resp = client.get("/api/v1/auth/session")
        assert sess_resp.status_code == 200
        assert sess_resp.get_json()["authenticated"] is True

        # Perform Send Result using session cookie alone (no API key headers)
        send_resp = client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-TEST-SESSION-DEV"},
        )
        assert send_resp.status_code == 200
        assert send_resp.get_json()["success"] is True


def test_complete_roundtrip_device_to_collection_persistence(client, app):
    """Complete 8-step verification:
    1. Receive device from Collection (POST /api/v1/devices/receive)
    2. Persist device in refurbishment schema
    3. Run assessment (POST /api/v1/assessments)
    4. Validate non-null calculations & database persistence
    5. Automatic callback delivery to Collection
    6. Verify outbound transfer logged with status Completed
    7. Verify device transitions to Completed
    8. Verify manual retry endpoint allows re-sending with existing session
    """
    inbound_payload = {
        "device_id": "EW-2026-ROUNDTRIP-01",
        "transfer_id": "TRF-IN-ROUNDTRIP-01",
        "device": {
            "type": "Laptop",
            "brand": "HP",
            "model": "Omen Hyper X",
            "condition": "Damaged",
            "power_status": "Powers on",
            "screen_condition": "Cracked",
            "battery_condition": "Poor",
            "damage_description": "Screen cracked, worn battery",
            "age": "3 years",
            "weight_kg": 2.3,
        },
    }

    # Step 1 & 2: Receive and persist device
    recv_resp = client.post(
        "/api/v1/devices/receive",
        json=inbound_payload,
        headers={"X-API-Key": "test-inbound-key-collection"},
    )
    assert recv_resp.status_code == 201
    assert recv_resp.get_json()["persisted"] is True

    # Step 3 & 4: Run assessment
    with patch("services.callback_service.requests.post") as mock_col_post:
        mock_col_post.return_value.status_code = 200
        mock_col_post.return_value.text = '{"status": "success", "message": "Assessment acknowledged"}'
        mock_col_post.return_value.json.return_value = {"status": "success"}

        asm_resp = client.post(
            "/api/v1/assessments",
            json={"device_id": "EW-2026-ROUNDTRIP-01"},
            headers={"X-API-Key": "test-prod-admin-key-2026"},
        )
        assert asm_resp.status_code == 201
        asm_data = asm_resp.get_json()["assessment"]

        # Validate non-null values
        assert asm_data["repairability_score"] is not None
        assert asm_data["repair_cost"] > 0
        assert asm_data["component_recovery_value"] > 0
        assert asm_data["estimated_refurbished_value"] > 0
        assert asm_data["co2_avoided_kg"] > 0
        assert asm_data["recommendation"] in ("Parts Recovery", "Recycle", "Refurbish")

        # Step 5 & 6: Validate callback delivery was dispatched to Collection
        assert mock_col_post.called
        call_json = mock_col_post.call_args[1]["json"]
        assert call_json["device_id"] == "EW-2026-ROUNDTRIP-01"
        assert call_json["repairability_score"] == asm_data["repairability_score"]
        assert call_json["component_value"] == asm_data["component_recovery_value"]
        assert call_json["recommendation"] == asm_data["recommendation"]

        # Step 7: Check device status in DB
        with app.app_context():
            dev = Device.query.filter_by(device_id="EW-2026-ROUNDTRIP-01").first()
            assert dev.status == "Completed"

            # Check outbound transfer logged as Completed
            trf = Transfer.query.filter_by(device_id="EW-2026-ROUNDTRIP-01", direction="Outbound").first()
            assert trf is not None
            assert trf.status == "Completed"
            assert trf.http_status == 200

        # Step 8: Manual re-send via Send Result
        resend_resp = client.post(
            "/api/v1/assessment-results/send",
            json={"device_id": "EW-2026-ROUNDTRIP-01", "force": True},
            headers={"X-API-Key": "test-prod-admin-key-2026"},
        )
        assert resend_resp.status_code == 200
        assert resend_resp.get_json()["success"] is True


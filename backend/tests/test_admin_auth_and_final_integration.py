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


def test_admin_key_quote_and_whitespace_sanitization(client, app, monkeypatch):
    """Verify administrator login succeeds when credentials have surrounding quotes or whitespace."""
    with app.app_context():
        # Set configured ADMIN_API_KEY with outer quotes and whitespace as commonly entered in Vercel
        monkeypatch.setenv("ADMIN_API_KEY", ' "prod-admin-secret-2026" \n')

        # 1. Login with plain unquoted key
        r1 = client.post("/api/v1/auth/login", json={"admin_key": "prod-admin-secret-2026"})
        assert r1.status_code == 200
        assert r1.get_json()["authenticated"] is True

        # Clear session
        client.post("/api/v1/auth/logout")

        # 2. Login with user-entered double quotes
        r2 = client.post("/api/v1/auth/login", json={"admin_key": '"prod-admin-secret-2026"'})
        assert r2.status_code == 200
        assert r2.get_json()["authenticated"] is True

        client.post("/api/v1/auth/logout")

        # 3. Login with user-entered single quotes and leading/trailing whitespace
        r3 = client.post("/api/v1/auth/login", json={"admin_key": "  'prod-admin-secret-2026'  "})
        assert r3.status_code == 200
        assert r3.get_json()["authenticated"] is True


def test_admin_login_incorrect_key(client, app):
    """Verify administrator login rejects invalid keys with HTTP 401."""
    with app.app_context():
        resp = client.post("/api/v1/auth/login", json={"admin_key": "completely-wrong-key"})
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"] == "Unauthorized"
        assert "Invalid administrator credentials" in data["message"]

        # Verify session was NOT established
        sess = client.get("/api/v1/auth/session")
        assert sess.status_code == 200
        assert sess.get_json()["authenticated"] is False


def test_admin_login_missing_credentials(client, app):
    """Verify administrator login rejects missing or empty credentials with HTTP 401."""
    with app.app_context():
        # Empty JSON
        r1 = client.post("/api/v1/auth/login", json={})
        assert r1.status_code == 401
        assert "Missing administrator credentials" in r1.get_json()["message"]

        # Blank string key
        r2 = client.post("/api/v1/auth/login", json={"admin_key": "   "})
        assert r2.status_code == 401
        assert "Missing administrator credentials" in r2.get_json()["message"]


def test_cross_credential_isolation_in_login_and_headers(client, app):
    """Verify PARTNER_INBOUND_API_KEY and COLLECTION_API_KEY cannot be used for admin login or admin headers."""
    with app.app_context():
        app.config["IS_PRODUCTION"] = True

        # 1. Inbound key in login body -> 403 Forbidden
        r_inbound = client.post(
            "/api/v1/auth/login",
            json={"admin_key": "test-inbound-key-collection"},
        )
        assert r_inbound.status_code == 403
        assert "PARTNER_INBOUND_API_KEY cannot be used" in r_inbound.get_json()["message"]

        # 2. Outbound collection key in login body -> 403 Forbidden
        r_outbound = client.post(
            "/api/v1/auth/login",
            json={"admin_key": "test-outbound-key-collection"},
        )
        assert r_outbound.status_code == 403
        assert "COLLECTION_API_KEY cannot be used" in r_outbound.get_json()["message"]

        # 3. Collection key in X-API-Key header to protected endpoint -> 403 Forbidden
        r_col_hdr = client.get(
            "/api/v1/devices",
            headers={"X-API-Key": "test-outbound-key-collection"},
        )
        assert r_col_hdr.status_code == 403
        assert "COLLECTION_API_KEY is not permitted" in r_col_hdr.get_json()["message"]


def test_admin_key_environment_variable_aliases(client, app, monkeypatch):
    """Verify administrator authentication recognizes all standard environment variable aliases."""
    aliases = ["PARTNER_ADMIN_API_KEY", "REFURBISHMENT_ADMIN_API_KEY", "ADMIN_KEY"]
    for alias in aliases:
        with app.app_context():
            app.config["ADMIN_API_KEY"] = None
            monkeypatch.delenv("ADMIN_API_KEY", raising=False)
            monkeypatch.delenv("PARTNER_ADMIN_API_KEY", raising=False)
            monkeypatch.delenv("REFURBISHMENT_ADMIN_API_KEY", raising=False)
            monkeypatch.delenv("ADMIN_KEY", raising=False)

            secret = f"key-via-{alias.lower()}"
            monkeypatch.setenv(alias, secret)

            resp = client.post("/api/v1/auth/login", json={"admin_key": secret})
            assert resp.status_code == 200, f"Failed for alias {alias}"
            assert resp.get_json()["authenticated"] is True

            client.post("/api/v1/auth/logout")


def test_session_lifecycle_and_protected_endpoints(client, app):
    """Verify session grants access to protected endpoints and session expiration/logout revokes it with HTTP 401."""
    with app.app_context():
        # Initial unauthenticated request -> 401
        r_dev_unauth = client.get("/api/v1/devices")
        assert r_dev_unauth.status_code == 401
        assert "Administrator authentication required" in r_dev_unauth.get_json()["message"]

        r_dash_unauth = client.get("/api/v1/dashboard")
        assert r_dash_unauth.status_code == 401

        r_trf_unauth = client.get("/api/v1/transfers")
        assert r_trf_unauth.status_code == 401

        # Establish administrator session
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"admin_key": "test-prod-admin-key-2026"},
        )
        assert login_resp.status_code == 200

        # Protected endpoints succeed via session cookie
        assert client.get("/api/v1/devices").status_code == 200
        assert client.get("/api/v1/dashboard").status_code == 200
        assert client.get("/api/v1/transfers").status_code == 200

        # Logout / invalidate session
        logout_resp = client.post("/api/v1/auth/logout")
        assert logout_resp.status_code == 200

        # Verify session endpoint confirms unauthenticated
        sess_check = client.get("/api/v1/auth/session")
        assert sess_check.status_code == 200
        assert sess_check.get_json()["authenticated"] is False

        # Protected endpoints once again reject with 401
        assert client.get("/api/v1/devices").status_code == 401
        assert client.get("/api/v1/dashboard").status_code == 401
        assert client.get("/api/v1/transfers").status_code == 401


"""Regression test suite ensuring zero NULL assessment reports, deterministic scoring,
robust input validation, and reliable callback payload structure.
"""

import pytest
from datetime import datetime, timezone
from app import create_app
from extensions import db
from models.device import Device
from models.assessment import Assessment, AssessmentComponent
from models.recovery import RecoveryAnalysis
from services.assessment_engine import evaluate_device_assessment


class TestAssessmentConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DB_SCHEMA = "refurbishment"
    SECRET_KEY = "test-secret"
    ADMIN_API_KEY = "test-admin-key"
    PARTNER_API_KEY = "test-partner-key"
    COLLECTION_API_KEY = "test-col-key"
    COLLECTION_API_URL = "https://mock-collection.vercel.app"


@pytest.fixture
def app():
    test_app = create_app(config_class=TestAssessmentConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {
        "X-API-Key": "test-admin-key",
        "Content-Type": "application/json",
    }


def test_rule_based_engine_target_devices():
    """Verify deterministic calculations for all three production devices without NULLs."""
    dev_a23 = {
        "device_id": "EW-2026-166CA51F",
        "device_type": "Smartphone",
        "brand": "Samsung",
        "model": "Galaxy A23",
        "condition": "Fair",
        "power_status": "Powers on",
        "screen_condition": "Minor scratches",
        "battery_condition": "82% health",
        "damage_description": "Minor bezel scuffs",
        "age": 2,
        "weight_kg": 0.195,
    }
    res_a23 = evaluate_device_assessment(dev_a23)
    assert res_a23["repairability_score"] is not None
    assert 0 <= res_a23["repairability_score"] <= 100
    assert res_a23["repair_cost"] > 0
    assert res_a23["component_recovery_value"] > 0
    assert res_a23["estimated_refurbished_value"] > 0
    assert res_a23["co2_avoided_kg"] > 0
    assert res_a23["recommendation"] in ("Refurbish", "Parts Recovery", "Recycle", "Reject")
    assert len(res_a23["components"]) > 0

    dev_tab = {
        "device_id": "EW-2026-B834E735",
        "device_type": "Tablet",
        "brand": "Samsung",
        "model": "Galaxy Tab A8 SM-X205",
        "condition": "Good",
        "power_status": "Powers on",
        "screen_condition": "Good",
        "battery_condition": "Good",
        "damage_description": "None",
        "age": 1,
        "weight_kg": 0.508,
    }
    res_tab = evaluate_device_assessment(dev_tab)
    assert res_tab["repairability_score"] is not None
    assert res_tab["repairability_score"] >= 70.0
    assert res_tab["recommendation"] == "Refurbish"

    dev_omen = {
        "device_id": "EW-2026-D86F5C8F",
        "device_type": "Laptop",
        "brand": "HP",
        "model": "Omen Hyper X",
        "condition": "Damaged",
        "power_status": "No power",
        "screen_condition": "Cracked",
        "battery_condition": "Poor",
        "damage_description": "Motherboard short, broken display",
        "age": 4,
        "weight_kg": 2.4,
    }
    res_omen = evaluate_device_assessment(dev_omen)
    assert res_omen["repairability_score"] is not None
    assert res_omen["repair_cost"] > 5000.0
    assert res_omen["component_recovery_value"] > 0
    assert res_omen["recommendation"] in ("Parts Recovery", "Recycle")


def test_unassessed_device_serialization_never_shows_complete(app):
    """An unassessed device must have score=None, decision='Pending Assessment', and dashes for formatted values."""
    with app.app_context():
        device = Device(
            device_id="EW-TEST-UNASSESSED",
            device_type="Laptop",
            brand="Lenovo",
            model="ThinkPad T14",
            condition="Fair",
            status="Received",
        )
        db.session.add(device)
        db.session.commit()

        d_dict = device.to_dict()
        assert d_dict["score"] is None
        assert d_dict["repairability_score"] is None
        assert d_dict["decision"] == "Pending Assessment"
        assert d_dict["repair_cost_fmt"] == "—"
        assert d_dict["component_recovery_value_fmt"] == "—"
        assert d_dict["estimated_refurbished_value_fmt"] == "—"
        assert d_dict["co2_avoided_fmt"] == "—"


def test_assessment_rejects_missing_essential_info(client, auth_headers, app):
    """Essential fields (device_type, brand, model, condition) must be present. Missing fields return 422."""
    with app.app_context():
        device = Device(
            device_id="EW-TEST-INCOMPLETE",
            device_type="",  # Missing device_type
            brand="Dell",
            model="",  # Missing model
            condition="Good",
            status="Received",
        )
        db.session.add(device)
        db.session.commit()

    resp = client.post(
        "/api/v1/assessments",
        json={"device_id": "EW-TEST-INCOMPLETE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    data = resp.get_json()
    assert "missing_fields" in data
    assert "device_type" in data["missing_fields"]
    assert "model" in data["missing_fields"]

    with app.app_context():
        updated_dev = Device.query.filter_by(device_id="EW-TEST-INCOMPLETE").first()
        assert updated_dev.status == "Incomplete Information"
        asm = Assessment.query.filter_by(device_id="EW-TEST-INCOMPLETE").first()
        assert asm is None, "Assessment must NOT be persisted when essential data is missing"


def test_complete_assessment_persists_non_null_records(client, auth_headers, app):
    """End-to-end: running assessment persists non-null assessment, components, recovery analysis, and updates device status."""
    with app.app_context():
        device = Device(
            device_id="EW-2026-166CA51F",
            device_type="Smartphone",
            brand="Samsung",
            model="Galaxy A23",
            condition="Fair",
            power_status="Powers on",
            screen_condition="Minor scratches",
            battery_condition="82% health",
            damage_description="Minor bezel scuffs",
            age="2 years",
            weight_kg=0.2,
            status="Received",
        )
        db.session.add(device)
        db.session.commit()

    resp = client.post(
        "/api/v1/assessments",
        json={"device_id": "EW-2026-166CA51F"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "success"
    asm_data = data["assessment"]

    # Verify all scores are populated and non-null
    assert asm_data["repairability_score"] is not None
    assert asm_data["repairability_score"] > 0
    assert asm_data["repair_cost"] is not None
    assert asm_data["repair_cost"] > 0
    assert asm_data["component_recovery_value"] is not None
    assert asm_data["component_recovery_value"] > 0
    assert asm_data["estimated_refurbished_value"] is not None
    assert asm_data["estimated_refurbished_value"] > 0
    assert asm_data["co2_avoided_kg"] is not None
    assert asm_data["co2_avoided_kg"] > 0
    assert asm_data["recommendation"] is not None
    assert asm_data["recommendation"] != "Pending Assessment"
    assert len(asm_data["components"]) > 0

    with app.app_context():
        # Verify database persistence in refurbishment.assessments
        asm = Assessment.query.filter_by(device_id="EW-2026-166CA51F").first()
        assert asm is not None
        assert asm.repairability_score is not None
        assert asm.repair_cost > 0
        assert asm.component_recovery_value > 0
        assert asm.estimated_refurbished_value > 0
        assert asm.co2_avoided_kg > 0

        # Verify components in refurbishment.assessment_components
        comps = AssessmentComponent.query.filter_by(assessment_id=asm.assessment_id).all()
        assert len(comps) > 0
        for comp in comps:
            assert comp.component_name
            assert comp.condition
            assert comp.estimated_value >= 0

        # Verify recovery analysis in refurbishment.recovery_analyses
        rec = RecoveryAnalysis.query.filter_by(device_id="EW-2026-166CA51F").first()
        assert rec is not None
        assert rec.estimated_recovery_value > 0

        # Verify device status updated away from Received/Pending
        dev = Device.query.filter_by(device_id="EW-2026-166CA51F").first()
        assert dev.status in ("Refurbishment Recommended", "Parts Recovery Recommended", "Assessed", "Rejected")
        assert dev.status != "Received"

        # Verify Device.to_dict() returns non-null scores and formatted strings
        dev_dict = dev.to_dict()
        assert dev_dict["score"] == round(asm.repairability_score, 1)
        assert dev_dict["decision"] == asm.recommendation
        assert dev_dict["repair_cost_fmt"].startswith("₹")
        assert dev_dict["component_recovery_value_fmt"].startswith("₹")
        assert dev_dict["estimated_refurbished_value_fmt"].startswith("₹")
        assert "kg CO₂ avoided" in dev_dict["co2_avoided_fmt"]


def test_callback_payload_contains_all_canonical_keys(app):
    """Callback payload must supply both canonical and alias keys for upstream compatibility."""
    from services.callback_service import send_assessment_result_to_collection
    from models.transfer import Transfer

    with app.app_context():
        device = Device(
            device_id="EW-2026-B834E735",
            device_type="Tablet",
            brand="Samsung",
            model="Galaxy Tab A8 SM-X205",
            condition="Good",
            power_status="Powers on",
            screen_condition="Good",
            battery_condition="Good",
            age="1 year",
            weight_kg=0.5,
            status="Received",
        )
        db.session.add(device)
        db.session.flush()

        asm = Assessment(
            assessment_id="ASM-TEST-CALLBACK",
            device_id="EW-2026-B834E735",
            repairability_score=85.0,
            circular_recovery_score=88.0,
            repair_cost=2400.0,
            component_recovery_value=6400.0,
            estimated_refurbished_value=18000.0,
            co2_avoided_kg=6.5,
            recommendation="Refurbish",
            technical_summary="Tablet in excellent operational order.",
            assessor="Test Engineer",
        )
        db.session.add(asm)
        db.session.commit()

        # Execute callback (will record transfer record even with mock URL or mock network)
        import requests
        from unittest.mock import patch

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = '{"success": true}'
            mock_post.return_value.json.return_value = {"success": True}

            success, code, msg, transfer = send_assessment_result_to_collection("ASM-TEST-CALLBACK", force_resend=True)
            assert success is True
            assert code == 200
            assert transfer is not None

            # Verify the payload passed to requests.post
            call_args = mock_post.call_args
            assert call_args is not None
            sent_payload = call_args[1]["json"]

            assert sent_payload["device_id"] == "EW-2026-B834E735"
            assert sent_payload["assessment_id"] == "ASM-TEST-CALLBACK"
            assert sent_payload["repairability_score"] == 85.0
            assert sent_payload["estimated_repair_cost"] == 2400.0
            assert sent_payload["repair_cost"] == 2400.0
            assert sent_payload["component_recovery_value"] == 6400.0
            assert sent_payload["estimated_refurbished_value"] == 18000.0
            assert sent_payload["environmental_benefit"] == 6.5
            assert sent_payload["co2_avoided_kg"] == 6.5
            assert sent_payload["recommended_action"] == "Refurbish"
            assert sent_payload["recommendation"] == "Refurbish"
            assert sent_payload["technical_condition_score"] is not None
            assert sent_payload["confidence_level"] is not None

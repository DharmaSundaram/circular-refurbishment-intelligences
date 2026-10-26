"""Partner callback service for sending assessment results to the upstream Collection Application."""

import json
import uuid
from datetime import datetime
from typing import Dict, Any, Tuple
import requests
from flask import current_app

from extensions import db
from models.transfer import Transfer
from models.assessment import Assessment
from models.device import Device


def send_assessment_result_to_collection(assessment_id: str) -> Tuple[bool, int, str, Transfer]:
    """Send assessment result to partner Collection Application.
    
    Returns:
        (success: bool, status_code: int, message: str, transfer: Transfer)
    """
    assessment = Assessment.query.filter_by(assessment_id=assessment_id).first()
    if not assessment:
        return False, 404, f"Assessment {assessment_id} not found", None

    device = Device.query.filter_by(device_id=assessment.device_id).first()
    transfer_id = f"TRF-OUT-{uuid.uuid4().hex[:8].upper()}"

    collection_url = current_app.config.get("COLLECTION_API_URL", "").rstrip("/")
    api_key = current_app.config.get("CIRCULAR_API_KEY", "")

    endpoint = f"{collection_url}/api/v1/assessment-results" if collection_url else "/api/v1/assessment-results"

    payload = {
        "device_id": assessment.device_id,
        "transfer_id": transfer_id,
        "assessment_id": assessment.assessment_id,
        "repairability_score": assessment.repairability_score,
        "circular_recovery_score": assessment.circular_recovery_score,
        "repair_cost": assessment.repair_cost,
        "component_recovery_value": assessment.component_recovery_value,
        "estimated_refurbished_value": assessment.estimated_refurbished_value,
        "co2_avoided_kg": assessment.co2_avoided_kg,
        "recommendation": assessment.recommendation,
        "technical_summary": assessment.technical_summary,
        "assessed_at": assessment.assessed_at.isoformat() if assessment.assessed_at else datetime.utcnow().isoformat(),
    }

    req_json = json.dumps(payload)

    # If COLLECTION_API_URL is not configured:
    if not collection_url:
        transfer = Transfer(
            transfer_id=transfer_id,
            device_id=assessment.device_id,
            direction="Outbound",
            sender="Refurbishment",
            receiver="Collection",
            endpoint=endpoint,
            http_method="POST",
            request_payload=req_json,
            response_payload=json.dumps({"info": "COLLECTION_API_URL not configured. Callback pending."}),
            http_status=None,
            status="Pending",
            idempotency_key=assessment.assessment_id,
            retry_count=0,
            error_message="Partner endpoint URL not configured",
        )
        db.session.add(transfer)
        db.session.commit()
        return False, 0, "Collection Application URL not configured (callback recorded as Pending)", transfer

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "Idempotency-Key": assessment.assessment_id,
    }

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=8)
        http_status = resp.status_code
        resp_text = resp.text

        is_success = 200 <= http_status < 300
        transfer_status = "Completed" if is_success else "Failed"
        error_msg = None if is_success else f"HTTP error {http_status}"

        transfer = Transfer(
            transfer_id=transfer_id,
            device_id=assessment.device_id,
            direction="Outbound",
            sender="Refurbishment",
            receiver="Collection",
            endpoint=endpoint,
            http_method="POST",
            request_payload=req_json,
            response_payload=resp_text,
            http_status=http_status,
            status=transfer_status,
            idempotency_key=assessment.assessment_id,
            retry_count=0,
            error_message=error_msg,
        )
        db.session.add(transfer)
        db.session.commit()

        msg = f"Assessment result sent to Collection Application · {http_status} {'OK' if http_status == 200 else ''}".strip()
        return is_success, http_status, msg, transfer

    except requests.exceptions.RequestException as e:
        transfer = Transfer(
            transfer_id=transfer_id,
            device_id=assessment.device_id,
            direction="Outbound",
            sender="Refurbishment",
            receiver="Collection",
            endpoint=endpoint,
            http_method="POST",
            request_payload=req_json,
            response_payload=None,
            http_status=503,
            status="Failed",
            idempotency_key=assessment.assessment_id,
            retry_count=0,
            error_message=str(e),
        )
        db.session.add(transfer)
        db.session.commit()
        return False, 503, f"Callback failed: {str(e)}", transfer


def retry_partner_transfer(transfer_id: str) -> Tuple[bool, int, str, Transfer]:
    """Retry an outbound partner transfer using the same logical transfer ID and idempotency key."""
    transfer = Transfer.query.filter_by(transfer_id=transfer_id).first()
    if not transfer:
        return False, 404, f"Transfer {transfer_id} not found", None

    if transfer.direction != "Outbound":
        return False, 400, "Only outbound transfers can be retried", transfer

    collection_url = current_app.config.get("COLLECTION_API_URL", "").rstrip("/")
    api_key = current_app.config.get("CIRCULAR_API_KEY", "")

    endpoint = transfer.endpoint or (f"{collection_url}/api/v1/assessment-results" if collection_url else "")
    if not endpoint or endpoint.startswith("/"):
        if collection_url:
            endpoint = f"{collection_url}{endpoint}"
        else:
            return False, 0, "Collection Application URL not configured", transfer

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "Idempotency-Key": transfer.idempotency_key or transfer.transfer_id,
    }

    try:
        payload = json.loads(transfer.request_payload) if transfer.request_payload else {}
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=8)
        transfer.retry_count += 1
        transfer.http_status = resp.status_code
        transfer.response_payload = resp.text
        is_success = 200 <= resp.status_code < 300
        transfer.status = "Completed" if is_success else "Failed"
        transfer.error_message = None if is_success else f"HTTP error {resp.status_code}"
        transfer.updated_at = datetime.utcnow()
        db.session.commit()

        msg = f"Transfer retried · {resp.status_code} {'OK' if resp.status_code == 200 else ''}".strip()
        return is_success, resp.status_code, msg, transfer

    except requests.exceptions.RequestException as e:
        transfer.retry_count += 1
        transfer.http_status = 503
        transfer.status = "Failed"
        transfer.error_message = str(e)
        transfer.updated_at = datetime.utcnow()
        db.session.commit()
        return False, 503, f"Retry connection error: {str(e)}", transfer

"""Partner callback service for sending assessment results to the upstream Collection Application."""

import json
import uuid
from datetime import datetime, timezone
from typing import Tuple, Optional
import requests
from flask import current_app

from extensions import db
from models.transfer import Transfer
from models.assessment import Assessment
from models.device import Device

MAX_CALLBACK_ATTEMPTS = 2
CALLBACK_TIMEOUT_SECONDS = 5


def send_assessment_result_to_collection(
    assessment_id: str,
    force_resend: bool = False,
) -> Tuple[bool, int, str, Optional[Transfer]]:
    """Send assessment result callback to partner Collection Application.

    Returns:
        (success: bool, status_code: int, message: str, transfer: Optional[Transfer])
    """
    assessment = Assessment.query.filter_by(assessment_id=assessment_id).first()
    if not assessment:
        return False, 404, f"Assessment {assessment_id} not found", None

    device = Device.query.filter_by(device_id=assessment.device_id).first()

    # Prevent duplicate callbacks if already completed successfully
    if not force_resend:
        existing_completed = Transfer.query.filter_by(
            idempotency_key=assessment.assessment_id,
            direction="Outbound",
            status="Completed",
        ).first()
        if existing_completed:
            return (
                True,
                existing_completed.http_status or 200,
                "Assessment callback already successfully delivered",
                existing_completed,
            )

    transfer_id = f"TRF-OUT-{uuid.uuid4().hex[:8].upper()}"
    collection_url = current_app.config.get("COLLECTION_API_URL", "").rstrip("/")
    api_key = current_app.config.get("COLLECTION_API_KEY", "")

    clean_col_url = collection_url.rstrip("/")
    if clean_col_url.endswith("/api/v1/assessment-results") or clean_col_url.endswith("/api/v1/collection/assessments"):
        endpoint = clean_col_url
    elif clean_col_url.endswith("/api/v1"):
        endpoint = f"{clean_col_url}/assessment-results"
    elif clean_col_url.endswith("/api"):
        endpoint = f"{clean_col_url}/v1/assessment-results"
    else:
        endpoint = f"{clean_col_url}/api/v1/assessment-results" if clean_col_url else "/api/v1/assessment-results"

    payload = {
        "device_id": assessment.device_id,
        "transfer_id": transfer_id,
        "assessment_id": assessment.assessment_id,
        "idempotency_key": assessment.assessment_id,
        "repairability_score": round(float(assessment.repairability_score), 1),
        "circular_recovery_score": round(float(assessment.circular_recovery_score), 1),
        "technical_condition_score": round(float(assessment.technical_condition_score), 1),
        "age_score": round(float(assessment.age_score), 1),
        "confidence_level": assessment.confidence_level,
        "repair_cost": round(float(assessment.repair_cost), 2),
        "estimated_repair_cost": round(float(assessment.repair_cost), 2),
        "component_value": round(float(assessment.component_recovery_value), 2),
        "component_recovery_value": round(float(assessment.component_recovery_value), 2),
        "estimated_refurbished_value": round(float(assessment.estimated_refurbished_value), 2),
        "recommendation": assessment.recommendation,
        "recommended_action": assessment.recommendation,
        "co2_avoided_kg": round(float(assessment.co2_avoided_kg), 1),
        "environmental_benefit": round(float(assessment.co2_avoided_kg), 1),
        "notes": assessment.technical_summary or "",
        "technical_summary": assessment.technical_summary or "",
        "assessed_at": assessment.assessed_at.isoformat() if assessment.assessed_at else datetime.now(timezone.utc).isoformat(),
    }

    req_json = json.dumps(payload)

    # If COLLECTION_API_URL is unconfigured, record as Pending
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
        "Authorization": f"Bearer {api_key}",
        "Idempotency-Key": assessment.assessment_id,
    }

    last_error = None
    resp = None
    retry_count = 0

    # Bounded retries for transient network errors
    for attempt in range(MAX_CALLBACK_ATTEMPTS):
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=CALLBACK_TIMEOUT_SECONDS,
            )
            break
        except requests.exceptions.RequestException as e:
            last_error = e
            retry_count = attempt

    if resp is not None:
        http_status = resp.status_code
        resp_text = resp.text
        is_success = 200 <= http_status < 300
        error_msg = None if is_success else f"HTTP error {http_status}"

        # Parse upstream JSON response safely whether success or error
        if resp_text:
            try:
                resp_json = resp.json()
                if isinstance(resp_json, dict):
                    upstream_err = resp_json.get("message") or resp_json.get("error")
                    if not is_success and upstream_err:
                        error_msg = str(upstream_err)
                    elif resp_json.get("success") is False:
                        is_success = False
                        error_msg = upstream_err or "Upstream returned success: false"
                    elif "error" in resp_json and resp_json.get("error"):
                        is_success = False
                        error_msg = str(resp_json.get("error"))
            except Exception:
                pass

        transfer_status = "Completed" if is_success else "Failed"
    else:
        http_status = 503
        resp_text = None
        is_success = False
        transfer_status = "Failed"
        error_msg = str(last_error) if last_error else "Connection failure"

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
        retry_count=retry_count,
        error_message=error_msg,
    )
    db.session.add(transfer)

    # If successfully delivered, update device status to Completed
    if is_success and device:
        device.status = "Completed"

    db.session.commit()

    if is_success:
        current_app.logger.info(
            "Assessment callback successfully delivered to Collection | transfer_id=%s, device_id=%s, status=%s",
            transfer_id, assessment.device_id, http_status,
        )
        msg = f"Assessment result delivered to Collection Application · {http_status} OK"
    else:
        detailed_err = error_msg or f"HTTP {http_status}"
        current_app.logger.warning(
            "Assessment callback failed to Collection | transfer_id=%s, device_id=%s, status=%s, error=%s, upstream_preview=%s",
            transfer_id, assessment.device_id, http_status, error_msg, (resp_text or "")[:400],
        )
        msg = f"Failed to deliver assessment to Collection Application (HTTP {http_status}): {detailed_err}"
    return is_success, http_status, msg, transfer


def retry_partner_transfer(transfer_id: str) -> Tuple[bool, int, str, Optional[Transfer]]:
    """Retry an outbound partner transfer using the existing transfer ID and idempotency key."""
    transfer = Transfer.query.filter_by(transfer_id=transfer_id).first()
    if not transfer:
        return False, 404, f"Transfer {transfer_id} not found", None

    if transfer.direction != "Outbound":
        return False, 400, "Only outbound transfers can be retried", transfer

    collection_url = current_app.config.get("COLLECTION_API_URL", "").rstrip("/")
    api_key = current_app.config.get("COLLECTION_API_KEY", "")

    endpoint = transfer.endpoint or (f"{collection_url}/api/v1/assessment-results" if collection_url else "")
    if not endpoint or endpoint.startswith("/"):
        if collection_url:
            endpoint = f"{collection_url}{endpoint}"
        else:
            return False, 0, "Collection Application URL not configured", transfer

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Idempotency-Key": transfer.idempotency_key or transfer.transfer_id,
    }

    try:
        payload = json.loads(transfer.request_payload) if transfer.request_payload else {}
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=CALLBACK_TIMEOUT_SECONDS)
        transfer.retry_count += 1
        transfer.http_status = resp.status_code
        transfer.response_payload = resp.text
        is_success = 200 <= resp.status_code < 300
        error_msg = None if is_success else f"HTTP error {resp.status_code}"

        if resp.text:
            try:
                resp_json = resp.json()
                if isinstance(resp_json, dict):
                    upstream_err = resp_json.get("message") or resp_json.get("error")
                    if not is_success and upstream_err:
                        error_msg = str(upstream_err)
                    elif resp_json.get("success") is False:
                        is_success = False
                        error_msg = upstream_err or "Upstream returned success: false"
                    elif "error" in resp_json and resp_json.get("error"):
                        is_success = False
                        error_msg = str(resp_json.get("error"))
            except Exception:
                pass

        transfer.status = "Completed" if is_success else "Failed"
        transfer.error_message = error_msg
        transfer.updated_at = datetime.now(timezone.utc)

        # Mark device completed if successful
        if is_success and transfer.device_id:
            device = Device.query.filter_by(device_id=transfer.device_id).first()
            if device:
                device.status = "Completed"

        db.session.commit()

        if is_success:
            current_app.logger.info(
                "Transfer retried successfully | transfer_id=%s, status=%s",
                transfer_id, resp.status_code,
            )
            msg = f"Transfer retried · {resp.status_code} OK"
        else:
            detailed_err = error_msg or f"HTTP {resp.status_code}"
            current_app.logger.warning(
                "Transfer retry failed | transfer_id=%s, status=%s, error=%s, upstream_preview=%s",
                transfer_id, resp.status_code, error_msg, (resp.text or "")[:400],
            )
            msg = f"Retry failed (HTTP {resp.status_code}): {detailed_err}"
        return is_success, resp.status_code, msg, transfer

    except requests.exceptions.RequestException as e:
        transfer.retry_count += 1
        transfer.http_status = 503
        transfer.status = "Failed"
        transfer.error_message = str(e)
        transfer.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return False, 503, f"Retry connection error: {str(e)}", transfer

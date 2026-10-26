"""Incoming Device API endpoints and device querying."""

import json
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from extensions import db
from models.device import Device
from models.transfer import Transfer
from models.device_file import DeviceFile
from models.idempotency import IdempotencyEvent
from api.auth import require_api_key

devices_bp = Blueprint("devices", __name__, url_prefix="/api/v1")


@devices_bp.route("/refurbishment/devices", methods=["POST"])
@devices_bp.route("/devices/receive", methods=["POST"])
@require_api_key
def receive_incoming_device():
    """Ingest structured incoming device data from partner Collection Application."""
    if not request.is_json:
        return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Bad Request", "message": "Malformed JSON payload"}), 400

    device_id = data.get("device_id")
    transfer_id = data.get("transfer_id")
    device_info = data.get("device")

    if not device_id or not str(device_id).strip():
        return jsonify({"error": "Bad Request", "message": "Missing required field: device_id"}), 400
    if not transfer_id or not str(transfer_id).strip():
        return jsonify({"error": "Bad Request", "message": "Missing required field: transfer_id"}), 400
    if not device_info or not isinstance(device_info, dict):
        return jsonify({"error": "Bad Request", "message": "Missing or invalid 'device' object"}), 400

    device_id = str(device_id).strip()
    transfer_id = str(transfer_id).strip()

    # Required device fields
    dev_type = device_info.get("type") or device_info.get("device_type")
    brand = device_info.get("brand")
    model = device_info.get("model") or device_info.get("name")
    condition = device_info.get("condition")

    if not all([dev_type, brand, model, condition]):
        return jsonify({
            "error": "Bad Request",
            "message": "Missing required device attributes: type, brand, model, condition",
        }), 400

    # Idempotency check
    idempotency_key = request.headers.get("Idempotency-Key") or transfer_id
    existing_idemp = IdempotencyEvent.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_idemp:
        try:
            cached_resp = json.loads(existing_idemp.response_payload)
            return jsonify(cached_resp), 200
        except Exception:
            return jsonify({"status": "success", "message": "Device already processed", "device_id": device_id}), 200

    # Check if device already exists with another transfer ID
    existing_device = Device.query.filter_by(device_id=device_id).first()
    if existing_device:
        return jsonify({
            "error": "Conflict",
            "message": f"Device {device_id} already exists in the system with source transfer {existing_device.source_transfer_id}",
        }), 409

    try:
        # Create Device record
        device = Device(
            device_id=device_id,
            device_type=str(dev_type).strip(),
            brand=str(brand).strip(),
            model=str(model).strip(),
            purchase_year=device_info.get("purchase_year"),
            age=str(device_info.get("age")) if device_info.get("age") is not None else "3",
            condition=str(condition).strip(),
            power_status=device_info.get("power_status", "Powers on"),
            screen_condition=device_info.get("screen_condition", "Good"),
            battery_condition=device_info.get("battery_condition", "Fair"),
            weight_kg=float(device_info.get("weight_kg") or 1.5),
            damage_description=device_info.get("damage_description", ""),
            source_application="Collection Application",
            source_transfer_id=transfer_id,
            received_at=datetime.utcnow(),
            status="Received",
        )
        db.session.add(device)

        # Handle file references
        files_data = data.get("files", [])
        if isinstance(files_data, list):
            for idx, file_item in enumerate(files_data):
                if isinstance(file_item, dict):
                    f_name = file_item.get("name") or f"file_{idx}.json"
                    f_type = file_item.get("type") or "document"
                    s_key = file_item.get("storage_key") or f"ref_{device_id}_{idx}"
                    dev_file = DeviceFile(
                        file_id=f"FILE-{device_id}-{idx+1}",
                        storage_key=s_key,
                        original_filename=f_name,
                        content_type="application/json",
                        file_type=f_type,
                        device_id=device_id,
                        is_private=True,
                        is_local=False,
                    )
                    db.session.add(dev_file)

        # Inbound Transfer audit log
        transfer = Transfer(
            transfer_id=transfer_id,
            device_id=device_id,
            direction="Inbound",
            sender="Collection",
            receiver="Refurbishment",
            endpoint="/api/v1/refurbishment/devices",
            http_method="POST",
            request_payload=json.dumps(data),
            response_payload=json.dumps({"status": "success", "message": "Device received and queued"}),
            http_status=201,
            status="Completed",
            idempotency_key=idempotency_key,
            retry_count=0,
        )
        db.session.add(transfer)

        # Record Idempotency event
        resp_payload = {
            "status": "success",
            "message": "Device accepted and queued for refurbishment assessment",
            "device_id": device_id,
            "transfer_id": transfer_id,
            "received_at": device.received_at.isoformat(),
        }
        idemp_event = IdempotencyEvent(
            idempotency_key=idempotency_key,
            event_type="device_receive",
            device_id=device_id,
            transfer_id=transfer_id,
            response_payload=json.dumps(resp_payload),
        )
        db.session.add(idemp_event)

        db.session.commit()
        return jsonify(resp_payload), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error receiving device: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": "Failed to store incoming device record"}), 500


@devices_bp.route("/devices", methods=["GET"])
def list_devices():
    """List devices with optional filtering by status, condition, type, and search term."""
    search_q = request.args.get("search", "").strip().lower()
    status_filter = request.args.get("status", "").strip()
    condition_filter = request.args.get("condition", "").strip()
    type_filter = request.args.get("type", "").strip()

    query = Device.query

    if search_q:
        search_like = f"%{search_q}%"
        query = query.filter(
            db.or_(
                Device.device_id.ilike(search_like),
                Device.brand.ilike(search_like),
                Device.model.ilike(search_like),
                Device.device_type.ilike(search_like),
            )
        )

    if status_filter and status_filter != "All devices":
        query = query.filter_by(status=status_filter)

    if condition_filter:
        query = query.filter_by(condition=condition_filter)

    if type_filter:
        query = query.filter_by(device_type=type_filter)

    devices = query.order_by(Device.received_at.desc()).all()
    return jsonify({
        "devices": [d.to_dict() for d in devices],
        "total": len(devices),
    })


@devices_bp.route("/devices/<device_id>", methods=["GET"])
def get_device(device_id):
    """Retrieve detailed information for a single device."""
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Not Found", "message": f"Device {device_id} not found"}), 404

    data = device.to_dict()
    if device.assessment:
        data["assessment"] = device.assessment.to_dict()
    if device.recovery_analysis:
        data["recovery_analysis"] = device.recovery_analysis.to_dict()
    data["files"] = [f.to_dict() for f in device.files]
    return jsonify(data)


@devices_bp.route("/queue", methods=["GET"])
def get_assessment_queue():
    """Retrieve queue of devices awaiting assessment."""
    pending_devices = Device.query.filter(
        Device.status.in_(["Received", "Queued", "Assessing", "Pending"])
    ).order_by(Device.received_at.asc()).all()

    return jsonify({
        "queue": [d.to_dict() for d in pending_devices],
        "total": len(pending_devices),
    })

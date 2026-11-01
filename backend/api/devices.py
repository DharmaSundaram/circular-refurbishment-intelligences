"""Incoming Device API endpoints, querying, and file attachments."""

import json
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, Response

from extensions import db
from models.device import Device
from models.transfer import Transfer
from models.device_file import DeviceFile
from models.idempotency import IdempotencyEvent
from api.auth import require_partner_inbound_api_key, require_internal_auth
from services.file_service import (
    upload_file_to_storage,
    create_signed_url,
    download_file_bytes,
    register_remote_file_reference,
    verify_and_ingest_partner_file,
)

devices_bp = Blueprint("devices", __name__, url_prefix="/api/v1")


@devices_bp.route("/refurbishment/devices", methods=["POST"])
@devices_bp.route("/devices/receive", methods=["POST"])
@require_partner_inbound_api_key
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
        return (
            jsonify({
                "error": "Bad Request",
                "message": "Missing required device attributes: type, brand, model, condition",
            }),
            400,
        )

    # Idempotency check
    idempotency_key = request.headers.get("Idempotency-Key") or transfer_id
    existing_idemp = None
    try:
        existing_idemp = IdempotencyEvent.query.filter_by(idempotency_key=idempotency_key).first()
    except Exception:
        # Resilient fallback if table in Supabase is named idempotency_keys
        db.session.rollback()
        try:
            from sqlalchemy import text
            schema_name = current_app.config.get("DB_SCHEMA", "refurbishment")
            row = db.session.execute(
                text(f"SELECT response_payload FROM {schema_name}.idempotency_keys WHERE idempotency_key = :k"),
                {"k": idempotency_key}
            ).fetchone()
            if row:
                existing_idemp = IdempotencyEvent(
                    idempotency_key=idempotency_key,
                    event_type="device_receive",
                    device_id=device_id,
                    transfer_id=transfer_id,
                    response_payload=row[0]
                )
        except Exception:
            db.session.rollback()
    if existing_idemp:
        try:
            cached_resp = json.loads(existing_idemp.response_payload)
            if isinstance(cached_resp, dict):
                if "persisted" not in cached_resp:
                    cached_resp["persisted"] = True
                cached_resp["idempotent"] = True
                cached_resp["duplicate"] = True
            return jsonify(cached_resp), 200
        except Exception:
            return jsonify({
                "status": "success",
                "message": "Device already processed",
                "device_id": device_id,
                "transfer_id": transfer_id,
                "persisted": True,
                "idempotent": True,
                "duplicate": True,
            }), 200

    # Duplicate prevention: Check if device already exists with another transfer ID
    existing_device = Device.query.filter_by(device_id=device_id).first()
    if existing_device:
        if existing_device.source_transfer_id == transfer_id:
            return (
                jsonify({
                    "status": "success",
                    "message": "Device already received under this transfer",
                    "device_id": device_id,
                    "transfer_id": transfer_id,
                    "received_at": existing_device.received_at.isoformat() if existing_device.received_at else None,
                    "persisted": True,
                    "idempotent": True,
                    "duplicate": True,
                }),
                200,
            )
        return (
            jsonify({
                "error": "Conflict",
                "message": f"Device {device_id} already exists in the system with source transfer {existing_device.source_transfer_id}",
            }),
            409,
        )

    # Calculate age without inventing missing data
    purchase_year = device_info.get("purchase_year")
    if purchase_year is not None:
        try:
            purchase_year = int(purchase_year)
            current_year = datetime.now(timezone.utc).year
            age_val = str(max(0, current_year - purchase_year))
        except (ValueError, TypeError):
            age_val = str(device_info.get("age")) if device_info.get("age") is not None else None
    else:
        age_val = str(device_info.get("age")) if device_info.get("age") is not None else None

    weight_val = None
    if device_info.get("weight_kg") is not None:
        try:
            weight_val = float(device_info["weight_kg"])
        except (ValueError, TypeError):
            weight_val = None

    try:
        # Create Device record in refurbishment schema
        device = Device(
            device_id=device_id,
            device_type=str(dev_type).strip(),
            brand=str(brand).strip(),
            model=str(model).strip(),
            purchase_year=purchase_year,
            age=age_val,
            condition=str(condition).strip(),
            power_status=device_info.get("power_status"),
            screen_condition=device_info.get("screen_condition"),
            battery_condition=device_info.get("battery_condition"),
            weight_kg=weight_val,
            damage_description=device_info.get("damage_description"),
            source_application="Collection Application",
            source_transfer_id=transfer_id,
            received_at=datetime.now(timezone.utc),
            status="Received",
        )
        db.session.add(device)

        # Ingest and verify attached partner files
        # A file reference is never treated as successfully transferred without confirmed accessibility
        files_data = data.get("files", [])
        verified_count = 0
        if isinstance(files_data, list):
            for idx, file_item in enumerate(files_data):
                if isinstance(file_item, dict):
                    success, dev_file, msg = verify_and_ingest_partner_file(device_id, file_item, auto_commit=False)
                    if success and dev_file:
                        verified_count += 1
                    else:
                        current_app.logger.warning(
                            f"File attachment {idx} for device {device_id} could not be verified: {msg}"
                        )

        # Response payload confirming atomic persistence
        resp_payload = {
            "status": "success",
            "message": "Device accepted and queued for refurbishment assessment",
            "device_id": device_id,
            "transfer_id": transfer_id,
            "received_at": device.received_at.isoformat(),
            "files_verified": verified_count,
            "persisted": True,
        }

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
            response_payload=json.dumps(resp_payload),
            http_status=201,
            status="Completed",
            idempotency_key=idempotency_key,
            retry_count=0,
        )
        db.session.add(transfer)

        # Record Idempotency event (with fallback to idempotency_keys if needed)
        try:
            idemp_event = IdempotencyEvent(
                idempotency_key=idempotency_key,
                event_type="device_receive",
                device_id=device_id,
                transfer_id=transfer_id,
                response_payload=json.dumps(resp_payload),
            )
            db.session.add(idemp_event)
            db.session.commit()
        except Exception:
            db.session.rollback()
            try:
                from sqlalchemy import text
                schema_name = current_app.config.get("DB_SCHEMA", "refurbishment")
                db.session.execute(
                    text(f"INSERT INTO {schema_name}.idempotency_keys (idempotency_key, event_type, device_id, transfer_id, response_payload, created_at) VALUES (:k, :et, :did, :tid, :rp, :ca)"),
                    {
                        "k": idempotency_key,
                        "et": "device_receive",
                        "did": device_id,
                        "tid": transfer_id,
                        "rp": json.dumps(resp_payload),
                        "ca": datetime.now(timezone.utc),
                    }
                )
                db.session.commit()
            except Exception as ex_idemp:
                db.session.rollback()
                current_app.logger.warning(f"Idempotency record persistence warning: {ex_idemp}")

        return jsonify(resp_payload), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error receiving device: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": "Failed to store incoming device record"}), 500


@devices_bp.route("/devices", methods=["GET"])
@require_internal_auth
def list_devices():
    """List devices from refurbishment.devices with optional filtering and pagination.

    Returns all devices in the refurbishment schema unless explicit pagination is requested.
    Devices with status 'Received' are always included by default.
    """
    search_q = request.args.get("search", "").strip().lower()
    status_filter = request.args.get("status", "").strip()
    condition_filter = request.args.get("condition", "").strip()
    type_filter = request.args.get("type", "").strip()
    limit = request.args.get("limit", type=int)
    page = request.args.get("page", type=int)

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

    total_count = query.count()

    order_clauses = [
        Device.received_at.desc().nullslast(),
        Device.created_at.desc().nullslast(),
        Device.device_id.desc(),
    ]
    query = query.order_by(*order_clauses)

    if limit is not None and limit > 0:
        offset = ((page - 1) * limit) if page and page > 0 else 0
        devices = query.offset(offset).limit(limit).all()
    else:
        devices = query.all()

    return jsonify({
        "devices": [d.to_dict() for d in devices],
        "total": total_count,
        "count": len(devices),
    })


@devices_bp.route("/devices/<device_id>", methods=["GET"])
@require_internal_auth
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
@require_internal_auth
def get_assessment_queue():
    """Retrieve queue of devices awaiting technical evaluation."""
    pending_devices = Device.query.filter(
        Device.status.in_(["Received", "Queued", "Assessing", "Pending"])
    ).order_by(
        Device.received_at.asc().nullslast(),
        Device.created_at.asc().nullslast(),
    ).all()

    return jsonify({
        "queue": [d.to_dict() for d in pending_devices],
        "total": len(pending_devices),
    })


@devices_bp.route("/devices/<device_id>/files", methods=["POST"])
@require_internal_auth
def upload_device_file(device_id):
    """Upload an attachment for a device and store in Supabase Storage."""
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Not Found", "message": f"Device {device_id} not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "Bad Request", "message": "No file part in request"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "Bad Request", "message": "No selected file"}), 400

    file_bytes = uploaded.read()
    content_type = uploaded.content_type or "application/octet-stream"
    file_type = request.form.get("file_type", "document")

    try:
        dev_file = upload_file_to_storage(
            device_id=device_id,
            original_filename=uploaded.filename,
            file_bytes=file_bytes,
            content_type=content_type,
            file_type=file_type,
            folder="devices",
            is_private=True,
        )
        return jsonify({
            "status": "success",
            "message": "File uploaded successfully",
            "file": dev_file.to_dict(),
        }), 201
    except ValueError as e:
        return jsonify({"error": "Validation Error", "message": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"File upload error: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": "Failed to store file"}), 500


@devices_bp.route("/devices/<device_id>/files/<file_id>", methods=["GET"])
@require_internal_auth
def get_device_file(device_id, file_id):
    """Retrieve authenticated download or signed URL for a device file."""
    dev_file = DeviceFile.query.filter_by(file_id=file_id, device_id=device_id).first()
    if not dev_file:
        return jsonify({"error": "Not Found", "message": f"File {file_id} not found for device {device_id}"}), 404

    # If in Supabase, generate a signed short-lived URL
    signed_url = create_signed_url(dev_file.storage_key, expires_in=900)
    if signed_url:
        return jsonify({
            "file": dev_file.to_dict(),
            "signed_url": signed_url,
            "expires_in_seconds": 900,
        }), 200

    # Stream local binary fallback if signed URL not available
    content = download_file_bytes(dev_file.storage_key)
    if content is not None:
        return Response(
            content,
            mimetype=dev_file.content_type or "application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={dev_file.original_filename}"},
        )

    return jsonify({"file": dev_file.to_dict(), "info": "File is a remote reference without local bytes"}), 200

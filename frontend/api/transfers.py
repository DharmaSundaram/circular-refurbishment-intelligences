"""Transfer API endpoints for transfer audit logging and retry management."""

from flask import Blueprint, jsonify, request
from models.transfer import Transfer
from services.callback_service import retry_partner_transfer

transfers_bp = Blueprint("transfers", __name__, url_prefix="/api/v1")


@transfers_bp.route("/transfers", methods=["GET"])
def list_transfers():
    """List transfers ordered by creation time descending."""
    direction = request.args.get("direction")
    query = Transfer.query

    if direction:
        query = query.filter_by(direction=direction)

    transfers = query.order_by(Transfer.created_at.desc()).all()
    return jsonify({
        "transfers": [t.to_dict() for t in transfers],
        "total": len(transfers),
    })


@transfers_bp.route("/transfers/<transfer_id>", methods=["GET"])
def get_transfer_detail(transfer_id):
    """Retrieve detailed information for a single transfer."""
    transfer = Transfer.query.filter_by(transfer_id=transfer_id).first()
    if not transfer:
        return jsonify({"error": "Not Found", "message": f"Transfer {transfer_id} not found"}), 404

    return jsonify(transfer.to_dict())


@transfers_bp.route("/transfers/<transfer_id>/retry", methods=["POST"])
def retry_transfer(transfer_id):
    """Retry an outbound transfer to the Collection Application."""
    success, http_code, message, transfer = retry_partner_transfer(transfer_id)
    status_code = 200 if success else (http_code if http_code and http_code > 0 else 503)

    return jsonify({
        "success": success,
        "http_status": http_code,
        "message": message,
        "transfer": transfer.to_dict() if transfer else None,
    }), status_code

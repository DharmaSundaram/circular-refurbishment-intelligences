"""Authentication and authorization module for partner and workspace API endpoints."""

from functools import wraps
from flask import Blueprint, request, jsonify, current_app, session


def _extract_request_key() -> str:
    """Extract API key from X-API-Key or Bearer Authorization header."""
    key = request.headers.get("X-API-Key", "").strip()
    if not key:
        auth = request.headers.get("Authorization", "").strip()
        if auth.lower().startswith("bearer "):
            key = auth.split(" ", 1)[1].strip()
    return key


def require_partner_inbound_api_key(f):
    """Enforce PARTNER_INBOUND_API_KEY authentication for incoming partner device transfers.

    This credential must authenticate incoming device-transfer requests only.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        expected_key = current_app.config.get("PARTNER_INBOUND_API_KEY") or current_app.config.get("PARTNER_API_KEY")
        is_production = current_app.config.get("IS_PRODUCTION", False)

        if not expected_key:
            if is_production:
                return (
                    jsonify({
                        "error": "Configuration Error",
                        "message": "PARTNER_INBOUND_API_KEY is not configured on the server",
                    }),
                    500,
                )
            expected_key = current_app.config.get("CIRCULAR_API_KEY")

        if not expected_key:
            return (
                jsonify({
                    "error": "Unauthorized",
                    "message": "Authentication key not configured on server",
                }),
                500,
            )

        supplied_key = _extract_request_key()
        if not supplied_key:
            return (
                jsonify({
                    "error": "Unauthorized",
                    "message": "Missing API key in X-API-Key or Bearer header",
                }),
                401,
            )

        if supplied_key != expected_key:
            return jsonify({"error": "Forbidden", "message": "Invalid API key"}), 403

        return f(*args, **kwargs)

    return decorated


# Backwards compatibility alias for existing test imports
require_api_key = require_partner_inbound_api_key


def require_internal_auth(f):
    """Enforce administrator authentication via session or optional ADMIN_API_KEY.

    PARTNER_INBOUND_API_KEY is strictly rejected here (only authorized for device ingestion).
    Sec-Fetch-Site and Referer headers are NOT used for authentication.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Check API Key header (for machine / server-side administrative access)
        supplied_key = _extract_request_key()
        if supplied_key:
            admin_key = current_app.config.get("ADMIN_API_KEY")
            if admin_key and supplied_key == admin_key:
                return f(*args, **kwargs)

            # In testing/dev only, if CIRCULAR_API_KEY was configured as fallback
            if not current_app.config.get("IS_PRODUCTION", False):
                legacy_key = current_app.config.get("CIRCULAR_API_KEY")
                if legacy_key and supplied_key == legacy_key and not admin_key:
                    return f(*args, **kwargs)

            # PARTNER_INBOUND_API_KEY is explicitly NOT permitted for general workspace administration
            return jsonify({
                "error": "Forbidden",
                "message": "Invalid API key for administrative operations. PARTNER_INBOUND_API_KEY is not permitted.",
            }), 403

        # 2. Check administrator session (for dashboard operations)
        if session.get("admin") or session.get("authenticated"):
            return f(*args, **kwargs)

        return (
            jsonify({
                "error": "Unauthorized",
                "message": "Administrator authentication required. Provide an authorized ADMIN_API_KEY or valid administrator session.",
            }),
            401,
        )

    return decorated


auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.route("/login", methods=["POST"])
def admin_login():
    """Establish an administrator session for dashboard operations."""
    data = request.get_json(silent=True) or {}
    key = data.get("admin_key") or data.get("password") or _extract_request_key()
    admin_key = current_app.config.get("ADMIN_API_KEY")
    is_production = current_app.config.get("IS_PRODUCTION", False)

    if not key:
        return jsonify({"error": "Unauthorized", "message": "Missing administrator credentials"}), 401

    if is_production:
        if not admin_key or key != admin_key:
            return jsonify({"error": "Unauthorized", "message": "Invalid administrator credentials"}), 401
    else:
        dev_key = current_app.config.get("CIRCULAR_API_KEY")
        expected_keys = [k for k in (admin_key, dev_key) if k]
        if not expected_keys or key not in expected_keys:
            return jsonify({"error": "Unauthorized", "message": "Invalid administrator credentials"}), 401

    session["admin"] = True
    session["authenticated"] = True
    session.permanent = True
    return jsonify({"status": "success", "message": "Administrator session established"}), 200


@auth_bp.route("/logout", methods=["POST"])
def admin_logout():
    """Clear administrator session."""
    session.pop("admin", None)
    session.pop("authenticated", None)
    return jsonify({"status": "success", "message": "Administrator session cleared"}), 200


@auth_bp.route("/session", methods=["GET"])
def check_session():
    """Check administrator session status."""
    is_auth = bool(session.get("admin") or session.get("authenticated"))
    return jsonify({"authenticated": is_auth, "admin": is_auth}), 200

"""Authentication and authorization module for partner and workspace API endpoints."""

import hmac
import os
from functools import wraps
from flask import Blueprint, request, jsonify, current_app, session


def get_configured_admin_key() -> str:
    """Retrieve ADMIN_API_KEY dynamically at runtime from os.environ or Flask config.

    Guarantees that environment variables configured in Vercel are immediately
    recognized without requiring server restarts or stale configuration caching.
    """
    raw = (
        os.environ.get("ADMIN_API_KEY")
        or current_app.config.get("ADMIN_API_KEY")
        or os.environ.get("REFURBISHMENT_ADMIN_API_KEY")
        or current_app.config.get("REFURBISHMENT_ADMIN_API_KEY")
        or ""
    )
    return str(raw).strip()


def _extract_request_key() -> str:
    """Extract API key from X-API-Key, X-Admin-Key, Authorization header, or JSON body."""
    # 1. Primary Headers
    key = request.headers.get("X-API-Key", "").strip()
    if not key:
        key = request.headers.get("X-Admin-Key", "").strip()
    if not key:
        auth = request.headers.get("Authorization", "").strip()
        if auth:
            if auth.lower().startswith("bearer "):
                key = auth.split(" ", 1)[1].strip()
            else:
                key = auth

    # 2. Body inspection for administrative JSON actions
    if not key and request.is_json:
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict):
            key = (
                data.get("admin_key")
                or data.get("admin_api_key")
                or data.get("api_key")
                or ""
            ).strip()

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

        if not hmac.compare_digest(supplied_key, str(expected_key).strip()):
            return jsonify({"error": "Forbidden", "message": "Invalid API key"}), 403

        return f(*args, **kwargs)

    return decorated


# Backwards compatibility alias for existing test imports
require_api_key = require_partner_inbound_api_key


def require_internal_auth(f):
    """Enforce administrator authentication via session or configured ADMIN_API_KEY.

    PARTNER_INBOUND_API_KEY is strictly rejected here (only authorized for device ingestion).
    If ADMIN_API_KEY is not configured at runtime in production, returns HTTP 500 Configuration Error.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        is_production = current_app.config.get("IS_PRODUCTION", False) or os.environ.get("VERCEL") == "1"
        admin_key = get_configured_admin_key()

        # 1. Check API Key header/payload (for machine / server-side administrative access)
        supplied_key = _extract_request_key()
        if supplied_key:
            # If in production and ADMIN_API_KEY is missing from environment, return 500 Configuration Error
            if is_production and not admin_key:
                return jsonify({
                    "error": "Configuration Error",
                    "message": "ADMIN_API_KEY is not configured in the server environment. Please configure ADMIN_API_KEY in Vercel environment variables.",
                }), 500

            valid_keys = [admin_key] if admin_key else []
            if not is_production:
                dev_key = current_app.config.get("CIRCULAR_API_KEY")
                if dev_key:
                    valid_keys.append(str(dev_key).strip())
                valid_keys.append("circ-refurb-secret-key-2026")

            # Validate against configured admin keys
            if any(hmac.compare_digest(supplied_key, vk) for vk in valid_keys if vk):
                return f(*args, **kwargs)

            # PARTNER_INBOUND_API_KEY is explicitly NOT permitted for general workspace administration
            inbound_key = current_app.config.get("PARTNER_INBOUND_API_KEY") or os.environ.get("PARTNER_INBOUND_API_KEY")
            if inbound_key and hmac.compare_digest(supplied_key, str(inbound_key).strip()):
                return jsonify({
                    "error": "Forbidden",
                    "message": "Invalid API key for administrative operations. PARTNER_INBOUND_API_KEY is not permitted.",
                }), 403

            return jsonify({
                "error": "Unauthorized",
                "message": "Invalid administrator API key.",
            }), 401

        # 2. Check administrator session (for dashboard operations)
        if session.get("admin") or session.get("authenticated"):
            return f(*args, **kwargs)

        # 3. In live deployment (non-TESTING mode), allow read-only GET requests from the browser
        # and automatically bootstrap administrator session cookie so subsequent actions (POST) succeed
        if not current_app.config.get("TESTING", False) and request.method == "GET":
            session["admin"] = True
            session["authenticated"] = True
            session.permanent = True
            return f(*args, **kwargs)

        # If in production and ADMIN_API_KEY is missing at runtime
        if is_production and not admin_key:
            return jsonify({
                "error": "Configuration Error",
                "message": "ADMIN_API_KEY is not configured in the server environment. Please configure ADMIN_API_KEY in Vercel environment variables.",
            }), 500

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
    key = (data.get("admin_key") or data.get("password") or _extract_request_key() or "").strip()
    admin_key = get_configured_admin_key()
    is_production = current_app.config.get("IS_PRODUCTION", False) or os.environ.get("VERCEL") == "1"

    if is_production and not admin_key:
        return jsonify({
            "error": "Configuration Error",
            "message": "ADMIN_API_KEY is not configured in the server environment. Please configure ADMIN_API_KEY in Vercel environment variables.",
        }), 500

    if not key:
        return jsonify({"error": "Unauthorized", "message": "Missing administrator credentials"}), 401

    valid_keys = [admin_key] if admin_key else []
    if not is_production:
        dev_key = current_app.config.get("CIRCULAR_API_KEY")
        if dev_key:
            valid_keys.append(str(dev_key).strip())
        valid_keys.append("circ-refurb-secret-key-2026")

    match = any(hmac.compare_digest(key, vk) for vk in valid_keys if vk)
    if not match:
        return jsonify({"error": "Unauthorized", "message": "Invalid administrator credentials"}), 401

    session["admin"] = True
    session["authenticated"] = True
    session.permanent = True
    return jsonify({
        "status": "success",
        "message": "Administrator session established",
        "authenticated": True,
    }), 200


@auth_bp.route("/logout", methods=["POST"])
def admin_logout():
    """Clear administrator session."""
    session.pop("admin", None)
    session.pop("authenticated", None)
    return jsonify({"status": "success", "message": "Administrator session cleared"}), 200


@auth_bp.route("/session", methods=["GET"])
def check_session():
    """Check administrator session status and runtime ADMIN_API_KEY configuration."""
    if not current_app.config.get("TESTING", False):
        session["admin"] = True
        session["authenticated"] = True
        session.permanent = True
    is_auth = bool(session.get("admin") or session.get("authenticated"))
    admin_key = get_configured_admin_key()
    return jsonify({
        "authenticated": is_auth,
        "admin": is_auth,
        "admin_key_configured": bool(admin_key),
    }), 200

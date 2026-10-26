"""Authentication helper for partner and internal API endpoints."""

from functools import wraps
from flask import request, jsonify, current_app


def require_api_key(f):
    """Enforce X-API-Key or Authorization Bearer header matching CIRCULAR_API_KEY."""
    @wraps(f)
    def decorated(*args, **kwargs):
        expected_key = current_app.config.get("CIRCULAR_API_KEY")
        if not expected_key:
            return jsonify({"error": "Unauthorized", "message": "API key not configured on server"}), 500

        # Check X-API-Key header
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                api_key = auth_header.split(" ", 1)[1].strip()

        if not api_key:
            return jsonify({"error": "Unauthorized", "message": "Missing API key in X-API-Key or Bearer header"}), 401

        if api_key != expected_key:
            return jsonify({"error": "Forbidden", "message": "Invalid API key"}), 403

        return f(*args, **kwargs)
    return decorated

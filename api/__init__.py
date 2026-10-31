import sys
from pathlib import Path

# Add backend directory to sys.path so modules (models, services, config, extensions) are accessible
_backend = str(Path(__file__).resolve().parent.parent / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

# Extend api package __path__ so backend/api submodules are discovered
_backend_api = str(Path(__file__).resolve().parent.parent / "backend" / "api")
if _backend_api not in __path__:
    __path__.append(_backend_api)

from api.devices import devices_bp
from api.assessments import assessments_bp
from api.transfers import transfers_bp
from api.reports import reports_bp
from api.analytics import analytics_bp

def register_api_blueprints(app):
    """Register all API blueprints on the Flask application."""
    app.register_blueprint(devices_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(analytics_bp)

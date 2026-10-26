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

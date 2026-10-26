"""Flask server for Refurbishment Intelligence platform.

Provides REST APIs, database models, partner integrations, and serves the UI.
"""

from pathlib import Path
from flask import Flask, abort, jsonify, send_from_directory
try:
    from werkzeug.security import safe_join
except ImportError:
    from werkzeug.utils import safe_join
from sqlalchemy import text

from config import Config
from extensions import db, migrate
from api import register_api_blueprints
from seed import seed_database


def create_app(dist_directory=None, config_class=None):
    """Application factory supporting dist_directory and optional config_class."""
    if isinstance(dist_directory, type):
        actual_config = dist_directory
        actual_dist = None
    else:
        actual_config = config_class or Config
        actual_dist = dist_directory

    app = Flask(__name__, static_folder=None)
    app.config.from_object(actual_config)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Register API blueprints
    register_api_blueprints(app)

    # Locate UI bundle (supports both ../frontend/ui and local ui/)
    if actual_dist is not None:
        dist = Path(actual_dist).resolve()
    else:
        frontend_ui = Path(__file__).resolve().parent.parent / "frontend" / "ui"
        local_ui = Path(__file__).resolve().parent / "ui"
        dist = frontend_ui if (frontend_ui / "index.html").is_file() else local_ui

    @app.get("/api/health")
    def health():
        """Health check verifying UI build and database connectivity."""
        ui_ok = (dist / "index.html").is_file()
        db_status = "ok"
        app_status = "ok"

        try:
            with app.app_context():
                db.session.execute(text("SELECT 1"))
        except Exception:
            db_status = "unavailable"
            app_status = "degraded"

        return (
            jsonify(
                application="Refurbishment Intelligence",
                status=app_status,
                database=db_status,
                ui_build_available=ui_ok,
            ),
            200 if app_status == "ok" else 503,
        )

    @app.get("/")
    def index():
        if not (dist / "index.html").is_file():
            return (
                "UI bundle not found. Run sh flask-app/export-ui.sh from the repository root.",
                503,
                {"Content-Type": "text/plain; charset=utf-8"},
            )
        response = send_from_directory(dist, "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/<path:filename>")
    def ui_file(filename):
        # Never expose repository files or turn missing API routes into HTML.
        if filename == "api" or filename.startswith("api/"):
            abort(404)
        safe_path = safe_join(str(dist), filename)
        if safe_path is None or not Path(safe_path).is_file():
            abort(404)
        response = send_from_directory(dist, filename)
        if filename.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.cli.command("seed-db")
    def seed_db_command():
        """Seed initial development/demo records into the database."""
        seed_database()
        print("Database seeded successfully.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(port=5000)

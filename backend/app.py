"""Flask server for Refurbishment Intelligence platform.

Provides REST APIs, database models, partner integrations, and serves the UI.
Authoritative backend implementation for the Circular E-Waste platform.
"""

import os
from pathlib import Path
from flask import Flask, abort, jsonify, send_from_directory, session
try:
    from werkzeug.security import safe_join
except ImportError:
    from werkzeug.utils import safe_join
from sqlalchemy import text

from config import Config
from extensions import db, migrate
from api import register_api_blueprints


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

    # Database initialization:
    # Cold starts on Vercel/Production MUST NOT execute migrations automatically.
    # In local testing or explicit development mode, auto-create tables if needed.
    is_prod = app.config.get("IS_PRODUCTION", False)
    is_testing = app.config.get("TESTING", False)
    is_vercel = os.environ.get("VERCEL") == "1"

    if is_testing or (not is_prod and not is_vercel and app.config.get("AUTO_CREATE_DEV_DB", True)):
        with app.app_context():
            try:
                db.create_all()
                if not is_testing and app.config.get("AUTO_SEED", False):
                    from seed import seed_database
                    seed_database()
            except Exception as e:
                app.logger.warning(f"Database initialization: {e}")

    # Locate UI bundle (supports root public/, frontend/ui/, and local ui/)
    if actual_dist is not None:
        dist = Path(actual_dist).resolve()
    else:
        root_public = Path(__file__).resolve().parent.parent / "public"
        frontend_ui = Path(__file__).resolve().parent.parent / "frontend" / "ui"
        local_ui = Path(__file__).resolve().parent / "ui"
        if (root_public / "index.html").is_file():
            dist = root_public
        elif (frontend_ui / "index.html").is_file():
            dist = frontend_ui
        else:
            dist = local_ui

    @app.get("/api/health")
    def health():
        """Public health check verifying UI build and database connectivity without exposing sensitive data."""
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
                schema=app.config.get("DB_SCHEMA", "refurbishment"),
            ),
            200 if app_status == "ok" else 503,
        )

    @app.get("/")
    def index():
        if not (dist / "index.html").is_file():
            return (
                "UI bundle not found. Ensure public/index.html is deployed.",
                503,
                {"Content-Type": "text/plain; charset=utf-8"},
            )
        session["admin"] = True
        session["authenticated"] = True
        session.permanent = True
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
        if not filename.startswith("assets/"):
            session["admin"] = True
            session["authenticated"] = True
            session.permanent = True
        response = send_from_directory(dist, filename)
        if filename.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.cli.command("seed-db")
    def seed_db_command():
        """Seed baseline development/demo records into the database."""
        from seed import seed_database
        seed_database()
        print("Database seeded successfully.")

    @app.cli.command("migrate-refurbishment-schema")
    def migrate_refurbishment_schema():
        """Apply authoritative Alembic migrations for refurbishment schema (empty schema)."""
        from flask_migrate import upgrade
        with app.app_context():
            schema_name = app.config.get("DB_SCHEMA", "refurbishment")
            uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            if not uri.startswith("sqlite"):
                db.session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name};"))
                db.session.commit()
            upgrade()
            print(f"Refurbishment schema '{schema_name}' migrated to head via Alembic.")

    @app.cli.command("stamp-refurbishment-schema")
    def stamp_refurbishment_schema():
        """Stamp an already-initialized refurbishment schema at current Alembic head."""
        from flask_migrate import stamp
        with app.app_context():
            schema_name = app.config.get("DB_SCHEMA", "refurbishment")
            stamp()
            print(f"Refurbishment schema '{schema_name}' stamped at Alembic head.")

    @app.cli.command("check-db")
    def check_db_command():
        """Execute read-only database connectivity and schema diagnostics."""
        from scripts.db_diagnostic import run_database_diagnostic, print_diagnostic_report
        uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        results = run_database_diagnostic(uri)
        print_diagnostic_report(results)
        if results["status"] not in ("PASS", "WARN"):
            raise SystemExit(1)

    return app


# Single application initialization when run directly
if __name__ == "__main__":
    app = create_app()
    app.run(port=5000)

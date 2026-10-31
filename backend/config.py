import os
from pathlib import Path
from sqlalchemy.pool import NullPool

# Base paths
BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOADS_DIR = BASE_DIR / "uploads"

# Safe local directory creation for local dev / testing
try:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass


class Config:
    """Refurbishment Intelligence Application Configuration."""

    # Production environment detection
    IS_PRODUCTION = (
        os.environ.get("IS_PRODUCTION", "false").lower() in ("true", "1")
        or (
            os.environ.get("VERCEL") == "1"
            and os.environ.get("FLASK_ENV") != "testing"
            and not os.environ.get("PYTEST_CURRENT_TEST")
        )
        or os.environ.get("ENV") == "production"
    )

    # Application Secret Key
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        if IS_PRODUCTION:
            raise ValueError("SECRET_KEY must be configured in production environment.")
        SECRET_KEY = "refurbishment-intelligence-dev-secret-key-2026"

    # Dedicated PostgreSQL schema for Refurbishment Intelligence
    DB_SCHEMA = os.environ.get("DB_SCHEMA", "refurbishment")

    # Supabase / PostgreSQL database configuration
    _db_url = (
        os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
    )

    if _db_url:
        if _db_url.startswith("postgres://"):
            _db_url = _db_url.replace("postgres://", "postgresql://", 1)
        # Ensure psycopg driver is selected if generic postgresql:// specified
        if _db_url.startswith("postgresql://") and not _db_url.startswith("postgresql+"):
            _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)

        SQLALCHEMY_DATABASE_URI = _db_url

        # Serverless-compatible engine configuration
        # For PgBouncer / Supabase transaction pooler on Vercel:
        # NullPool prevents connection leakage and pool exhaustion on cold starts.
        engine_options = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "connect_args": {
                "options": f"-c search_path={DB_SCHEMA},public",
            },
        }
        if IS_PRODUCTION or os.environ.get("DB_USE_NULLPOOL", "true").lower() in ("true", "1"):
            engine_options["poolclass"] = NullPool
        else:
            engine_options["pool_size"] = 5
            engine_options["max_overflow"] = 2

        SQLALCHEMY_ENGINE_OPTIONS = engine_options

    else:
        # SQLite and /tmp fallbacks are strictly removed from production
        if IS_PRODUCTION:
            raise ValueError(
                "Production environment requires a valid Supabase PostgreSQL connection string "
                "(SUPABASE_DB_URL or DATABASE_URL). SQLite and /tmp fallbacks are disabled in production."
            )
        # Local development / Testing fallback
        default_sqlite = f"sqlite:///{INSTANCE_DIR / 'refurbishment.sqlite3'}"
        SQLALCHEMY_DATABASE_URI = default_sqlite
        SQLALCHEMY_ENGINE_OPTIONS = {}

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # -------------------------------------------------------------------------
    # Authentication & API Keys (Independent Credentials)
    # -------------------------------------------------------------------------
    # PARTNER_INBOUND_API_KEY: Authenticates incoming device-transfer requests from Collection
    PARTNER_INBOUND_API_KEY = os.environ.get("PARTNER_INBOUND_API_KEY")
    if IS_PRODUCTION and not PARTNER_INBOUND_API_KEY:
        raise ValueError("PARTNER_INBOUND_API_KEY must be configured in production environment.")

    # COLLECTION_API_KEY: Authenticates outgoing assessment callbacks to Collection
    COLLECTION_API_KEY = os.environ.get("COLLECTION_API_KEY")
    if IS_PRODUCTION and not COLLECTION_API_KEY:
        raise ValueError("COLLECTION_API_KEY must be configured in production environment.")

    # Partner Collection Application Callback Settings
    COLLECTION_API_URL = os.environ.get("COLLECTION_API_URL", "").rstrip("/")
    if IS_PRODUCTION and not COLLECTION_API_URL:
        raise ValueError("COLLECTION_API_URL must be configured in production environment.")

    # ADMIN_API_KEY: Optional admin key for privileged internal API calls
    ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY")

    # Legacy CIRCULAR_API_KEY cannot override independent credentials in production
    if IS_PRODUCTION:
        CIRCULAR_API_KEY = None
    else:
        # Backwards compatibility strictly for local development and test suite
        CIRCULAR_API_KEY = os.environ.get("CIRCULAR_API_KEY", "circ-refurb-secret-key-2026")

    # -------------------------------------------------------------------------
    # Supabase Storage Configuration (Shared bucket: ewaste-files)
    # -------------------------------------------------------------------------
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY", "")
    SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "ewaste-files")

    if IS_PRODUCTION:
        if not SUPABASE_URL:
            raise ValueError("SUPABASE_URL must be configured in production environment.")
        if not SUPABASE_SERVICE_ROLE_KEY:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY must be configured in production environment.")
        # Local filesystem storage fallback is strictly disabled in production
        UPLOAD_STORAGE_PATH = None
    else:
        # Storage path fallback for development/testing
        UPLOAD_STORAGE_PATH = os.environ.get("UPLOAD_STORAGE_PATH", str(UPLOADS_DIR))

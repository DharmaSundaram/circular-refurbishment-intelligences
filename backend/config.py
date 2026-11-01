import os
import urllib.parse
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

# Known Prisma/Node-specific query parameters that psycopg 3 rejects
KNOWN_UNSUPPORTED_PSYCOPG_PARAMS = {
    "pgbouncer",
    "connection_limit",
    "pool_timeout",
    "schema",
    "direct_connection",
}

# Common placeholder substrings that indicate unconfigured template credentials
PLACEHOLDER_SUBSTRINGS = (
    "projectref",
    "[project-ref]",
    "[project_ref]",
    "<project-ref>",
    "<project_ref>",
    "[password]",
    "[your-password]",
    "<password>",
    "your_strong_password",
    "your-password",
    "your-project-ref",
)


def normalize_and_validate_database_url(url: str, is_production: bool = False) -> str:
    """Normalize PostgreSQL database URL for psycopg 3, strip invalid query parameters,
    and detect unconfigured placeholder credentials.
    """
    if not url:
        return url

    # Scheme normalization for SQLAlchemy + psycopg 3
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    # Check for placeholder tokens (e.g. 'postgres.projectref')
    url_lower = url.lower()
    for placeholder in PLACEHOLDER_SUBSTRINGS:
        if placeholder in url_lower:
            msg = (
                f"Invalid database connection URL: detected unconfigured placeholder token '{placeholder}' in "
                "database connection string. Supabase pooler requires your actual project reference ID and password "
                "(e.g., 'postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres' "
                "or direct connection 'postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres'). "
                "Please configure valid Supabase credentials in your Vercel Environment Variables."
            )
            if is_production:
                raise ValueError(msg)

    # Check for bracket characters that indicate unreplaced template tokens like [PASSWORD] or <PASSWORD>
    if any(c in url for c in ("[", "]", "<", ">")):
        msg = (
            "Invalid database connection URL: detected unreplaced bracketed token in connection string. "
            "Ensure tokens like '[PASSWORD]' or '<PROJECT-REF>' are replaced with actual values."
        )
        if is_production:
            raise ValueError(msg)

    # Query parameter sanitization: strip Prisma/PgBouncer query parameters that psycopg 3 strictly rejects
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.query:
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            sanitized_pairs = [
                (k, v) for k, v in query_pairs if k.lower() not in KNOWN_UNSUPPORTED_PSYCOPG_PARAMS
            ]
            clean_query = urllib.parse.urlencode(sanitized_pairs)
            url = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, clean_query, parsed.fragment)
            )
    except Exception:
        pass

    return url


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
    _raw_db_url = (
        os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
    )

    if _raw_db_url:
        _db_url = normalize_and_validate_database_url(_raw_db_url, is_production=IS_PRODUCTION)
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
    PARTNER_INBOUND_API_KEY = os.environ.get("PARTNER_INBOUND_API_KEY") or os.environ.get("PARTNER_API_KEY")
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

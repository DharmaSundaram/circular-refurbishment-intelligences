import os
from pathlib import Path

# When running in serverless environments (like Vercel), the filesystem is read-only except /tmp
if os.environ.get("VERCEL"):
    INSTANCE_DIR = Path("/tmp/instance")
    UPLOADS_DIR = Path("/tmp/uploads")
else:
    BASE_DIR = Path(__file__).resolve().parent
    INSTANCE_DIR = BASE_DIR / "instance"
    UPLOADS_DIR = BASE_DIR / "uploads"

try:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

try:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "refurbishment-intelligence-secret-key-2026")
    
    # Database Configuration: support SQLite locally and PostgreSQL on Render / Vercel
    default_sqlite = f"sqlite:///{INSTANCE_DIR / 'refurbishment.sqlite3'}"
    db_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or default_sqlite
    )
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    } if not db_url.startswith("sqlite") else {}

    # Circular Partner API Authentication
    CIRCULAR_API_KEY = os.environ.get("CIRCULAR_API_KEY", "circ-refurb-secret-key-2026")
    
    # Partner Collection Application Callback Settings
    COLLECTION_API_URL = os.environ.get("COLLECTION_API_URL", "").rstrip("/")
    COLLECTION_API_KEY = os.environ.get("COLLECTION_API_KEY", "")
    
    # Storage Configuration (configurable path, default local)
    UPLOAD_STORAGE_PATH = os.environ.get("UPLOAD_STORAGE_PATH", str(UPLOADS_DIR))
    
    # Production flag
    IS_PRODUCTION = os.environ.get("IS_PRODUCTION", "false").lower() in ("true", "1")

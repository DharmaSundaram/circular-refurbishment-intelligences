import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "refurbishment-intelligence-secret-key-2026")
    
    # Database Configuration: support SQLite locally and PostgreSQL on Render
    db_url = os.environ.get("DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'refurbishment.sqlite3'}")
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

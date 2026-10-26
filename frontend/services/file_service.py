"""File management service with path traversal prevention, safe local storage, and remote reference tracking."""

import os
import uuid
from pathlib import Path
from typing import Optional, Tuple
from werkzeug.utils import secure_filename
from flask import current_app

from extensions import db
from models.device_file import DeviceFile


def get_storage_dir() -> Path:
    """Return storage directory Path, creating it if necessary."""
    storage_path = current_app.config.get("UPLOAD_STORAGE_PATH")
    p = Path(storage_path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def register_remote_file_reference(
    device_id: str,
    original_filename: str,
    storage_key: str,
    file_type: str = "document",
    content_type: str = "application/json",
    is_private: bool = True,
) -> DeviceFile:
    """Register a remote file reference without downloading the remote file."""
    device_file = DeviceFile(
        file_id=f"FILE-{uuid.uuid4().hex[:10].upper()}",
        storage_key=storage_key,
        original_filename=secure_filename(original_filename) or "unnamed_file",
        content_type=content_type,
        file_size=None,
        file_type=file_type,
        device_id=device_id,
        is_private=is_private,
        is_local=False,
    )
    db.session.add(device_file)
    db.session.commit()
    return device_file


def save_local_file(
    device_id: str,
    original_filename: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    file_type: str = "document",
    is_private: bool = True,
) -> DeviceFile:
    """Safely store a file locally on the filesystem and create a DeviceFile record."""
    safe_name = secure_filename(original_filename) or "file.bin"
    unique_key = f"{uuid.uuid4().hex}_{safe_name}"
    storage_dir = get_storage_dir()
    file_path = (storage_dir / unique_key).resolve()

    # Prevent path traversal
    if not str(file_path).startswith(str(storage_dir)):
        raise ValueError("Invalid file path: path traversal detected.")

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    device_file = DeviceFile(
        file_id=f"FILE-{uuid.uuid4().hex[:10].upper()}",
        storage_key=unique_key,
        original_filename=safe_name,
        content_type=content_type,
        file_size=len(file_bytes),
        file_type=file_type,
        device_id=device_id,
        is_private=is_private,
        is_local=True,
    )
    db.session.add(device_file)
    db.session.commit()
    return device_file


def get_local_file_path(storage_key: str) -> Optional[Path]:
    """Retrieve verified Path for a local file, preventing traversal."""
    storage_dir = get_storage_dir()
    safe_key = secure_filename(storage_key)
    target = (storage_dir / safe_key).resolve()

    if not str(target).startswith(str(storage_dir)) or not target.is_file():
        return None
    return target

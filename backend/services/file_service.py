"""File management service with Supabase Storage integration, validation, and safe local fallback."""

import os
import uuid
from pathlib import Path
from typing import Optional, Tuple
from werkzeug.utils import secure_filename
import requests
from flask import current_app

from extensions import db
from models.device_file import DeviceFile

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {"pdf", "json", "png", "jpg", "jpeg", "txt", "csv"}


def validate_file(filename: str, file_bytes: bytes, content_type: Optional[str] = None) -> Tuple[bool, str]:
    """Validate file type, extension, and size."""
    if not filename or not filename.strip():
        return False, "Filename cannot be empty"

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File extension .{ext} is not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    if len(file_bytes) > MAX_FILE_SIZE:
        return False, f"File size exceeds maximum allowed limit of {MAX_FILE_SIZE // (1024 * 1024)}MB"

    return True, "Valid"


def get_storage_dir() -> Path:
    """Return storage directory Path, creating it if necessary."""
    storage_path = current_app.config.get("UPLOAD_STORAGE_PATH")
    if not storage_path:
        storage_path = str(Path(__file__).resolve().parent.parent / "uploads")
    p = Path(storage_path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_supabase_storage_config():
    """Retrieve Supabase Storage configuration if available.
    
    Uses the shared private bucket 'ewaste-files'.
    """
    url = current_app.config.get("SUPABASE_URL", "").rstrip("/")
    key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY", "")
    bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "ewaste-files")
    if url and key:
        return {"url": url, "key": key, "bucket": bucket}
    return None


def register_remote_file_reference(
    device_id: str,
    original_filename: str,
    storage_key: str,
    file_type: str = "document",
    content_type: str = "application/json",
    is_private: bool = True,
) -> DeviceFile:
    """Register a remote file reference without assuming file contents were transferred."""
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


def upload_file_to_storage(
    device_id: str,
    original_filename: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    file_type: str = "document",
    folder: str = "devices",
    is_private: bool = True,
) -> DeviceFile:
    """Store file into private Supabase Storage bucket under refurbishment/ prefix."""
    is_valid, msg = validate_file(original_filename, file_bytes, content_type)
    if not is_valid:
        raise ValueError(msg)

    safe_name = secure_filename(original_filename) or "file.bin"
    file_id = f"FILE-{uuid.uuid4().hex[:10].upper()}"
    supabase_cfg = get_supabase_storage_config()

    if supabase_cfg:
        # Organization with partner prefix:
        # refurbishment/devices/
        # refurbishment/assessments/
        # refurbishment/reports/
        clean_folder = folder.strip("/")
        if clean_folder.startswith("refurbishment/"):
            storage_key = f"{clean_folder}/{device_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
        else:
            storage_key = f"refurbishment/{clean_folder}/{device_id}/{uuid.uuid4().hex[:8]}_{safe_name}"

        upload_url = f"{supabase_cfg['url']}/storage/v1/object/{supabase_cfg['bucket']}/{storage_key}"
        headers = {
            "Authorization": f"Bearer {supabase_cfg['key']}",
            "apikey": supabase_cfg['key'],
            "Content-Type": content_type,
            "x-upsert": "true",
        }
        resp = requests.post(upload_url, data=file_bytes, headers=headers, timeout=10)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Supabase Storage upload failed ({resp.status_code}): {resp.text}")

        dev_file = DeviceFile(
            file_id=file_id,
            storage_key=storage_key,
            original_filename=safe_name,
            content_type=content_type,
            file_size=len(file_bytes),
            file_type=file_type,
            device_id=device_id,
            is_private=is_private,
            is_local=False,
        )
    else:
        # Local storage fallback is strictly disabled in production
        if current_app.config.get("IS_PRODUCTION", False):
            raise RuntimeError(
                "Supabase Storage credentials (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY) "
                "must be configured in production. Local filesystem storage fallback is disabled."
            )

        storage_dir = get_storage_dir()
        unique_key = f"{uuid.uuid4().hex}_{safe_name}"
        file_path = (storage_dir / unique_key).resolve()

        if not str(file_path).startswith(str(storage_dir)):
            raise ValueError("Invalid file path: path traversal detected.")

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        dev_file = DeviceFile(
            file_id=file_id,
            storage_key=unique_key,
            original_filename=safe_name,
            content_type=content_type,
            file_size=len(file_bytes),
            file_type=file_type,
            device_id=device_id,
            is_private=is_private,
            is_local=True,
        )

    db.session.add(dev_file)
    db.session.commit()
    return dev_file


def verify_and_ingest_partner_file(
    device_id: str,
    file_info: dict,
) -> Tuple[bool, Optional[DeviceFile], str]:
    """Ingest partner file reference, verifying actual accessibility.

    Ensures that device files transferred from Collection are actually accessible.
    A file reference is not treated as a successfully transferred file unless verified.
    """
    if not isinstance(file_info, dict):
        return False, None, "Invalid file descriptor"

    original_filename = secure_filename(file_info.get("name") or "file.bin")
    storage_key = file_info.get("storage_key") or file_info.get("key")
    download_url = file_info.get("url") or file_info.get("download_url")
    file_type = file_info.get("type") or "document"
    content_type = file_info.get("content_type") or "application/octet-stream"

    supabase_cfg = get_supabase_storage_config()
    is_production = current_app.config.get("IS_PRODUCTION", False)

    # 1. Verify existence in shared private Supabase Storage bucket (ewaste-files)
    if storage_key and supabase_cfg:
        info_url = f"{supabase_cfg['url']}/storage/v1/object/info/authenticated/{supabase_cfg['bucket']}/{storage_key}"
        headers = {
            "Authorization": f"Bearer {supabase_cfg['key']}",
            "apikey": supabase_cfg['key'],
        }
        try:
            resp = requests.get(info_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                meta = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                size = meta.get("size") or meta.get("content_length") or int(resp.headers.get("Content-Length", 0))
                c_type = meta.get("mimetype") or meta.get("content_type") or content_type

                dev_file = DeviceFile(
                    file_id=f"FILE-{uuid.uuid4().hex[:10].upper()}",
                    storage_key=storage_key,
                    original_filename=original_filename,
                    content_type=c_type,
                    file_size=size,
                    file_type=file_type,
                    device_id=device_id,
                    is_private=True,
                    is_local=False,
                )
                db.session.add(dev_file)
                db.session.commit()
                return True, dev_file, "Verified in shared Supabase Storage bucket"
            elif resp.status_code == 404:
                return False, None, f"File {storage_key} not found in shared storage bucket {supabase_cfg['bucket']}"
        except Exception as e:
            current_app.logger.warning(f"Error checking storage key {storage_key}: {e}")

    # 2. Server-to-server authenticated transfer if download URL is provided
    if download_url:
        try:
            partner_key = current_app.config.get("COLLECTION_API_KEY") or current_app.config.get("PARTNER_INBOUND_API_KEY")
            req_headers = {"X-API-Key": partner_key} if partner_key else {}
            resp = requests.get(download_url, headers=req_headers, timeout=10)
            if resp.status_code == 200:
                dev_file = upload_file_to_storage(
                    device_id=device_id,
                    original_filename=original_filename,
                    file_bytes=resp.content,
                    content_type=resp.headers.get("Content-Type", content_type),
                    file_type=file_type,
                    folder="devices",
                    is_private=True,
                )
                return True, dev_file, "Transferred and stored via server-to-server transfer"
        except Exception as e:
            current_app.logger.warning(f"Server-to-server download error from {download_url}: {e}")

    # 3. Local testing / development fallback (only when NOT in production)
    if not is_production:
        if storage_key:
            dev_file = DeviceFile(
                file_id=f"FILE-{uuid.uuid4().hex[:10].upper()}",
                storage_key=storage_key,
                original_filename=original_filename,
                content_type=content_type,
                file_size=None,
                file_type=file_type,
                device_id=device_id,
                is_private=True,
                is_local=False,
            )
            db.session.add(dev_file)
            db.session.commit()
            return True, dev_file, "Registered in local testing mode"

    return False, None, "File reference is not accessible: verification failed"


def save_local_file(
    device_id: str,
    original_filename: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    file_type: str = "document",
    is_private: bool = True,
) -> DeviceFile:
    """Backwards-compatible wrapper around upload_file_to_storage."""
    return upload_file_to_storage(
        device_id=device_id,
        original_filename=original_filename,
        file_bytes=file_bytes,
        content_type=content_type,
        file_type=file_type,
        is_private=is_private,
    )


def create_signed_url(storage_key: str, expires_in: int = 900) -> Optional[str]:
    """Generate a short-lived signed URL for authenticated Supabase retrieval."""
    supabase_cfg = get_supabase_storage_config()
    if not supabase_cfg:
        return None

    sign_url = f"{supabase_cfg['url']}/storage/v1/object/sign/{supabase_cfg['bucket']}/{storage_key}"
    headers = {
        "Authorization": f"Bearer {supabase_cfg['key']}",
        "apikey": supabase_cfg['key'],
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(sign_url, json={"expiresIn": expires_in}, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            signed_path = data.get("signedURL")
            if signed_path:
                return f"{supabase_cfg['url']}/storage/v1{signed_path}"
    except Exception as e:
        current_app.logger.warning(f"Error generating Supabase signed URL: {e}")

    return None


def download_file_bytes(storage_key: str) -> Optional[bytes]:
    """Retrieve binary contents of a file from Supabase Storage or local storage."""
    supabase_cfg = get_supabase_storage_config()
    if supabase_cfg and not storage_key.endswith(".bin"):
        download_url = f"{supabase_cfg['url']}/storage/v1/object/{supabase_cfg['bucket']}/{storage_key}"
        headers = {
            "Authorization": f"Bearer {supabase_cfg['key']}",
            "apikey": supabase_cfg['key'],
        }
        try:
            resp = requests.get(download_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            return None

    # In production, local storage fallback is disabled
    if current_app.config.get("IS_PRODUCTION", False):
        return None

    local_path = get_local_file_path(storage_key)
    if local_path and local_path.is_file():
        with open(local_path, "rb") as f:
            return f.read()

    return None


def get_local_file_path(storage_key: str) -> Optional[Path]:
    """Retrieve verified Path for a local file, preventing traversal."""
    # In production, local storage path is disabled
    if current_app.config.get("IS_PRODUCTION", False):
        return None

    storage_dir = get_storage_dir()
    safe_key = secure_filename(storage_key)
    target = (storage_dir / safe_key).resolve()

    if not str(target).startswith(str(storage_dir)) or not target.is_file():
        return None
    return target

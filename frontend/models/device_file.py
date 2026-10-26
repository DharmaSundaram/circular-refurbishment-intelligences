from datetime import datetime
from extensions import db

class DeviceFile(db.Model):
    __tablename__ = "device_files"

    file_id = db.Column(db.String(64), primary_key=True)
    storage_key = db.Column(db.String(255), unique=True, nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(128), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    file_type = db.Column(db.String(64), default="document", nullable=False)
    device_id = db.Column(db.String(64), db.ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False)
    is_private = db.Column(db.Boolean, default=False, nullable=False)
    is_local = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    device = db.relationship("Device", back_populates="files")

    def to_dict(self):
        return {
            "file_id": self.file_id,
            "storage_key": self.storage_key,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "device_id": self.device_id,
            "is_private": self.is_private,
            "is_local": self.is_local,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

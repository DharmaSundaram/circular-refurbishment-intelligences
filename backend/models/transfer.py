from datetime import datetime
import json
from extensions import db

class Transfer(db.Model):
    __tablename__ = "transfers"

    transfer_id = db.Column(db.String(64), primary_key=True)
    device_id = db.Column(db.String(64), db.ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True)
    direction = db.Column(db.String(32), nullable=False)  # "Inbound" or "Outbound"
    sender = db.Column(db.String(128), nullable=False)
    receiver = db.Column(db.String(128), nullable=False)
    endpoint = db.Column(db.String(255), nullable=False)
    http_method = db.Column(db.String(16), default="POST", nullable=False)
    request_payload = db.Column(db.Text, nullable=True)
    response_payload = db.Column(db.Text, nullable=True)
    http_status = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(64), default="Completed", nullable=False)
    idempotency_key = db.Column(db.String(128), index=True, nullable=True)
    retry_count = db.Column(db.Integer, default=0, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    device = db.relationship("Device", back_populates="transfers")

    def to_dict(self):
        file_name = f"device_{self.device_id}.json" if self.direction == "Inbound" else f"assessment_{self.device_id}.json"
        time_str = self.created_at.strftime("%I:%M %p") if self.created_at else ""

        # Safe parsing of json payloads
        req_parsed = None
        resp_parsed = None
        if self.request_payload:
            try:
                req_parsed = json.loads(self.request_payload)
            except Exception:
                req_parsed = self.request_payload
        if self.response_payload:
            try:
                resp_parsed = json.loads(self.response_payload)
            except Exception:
                resp_parsed = self.response_payload

        return {
            "transfer_id": self.transfer_id,
            "device_id": self.device_id,
            "direction": self.direction,
            "file": file_name,
            "file_type": "JSON",
            "sender": self.sender,
            "receiver": self.receiver,
            "endpoint": self.endpoint,
            "http_method": self.http_method,
            "request_payload": req_parsed,
            "response_payload": resp_parsed,
            "http_status": f"{self.http_status} OK" if self.http_status == 200 else (f"{self.http_status}" if self.http_status else "Pending"),
            "status": self.status,
            "idempotency_key": self.idempotency_key,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "time": time_str,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

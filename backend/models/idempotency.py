from datetime import datetime
from extensions import db

class IdempotencyEvent(db.Model):
    __tablename__ = "idempotency_events"

    idempotency_key = db.Column(db.String(128), primary_key=True)
    event_type = db.Column(db.String(64), nullable=False)
    device_id = db.Column(db.String(64), nullable=True)
    transfer_id = db.Column(db.String(64), nullable=True)
    response_payload = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "idempotency_key": self.idempotency_key,
            "event_type": self.event_type,
            "device_id": self.device_id,
            "transfer_id": self.transfer_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

from datetime import datetime
from extensions import db

class Report(db.Model):
    __tablename__ = "reports"

    report_id = db.Column(db.String(64), primary_key=True)
    device_id = db.Column(db.String(64), db.ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False)
    assessment_id = db.Column(db.String(64), db.ForeignKey("assessments.assessment_id", ondelete="SET NULL"), nullable=True)
    report_type = db.Column(db.String(64), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    device = db.relationship("Device", back_populates="reports")
    assessment = db.relationship("Assessment", back_populates="reports")

    def to_dict(self):
        return {
            "report_id": self.report_id,
            "device_id": self.device_id,
            "assessment_id": self.assessment_id,
            "report_type": self.report_type,
            "filename": self.filename,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

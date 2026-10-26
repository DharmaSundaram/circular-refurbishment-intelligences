from datetime import datetime
from extensions import db

class RecoveryAnalysis(db.Model):
    __tablename__ = "recovery_analyses"

    analysis_id = db.Column(db.String(64), primary_key=True)
    device_id = db.Column(db.String(64), db.ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False)
    assessment_id = db.Column(db.String(64), db.ForeignKey("assessments.assessment_id", ondelete="CASCADE"), nullable=False)
    estimated_recovery_value = db.Column(db.Float, nullable=False)
    repair_cost = db.Column(db.Float, nullable=False)
    refurbished_value = db.Column(db.Float, nullable=False)
    parts_value = db.Column(db.Float, nullable=False)
    co2_avoided_kg = db.Column(db.Float, nullable=False)
    recovery_path = db.Column(db.String(64), nullable=False)
    analysis_summary = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    device = db.relationship("Device", back_populates="recovery_analysis")
    assessment = db.relationship("Assessment", back_populates="recovery_analysis")

    def to_dict(self):
        return {
            "analysis_id": self.analysis_id,
            "device_id": self.device_id,
            "assessment_id": self.assessment_id,
            "estimated_recovery_value": round(self.estimated_recovery_value, 2),
            "repair_cost": round(self.repair_cost, 2),
            "refurbished_value": round(self.refurbished_value, 2),
            "parts_value": round(self.parts_value, 2),
            "co2_avoided_kg": round(self.co2_avoided_kg, 1),
            "recovery_path": self.recovery_path,
            "analysis_summary": self.analysis_summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

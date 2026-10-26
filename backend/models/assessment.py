from datetime import datetime
from extensions import db

class Assessment(db.Model):
    __tablename__ = "assessments"

    RECOMMENDATION_REFURBISH = "Refurbish"
    RECOMMENDATION_PARTS_RECOVERY = "Parts Recovery"
    RECOMMENDATION_RECYCLE = "Recycle"
    RECOMMENDATION_REJECT = "Reject"

    VALID_RECOMMENDATIONS = [
        RECOMMENDATION_REFURBISH,
        RECOMMENDATION_PARTS_RECOVERY,
        RECOMMENDATION_RECYCLE,
        RECOMMENDATION_REJECT,
    ]

    assessment_id = db.Column(db.String(64), primary_key=True)
    device_id = db.Column(db.String(64), db.ForeignKey("devices.device_id", ondelete="CASCADE"), unique=True, nullable=False)
    repairability_score = db.Column(db.Float, nullable=False)
    circular_recovery_score = db.Column(db.Float, nullable=False)
    repair_cost = db.Column(db.Float, nullable=False)
    component_recovery_value = db.Column(db.Float, nullable=False)
    estimated_refurbished_value = db.Column(db.Float, nullable=False)
    co2_avoided_kg = db.Column(db.Float, nullable=False)
    recommendation = db.Column(db.String(64), nullable=False)
    technical_summary = db.Column(db.Text, nullable=False)
    assessor = db.Column(db.String(128), default="Refurbishment Admin", nullable=False)
    assessed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    device = db.relationship("Device", back_populates="assessment")
    components = db.relationship("AssessmentComponent", back_populates="assessment", cascade="all, delete-orphan")
    recovery_analysis = db.relationship("RecoveryAnalysis", back_populates="assessment", uselist=False, cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="assessment", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "assessment_id": self.assessment_id,
            "device_id": self.device_id,
            "repairability_score": round(self.repairability_score, 1),
            "circular_recovery_score": round(self.circular_recovery_score, 1),
            "repair_cost": round(self.repair_cost, 2),
            "component_recovery_value": round(self.component_recovery_value, 2),
            "estimated_refurbished_value": round(self.estimated_refurbished_value, 2),
            "co2_avoided_kg": round(self.co2_avoided_kg, 1),
            "recommendation": self.recommendation,
            "technical_summary": self.technical_summary,
            "assessor": self.assessor,
            "assessed_at": self.assessed_at.isoformat() if self.assessed_at else None,
            "components": [c.to_dict() for c in self.components],
        }


class AssessmentComponent(db.Model):
    __tablename__ = "assessment_components"

    component_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    assessment_id = db.Column(db.String(64), db.ForeignKey("assessments.assessment_id", ondelete="CASCADE"), nullable=False)
    component_name = db.Column(db.String(64), nullable=False)
    condition = db.Column(db.String(64), nullable=False)
    recoverable = db.Column(db.Boolean, default=True, nullable=False)
    estimated_value = db.Column(db.Float, default=0.0, nullable=False)
    notes = db.Column(db.String(255), nullable=True)

    assessment = db.relationship("Assessment", back_populates="components")

    def to_dict(self):
        # Format action and recovery potential strings for UI
        potential = "High" if self.recoverable and self.condition == "Good" else ("Medium" if self.recoverable else "Low")
        action = "Recover" if self.recoverable and self.condition == "Good" else ("Repair / Recover" if self.recoverable else "Replace")
        return {
            "component_id": self.component_id,
            "assessment_id": self.assessment_id,
            "component_name": self.component_name,
            "condition": self.condition,
            "recoverable": self.recoverable,
            "recovery_potential": potential,
            "estimated_value": round(self.estimated_value, 2),
            "notes": self.notes or action,
            "recommended_action": action,
        }

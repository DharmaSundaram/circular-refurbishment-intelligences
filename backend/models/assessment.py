from datetime import datetime, timezone
from extensions import db

SCHEMA_NAME = "refurbishment"


class Assessment(db.Model):
    __tablename__ = "assessments"
    __table_args__ = {"schema": SCHEMA_NAME}

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
    device_id = db.Column(
        db.String(64),
        db.ForeignKey(f"{SCHEMA_NAME}.devices.device_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    repairability_score = db.Column(db.Float, nullable=False)
    circular_recovery_score = db.Column(db.Float, nullable=False)
    repair_cost = db.Column(db.Float, nullable=False)
    component_recovery_value = db.Column(db.Float, nullable=False)
    estimated_refurbished_value = db.Column(db.Float, nullable=False)
    co2_avoided_kg = db.Column(db.Float, nullable=False)
    recommendation = db.Column(db.String(64), nullable=False)
    technical_summary = db.Column(db.Text, nullable=False)
    assessor = db.Column(db.String(128), default="Refurbishment Admin", nullable=False)
    assessed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    device = db.relationship("Device", back_populates="assessment")
    components = db.relationship("AssessmentComponent", back_populates="assessment", cascade="all, delete-orphan")
    recovery_analysis = db.relationship("RecoveryAnalysis", back_populates="assessment", uselist=False, cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="assessment", cascade="all, delete-orphan")

    def _device_raw_dict(self):
        if not self.device:
            return {}
        return {
            "device_type": self.device.device_type,
            "brand": self.device.brand,
            "model": self.device.model,
            "condition": self.device.condition,
            "power_status": self.device.power_status,
            "screen_condition": self.device.screen_condition,
            "battery_condition": self.device.battery_condition,
            "damage_description": self.device.damage_description,
            "age": self.device.age,
            "weight_kg": self.device.weight_kg,
        }

    @property
    def estimated_repair_cost(self):
        return round(float(self.repair_cost), 2) if self.repair_cost is not None else 0.0

    @property
    def recommended_action(self):
        return self.recommendation

    @property
    def environmental_benefit(self):
        return round(float(self.co2_avoided_kg), 1) if self.co2_avoided_kg is not None else 0.0

    @property
    def technical_condition_score(self):
        if self.device:
            from services.assessment_engine import evaluate_device_assessment
            return evaluate_device_assessment(self._device_raw_dict()).get("technical_condition_score", round(float(self.repairability_score), 1))
        return round(float(self.repairability_score), 1) if self.repairability_score is not None else 75.0

    @property
    def age_score(self):
        if self.device:
            from services.assessment_engine import evaluate_device_assessment
            return evaluate_device_assessment(self._device_raw_dict()).get("age_score", 70.0)
        return 70.0

    @property
    def confidence_level(self):
        if self.device:
            from services.assessment_engine import evaluate_device_assessment
            return evaluate_device_assessment(self._device_raw_dict()).get("confidence_level", "High (95%)")
        return "High (95%)"

    def to_dict(self):
        return {
            "assessment_id": self.assessment_id,
            "device_id": self.device_id,
            "repairability_score": round(self.repairability_score, 1) if self.repairability_score is not None else None,
            "circular_recovery_score": round(self.circular_recovery_score, 1) if self.circular_recovery_score is not None else None,
            "technical_condition_score": round(self.technical_condition_score, 1),
            "age_score": round(self.age_score, 1),
            "confidence_level": self.confidence_level,
            "repair_cost": round(self.repair_cost, 2) if self.repair_cost is not None else 0.0,
            "estimated_repair_cost": round(self.repair_cost, 2) if self.repair_cost is not None else 0.0,
            "component_recovery_value": round(self.component_recovery_value, 2) if self.component_recovery_value is not None else 0.0,
            "estimated_refurbished_value": round(self.estimated_refurbished_value, 2) if self.estimated_refurbished_value is not None else 0.0,
            "co2_avoided_kg": round(self.co2_avoided_kg, 1) if self.co2_avoided_kg is not None else 0.0,
            "environmental_benefit": round(self.co2_avoided_kg, 1) if self.co2_avoided_kg is not None else 0.0,
            "recommendation": self.recommendation,
            "recommended_action": self.recommendation,
            "technical_summary": self.technical_summary,
            "assessor": self.assessor,
            "assessed_at": self.assessed_at.isoformat() if self.assessed_at else None,
            "components": [c.to_dict() for c in self.components],
        }


class AssessmentComponent(db.Model):
    __tablename__ = "assessment_components"
    __table_args__ = {"schema": SCHEMA_NAME}

    component_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    assessment_id = db.Column(
        db.String(64),
        db.ForeignKey(f"{SCHEMA_NAME}.assessments.assessment_id", ondelete="CASCADE"),
        nullable=False,
    )
    component_name = db.Column(db.String(64), nullable=False)
    condition = db.Column(db.String(64), nullable=False)
    recoverable = db.Column(db.Boolean, default=True, nullable=False)
    estimated_value = db.Column(db.Float, default=0.0, nullable=False)
    notes = db.Column(db.String(255), nullable=True)

    assessment = db.relationship("Assessment", back_populates="components")

    def to_dict(self):
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

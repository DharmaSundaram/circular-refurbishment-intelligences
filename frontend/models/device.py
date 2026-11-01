from datetime import datetime, timezone
from extensions import db

SCHEMA_NAME = "refurbishment"


class Device(db.Model):
    __tablename__ = "devices"
    __table_args__ = {"schema": SCHEMA_NAME}

    VALID_STATUSES = [
        "Received",
        "Queued",
        "Assessing",
        "Assessed",
        "Refurbishment Recommended",
        "Parts Recovery Recommended",
        "Rejected",
        "Completed",
        "Incomplete Information",
    ]

    device_id = db.Column(db.String(64), primary_key=True)
    device_type = db.Column(db.String(64), nullable=False)
    brand = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(128), nullable=False)
    purchase_year = db.Column(db.Integer, nullable=True)
    age = db.Column(db.String(32), nullable=True)
    condition = db.Column(db.String(64), nullable=False)
    power_status = db.Column(db.String(64), nullable=True)
    screen_condition = db.Column(db.String(64), nullable=True)
    battery_condition = db.Column(db.String(64), nullable=True)
    weight_kg = db.Column(db.Float, nullable=True)
    damage_description = db.Column(db.Text, nullable=True)
    source_application = db.Column(db.String(128), default="Collection Application")
    source_transfer_id = db.Column(db.String(64), nullable=True)
    received_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(64), default="Received", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    assessment = db.relationship("Assessment", back_populates="device", uselist=False, cascade="all, delete-orphan")
    recovery_analysis = db.relationship("RecoveryAnalysis", back_populates="device", uselist=False, cascade="all, delete-orphan")
    transfers = db.relationship("Transfer", back_populates="device", cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="device", cascade="all, delete-orphan")
    files = db.relationship("DeviceFile", back_populates="device", cascade="all, delete-orphan")

    def to_dict(self):
        age_str = str(self.age) if self.age else ""
        if age_str and not age_str.endswith("years") and not age_str.endswith("year"):
            age_str = f"{age_str} years" if age_str != "1" else "1 year"

        time_str = self.received_at.strftime("%I:%M %p") if self.received_at else ""

        asm = self.assessment
        if asm:
            score = round(asm.repairability_score, 1)
            circ_score = round(asm.circular_recovery_score, 1)
            decision = asm.recommendation
            repair_cost = round(float(asm.repair_cost), 2)
            comp_val = round(float(asm.component_recovery_value), 2)
            refurb_val = round(float(asm.estimated_refurbished_value), 2)
            co2_val = round(float(asm.co2_avoided_kg), 1)
            components = [c.to_dict() for c in asm.components]
            tech_summary = asm.technical_summary
            tech_score = round(float(asm.technical_condition_score), 1)
            age_score_val = round(float(asm.age_score), 1)
            conf_level = asm.confidence_level
            repair_cost_fmt = f"₹{repair_cost:,.0f}" if repair_cost > 0 else "—"
            comp_val_fmt = f"₹{comp_val:,.0f}" if comp_val > 0 else "—"
            refurb_val_fmt = f"₹{refurb_val:,.0f}" if refurb_val > 0 else "—"
            co2_val_fmt = f"{co2_val:.1f} kg CO₂ avoided" if co2_val > 0 else "—"
        else:
            score = None
            circ_score = None
            decision = "Pending Assessment" if self.status in ("Received", "Queued", "Assessing", "Pending", "Incomplete Information") else self.status
            repair_cost = None
            comp_val = None
            refurb_val = None
            co2_val = None
            components = []
            tech_summary = ""
            tech_score = None
            age_score_val = None
            conf_level = "Pending Assessment"
            repair_cost_fmt = "—"
            comp_val_fmt = "—"
            refurb_val_fmt = "—"
            co2_val_fmt = "—"

        return {
            "id": self.device_id,
            "device_id": self.device_id,
            "name": f"{self.brand} {self.model}".strip(),
            "type": self.device_type,
            "brand": self.brand,
            "model": self.model,
            "purchase_year": self.purchase_year,
            "age": age_str or "Unknown",
            "condition": self.condition,
            "power_status": self.power_status or "Unknown",
            "screen_condition": self.screen_condition or "Unknown",
            "battery_condition": self.battery_condition or "Unknown",
            "weight_kg": self.weight_kg,
            "damage_description": self.damage_description or "None reported",
            "source_application": self.source_application,
            "source_transfer_id": self.source_transfer_id,
            "time": time_str,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "status": self.status,
            "score": score,
            "repairability_score": score,
            "technical_condition_score": tech_score,
            "age_score": age_score_val,
            "confidence_level": conf_level,
            "decision": decision,
            "recommendation": decision,
            "recommended_action": decision,
            "repair_cost": repair_cost,
            "estimated_repair_cost": repair_cost,
            "repair_cost_fmt": repair_cost_fmt,
            "component_recovery_value": comp_val,
            "component_value": comp_val,
            "component_recovery_value_fmt": comp_val_fmt,
            "estimated_refurbished_value": refurb_val,
            "estimated_refurbished_value_fmt": refurb_val_fmt,
            "co2_avoided_kg": co2_val,
            "environmental_benefit": co2_val,
            "co2_avoided_fmt": co2_val_fmt,
            "circular_recovery_score": circ_score,
            "technical_summary": tech_summary,
            "components": components,
            "icon": "device",
        }

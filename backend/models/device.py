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
        score = round(asm.repairability_score, 1) if asm else None
        decision = asm.recommendation if asm else ("Pending Assessment" if self.status in ("Received", "Queued", "Assessing", "Pending") else self.status)
        repair_cost = asm.repair_cost if asm else 0.0
        comp_val = asm.component_recovery_value if asm else 0.0
        refurb_val = asm.estimated_refurbished_value if asm else 0.0
        co2_val = asm.co2_avoided_kg if asm else 0.0
        circ_score = round(asm.circular_recovery_score, 1) if asm else None
        components = [c.to_dict() for c in asm.components] if asm else []

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
            "decision": decision,
            "repair_cost": repair_cost,
            "repair_cost_fmt": f"₹{repair_cost:,.0f}" if repair_cost > 0 else "—",
            "component_recovery_value": comp_val,
            "component_recovery_value_fmt": f"₹{comp_val:,.0f}" if comp_val > 0 else "—",
            "estimated_refurbished_value": refurb_val,
            "estimated_refurbished_value_fmt": f"₹{refurb_val:,.0f}" if refurb_val > 0 else "—",
            "co2_avoided_kg": co2_val,
            "co2_avoided_fmt": f"{co2_val:.1f} kg CO₂ avoided" if co2_val > 0 else "—",
            "circular_recovery_score": circ_score,
            "technical_summary": asm.technical_summary if asm else "",
            "components": components,
            "icon": "device",
        }

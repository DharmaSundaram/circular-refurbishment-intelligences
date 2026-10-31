"""Analytics and aggregation API endpoints for Dashboard and Recovery Intelligence."""

from datetime import datetime, timezone
import requests
from flask import Blueprint, jsonify, current_app
from sqlalchemy import func

from extensions import db
from models.device import Device
from models.assessment import Assessment, AssessmentComponent
from models.transfer import Transfer
from api.auth import require_internal_auth

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/v1")


@analytics_bp.route("/dashboard", methods=["GET"])
@require_internal_auth
def get_dashboard_metrics():
    """Compute live dashboard metrics directly from the database without fabricated statistics."""
    total_devices = Device.query.count()

    pending_count = Device.query.filter(
        Device.status.in_(["Received", "Queued", "Assessing", "Pending"])
    ).count()

    completed_count = Device.query.filter(
        Device.status.in_(["Assessed", "Refurbishment Recommended", "Parts Recovery Recommended", "Completed"])
    ).count()

    refurb_candidates = Assessment.query.filter_by(recommendation="Refurbish").count()
    parts_recovery_count = Assessment.query.filter_by(recommendation="Parts Recovery").count()
    recycle_count = Assessment.query.filter_by(recommendation="Recycle").count()
    reject_count = Assessment.query.filter_by(recommendation="Reject").count()

    # Financial and environmental sums
    financials = db.session.query(
        func.coalesce(func.sum(Assessment.estimated_refurbished_value), 0.0),
        func.coalesce(func.sum(Assessment.component_recovery_value), 0.0),
        func.coalesce(func.sum(Assessment.repair_cost), 0.0),
        func.coalesce(func.sum(Assessment.co2_avoided_kg), 0.0),
        func.coalesce(func.avg(Assessment.repairability_score), 0.0),
        func.coalesce(func.avg(Assessment.circular_recovery_score), 0.0),
    ).first()

    total_refurb_val = float(financials[0]) if financials else 0.0
    total_parts_val = float(financials[1]) if financials else 0.0
    total_repair_cost = float(financials[2]) if financials else 0.0
    total_co2 = float(financials[3]) if financials else 0.0
    avg_repairability = float(financials[4]) if financials else 0.0
    avg_circular = float(financials[5]) if financials else 0.0

    total_recovery_value = total_refurb_val if total_refurb_val > 0 else total_parts_val

    # Category averages
    categories = ["Laptop", "Smartphone", "Monitor"]
    cat_averages = {}
    for cat in categories:
        avg = (
            db.session.query(func.coalesce(func.avg(Assessment.repairability_score), 0.0))
            .join(Device, Device.device_id == Assessment.device_id)
            .filter(Device.device_type.ilike(f"%{cat}%"))
            .scalar()
        )
        cat_averages[cat] = round(float(avg), 1)

    # Real Collection Application Connectivity Check (Phase 8 Requirement)
    collection_url = current_app.config.get("COLLECTION_API_URL", "").rstrip("/")
    collection_key = current_app.config.get("COLLECTION_API_KEY", "")
    partner_connected = False
    partner_status = "Not Configured"

    if collection_url:
        try:
            headers = {"X-API-Key": collection_key} if collection_key else {}
            resp = requests.get(f"{collection_url}/api/health", headers=headers, timeout=2)
            if resp.status_code in (200, 204):
                partner_connected = True
                partner_status = "Connected"
            else:
                partner_status = f"Degraded (HTTP {resp.status_code})"
        except Exception:
            partner_status = "Disconnected"

    # Real synchronization timestamp from the most recent completed transfer
    latest_transfer = (
        Transfer.query.filter_by(status="Completed")
        .order_by(Transfer.created_at.desc())
        .first()
    )
    if not latest_transfer:
        latest_transfer = Transfer.query.order_by(Transfer.created_at.desc()).first()

    sync_iso = latest_transfer.created_at.isoformat() if latest_transfer else None
    sync_fmt = (
        latest_transfer.created_at.strftime("%b %d, %Y · %I:%M %p")
        if latest_transfer
        else "No sync recorded"
    )

    def fmt_lakh(val):
        if val >= 100000:
            return f"₹{val / 100000:.2f}L"
        return f"₹{val:,.0f}"

    recent_devices = [d.to_dict() for d in Device.query.order_by(Device.received_at.desc()).limit(5).all()]
    recent_transfers = [t.to_dict() for t in Transfer.query.order_by(Transfer.created_at.desc()).limit(5).all()]

    return jsonify({
        "metrics": {
            "incoming_devices": total_devices,
            "incoming_devices_fmt": f"{total_devices:,}",
            "pending_assessments": pending_count,
            "completed_assessments": completed_count,
            "refurbishment_candidates": refurb_candidates,
            "parts_recovery": parts_recovery_count,
            "recycling": recycle_count,
            "rejected": reject_count,
            "total_recovery_value": round(total_recovery_value, 2),
            "total_recovery_value_fmt": fmt_lakh(total_recovery_value),
            "total_repair_cost": round(total_repair_cost, 2),
            "total_repair_cost_fmt": fmt_lakh(total_repair_cost),
            "total_refurbished_value": round(total_refurb_val, 2),
            "total_refurbished_value_fmt": fmt_lakh(total_refurb_val),
            "total_co2_avoided_kg": round(total_co2, 1),
            "total_co2_avoided_fmt": f"{total_co2:.1f} kg" if total_co2 < 1000 else f"{total_co2/1000:.1f} t CO₂",
            "average_repairability": round(avg_repairability, 1),
            "average_circular_recovery": round(avg_circular, 1),
            "category_averages": cat_averages,
            "partner_status": partner_status,
            "partner_connected": partner_connected,
            "last_sync_timestamp": sync_iso,
            "last_sync_formatted": sync_fmt,
            "decision_distribution": {
                "Refurbish": refurb_candidates,
                "Parts Recovery": parts_recovery_count,
                "Recycle": recycle_count,
                "Reject": reject_count,
            },
            "repairability_overview": {
                "average_score": round(avg_repairability, 1),
                "average_circular_recovery": round(avg_circular, 1),
                "categories": cat_averages,
            },
        },
        "partner_connection": {
            "status": partner_status,
            "connected": partner_connected,
            "last_sync_timestamp": sync_iso,
            "last_sync_formatted": sync_fmt,
            "endpoint": collection_url or None,
        },
        "recent_devices": recent_devices,
        "recent_transfers": recent_transfers,
        "decision_distribution": {
            "Refurbish": refurb_candidates,
            "Parts Recovery": parts_recovery_count,
            "Recycle": recycle_count,
            "Reject": reject_count,
        },
        "repairability_overview": {
            "average_score": round(avg_repairability, 1),
            "average_circular_recovery": round(avg_circular, 1),
            "categories": cat_averages,
        },
    })


@analytics_bp.route("/recovery-analysis", methods=["GET"])
@require_internal_auth
def get_recovery_analysis():
    """Retrieve aggregated recovery intelligence across all assessed devices."""
    financials = db.session.query(
        func.coalesce(func.sum(Assessment.estimated_refurbished_value), 0.0),
        func.coalesce(func.sum(Assessment.component_recovery_value), 0.0),
        func.coalesce(func.sum(Assessment.repair_cost), 0.0),
        func.coalesce(func.sum(Assessment.co2_avoided_kg), 0.0),
        func.coalesce(func.sum(Device.weight_kg), 0.0),
    ).join(Device, Device.device_id == Assessment.device_id).first()

    total_refurb = float(financials[0]) if financials else 0.0
    total_parts = float(financials[1]) if financials else 0.0
    total_repair = float(financials[2]) if financials else 0.0
    total_co2 = float(financials[3]) if financials else 0.0
    total_weight = float(financials[4]) if financials else 0.0

    total_recovery = total_refurb if total_refurb > 0 else total_parts

    def fmt_lakh(val):
        if val >= 100000:
            return f"₹{val / 100000:.2f}L"
        return f"₹{val:,.0f}"

    comp_groups = [
        ("Displays", ["display", "panel"]),
        ("SSDs & storage", ["ssd", "storage"]),
        ("RAM", ["ram", "memory"]),
        ("Motherboards", ["motherboard", "mainboard", "board", "power board"]),
        ("Other components", ["battery", "camera", "housing", "stand", "chassis"]),
    ]

    component_totals = []
    for label, keywords in comp_groups:
        conditions = [AssessmentComponent.component_name.ilike(f"%{kw}%") for kw in keywords]
        val = (
            db.session.query(func.coalesce(func.sum(AssessmentComponent.estimated_value), 0.0))
            .filter(db.or_(*conditions))
            .scalar()
        )
        component_totals.append({
            "name": label,
            "value": round(float(val), 2),
            "value_fmt": fmt_lakh(float(val)),
        })

    pathway_counts = {
        "Refurbish": Assessment.query.filter_by(recommendation="Refurbish").count(),
        "Parts Recovery": Assessment.query.filter_by(recommendation="Parts Recovery").count(),
        "Recycle": Assessment.query.filter_by(recommendation="Recycle").count(),
        "Reject": Assessment.query.filter_by(recommendation="Reject").count(),
    }

    return jsonify({
        "metrics": {
            "total_recovery_value": round(total_recovery, 2),
            "total_recovery_value_fmt": fmt_lakh(total_recovery),
            "estimated_repair_cost": round(total_repair, 2),
            "estimated_repair_cost_fmt": fmt_lakh(total_repair),
            "estimated_refurbished_value": round(total_refurb, 2),
            "estimated_refurbished_value_fmt": fmt_lakh(total_refurb),
            "potential_material_recovery_kg": round(total_weight, 1),
            "environmental_benefit_co2": round(total_co2, 1),
            "environmental_benefit_co2_fmt": f"{total_co2:.1f} kg CO₂" if total_co2 < 1000 else f"{total_co2/1000:.1f} t CO₂",
        },
        "pathway_distribution": pathway_counts,
        "component_breakdown": component_totals,
    })

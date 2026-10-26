"""Assessment API endpoints for initiating, calculating, retrieving, and dispatching assessments."""

import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

from extensions import db
from models.device import Device
from models.assessment import Assessment, AssessmentComponent
from models.recovery import RecoveryAnalysis
from models.report import Report
from services.assessment_engine import evaluate_device_assessment
from services.callback_service import send_assessment_result_to_collection

assessments_bp = Blueprint("assessments", __name__, url_prefix="/api/v1")


@assessments_bp.route("/assessments", methods=["POST"])
def create_or_run_assessment():
    """Create and compute a deterministic assessment for a device."""
    if not request.is_json:
        return jsonify({"error": "Bad Request", "message": "JSON body required"}), 400

    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    if not device_id:
        return jsonify({"error": "Bad Request", "message": "device_id is required"}), 400

    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Not Found", "message": f"Device {device_id} not found"}), 404

    # Run deterministic assessment engine
    results = evaluate_device_assessment(device.to_dict())

    # Optional overrides from client if provided
    repairability = data.get("repairability_score", results["repairability_score"])
    circular_score = data.get("circular_recovery_score", results["circular_recovery_score"])
    repair_cost = data.get("repair_cost", results["repair_cost"])
    comp_value = data.get("component_recovery_value", results["component_recovery_value"])
    refurb_value = data.get("estimated_refurbished_value", results["estimated_refurbished_value"])
    co2_avoided = data.get("co2_avoided_kg", results["co2_avoided_kg"])
    recommendation = data.get("recommendation", results["recommendation"])
    technical_summary = data.get("technical_summary", results["technical_summary"])
    assessor = data.get("assessor", "Refurbishment Admin")

    try:
        # Check if assessment already exists for device
        assessment = Assessment.query.filter_by(device_id=device_id).first()
        if not assessment:
            assessment_id = f"ASM-{uuid.uuid4().hex[:8].upper()}"
            assessment = Assessment(
                assessment_id=assessment_id,
                device_id=device_id,
                repairability_score=float(repairability),
                circular_recovery_score=float(circular_score),
                repair_cost=float(repair_cost),
                component_recovery_value=float(comp_value),
                estimated_refurbished_value=float(refurb_value),
                co2_avoided_kg=float(co2_avoided),
                recommendation=recommendation,
                technical_summary=technical_summary,
                assessor=assessor,
                assessed_at=datetime.utcnow(),
            )
            db.session.add(assessment)
        else:
            assessment.repairability_score = float(repairability)
            assessment.circular_recovery_score = float(circular_score)
            assessment.repair_cost = float(repair_cost)
            assessment.component_recovery_value = float(comp_value)
            assessment.estimated_refurbished_value = float(refurb_value)
            assessment.co2_avoided_kg = float(co2_avoided)
            assessment.recommendation = recommendation
            assessment.technical_summary = technical_summary
            assessment.assessor = assessor
            assessment.assessed_at = datetime.utcnow()
            # Clear old components
            AssessmentComponent.query.filter_by(assessment_id=assessment.assessment_id).delete()

        # Add components
        for comp_data in results.get("components", []):
            comp = AssessmentComponent(
                assessment_id=assessment.assessment_id,
                component_name=comp_data["component_name"],
                condition=comp_data["condition"],
                recoverable=comp_data["recoverable"],
                estimated_value=float(comp_data["estimated_value"]),
                notes=comp_data.get("notes"),
            )
            db.session.add(comp)

        # Create or update RecoveryAnalysis record
        rec_analysis = RecoveryAnalysis.query.filter_by(device_id=device_id).first()
        if not rec_analysis:
            rec_analysis = RecoveryAnalysis(
                analysis_id=f"REC-{uuid.uuid4().hex[:8].upper()}",
                device_id=device_id,
                assessment_id=assessment.assessment_id,
                estimated_recovery_value=float(comp_value if recommendation == "Parts Recovery" else refurb_value),
                repair_cost=float(repair_cost),
                refurbished_value=float(refurb_value),
                parts_value=float(comp_value),
                co2_avoided_kg=float(co2_avoided),
                recovery_path=recommendation,
                analysis_summary=technical_summary,
            )
            db.session.add(rec_analysis)
        else:
            rec_analysis.assessment_id = assessment.assessment_id
            rec_analysis.estimated_recovery_value = float(comp_value if recommendation == "Parts Recovery" else refurb_value)
            rec_analysis.repair_cost = float(repair_cost)
            rec_analysis.refurbished_value = float(refurb_value)
            rec_analysis.parts_value = float(comp_value)
            rec_analysis.co2_avoided_kg = float(co2_avoided)
            rec_analysis.recovery_path = recommendation
            rec_analysis.analysis_summary = technical_summary

        # Update Device status
        if recommendation == "Refurbish":
            device.status = "Refurbishment Recommended"
        elif recommendation == "Parts Recovery":
            device.status = "Parts Recovery Recommended"
        elif recommendation == "Reject":
            device.status = "Rejected"
        else:
            device.status = "Assessed"

        # Create Report record if not already recorded
        existing_report = Report.query.filter_by(device_id=device_id, report_type="assessment_pdf").first()
        if not existing_report:
            rep = Report(
                report_id=f"REP-{uuid.uuid4().hex[:8].upper()}",
                device_id=device_id,
                assessment_id=assessment.assessment_id,
                report_type="assessment_pdf",
                filename=f"assessment_{device_id}.pdf",
            )
            db.session.add(rep)

        db.session.commit()

        resp_dict = assessment.to_dict()
        resp_dict["reasons"] = results.get("reasons", [])
        return jsonify({
            "status": "success",
            "message": "Assessment evaluated and stored",
            "assessment": resp_dict,
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error evaluating assessment: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@assessments_bp.route("/assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    """Retrieve an assessment by ID."""
    assessment = Assessment.query.filter_by(assessment_id=assessment_id).first()
    if not assessment:
        return jsonify({"error": "Not Found", "message": f"Assessment {assessment_id} not found"}), 404

    return jsonify(assessment.to_dict())


@assessments_bp.route("/assessments/device/<device_id>", methods=["GET"])
def get_device_assessment(device_id):
    """Retrieve an assessment by device ID."""
    assessment = Assessment.query.filter_by(device_id=device_id).first()
    if not assessment:
        return jsonify({"error": "Not Found", "message": f"No assessment found for device {device_id}"}), 404

    return jsonify(assessment.to_dict())


@assessments_bp.route("/assessment-results/send", methods=["POST"])
@assessments_bp.route("/assessments/send", methods=["POST"])
def send_assessment_result():
    """Dispatch assessment result callback to the Collection Application."""
    data = request.get_json(silent=True) or {}
    assessment_id = data.get("assessment_id")
    device_id = data.get("device_id")

    if not assessment_id and device_id:
        asm = Assessment.query.filter_by(device_id=device_id).first()
        if asm:
            assessment_id = asm.assessment_id

    if not assessment_id:
        return jsonify({"error": "Bad Request", "message": "assessment_id or device_id is required"}), 400

    success, http_code, message, transfer = send_assessment_result_to_collection(assessment_id)

    # If successfully delivered, mark device as Completed
    if success:
        asm = Assessment.query.filter_by(assessment_id=assessment_id).first()
        if asm and asm.device:
            asm.device.status = "Completed"
            db.session.commit()

    response_status = 200 if success else (http_code if http_code and http_code > 0 else 503)

    return jsonify({
        "success": success,
        "http_status": http_code,
        "message": message,
        "transfer_id": transfer.transfer_id if transfer else None,
    }), response_status

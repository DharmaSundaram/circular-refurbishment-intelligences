"""Report API endpoints for downloading real PDF assessment reports and CSV exports."""

from flask import Blueprint, jsonify, send_file, Response
from services.report_service import generate_assessment_pdf, generate_summary_csv

reports_bp = Blueprint("reports", __name__, url_prefix="/api/v1")


@reports_bp.route("/reports/assessment/<device_id>", methods=["GET"])
@reports_bp.route("/reports/recovery/<device_id>", methods=["GET"])
def download_assessment_report(device_id):
    """Download a real, generated ReportLab PDF assessment report."""
    pdf_buffer = generate_assessment_pdf(device_id)
    if not pdf_buffer:
        return jsonify({
            "error": "Not Found",
            "message": f"No assessment record found for device {device_id}. Complete assessment first.",
        }), 404

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"assessment_{device_id}.pdf",
    )


@reports_bp.route("/reports/summary", methods=["GET"])
def download_summary_csv():
    """Download a CSV summary of all devices and recovery decisions."""
    csv_stream = generate_summary_csv()
    return Response(
        csv_stream.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=refurbishment_intelligence_summary.csv"},
    )

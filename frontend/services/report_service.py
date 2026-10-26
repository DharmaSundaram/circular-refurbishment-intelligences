"""Report generation service using ReportLab for real PDFs and standard csv for CSV summaries."""

import io
import csv
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from models.device import Device
from models.assessment import Assessment


def generate_assessment_pdf(device_id: str) -> Optional[io.BytesIO]:
    """Generate a real, professional PDF assessment report for a device using ReportLab.
    
    Returns BytesIO buffer or None if assessment doesn't exist.
    """
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return None

    assessment = Assessment.query.filter_by(device_id=device_id).first()
    if not assessment:
        return None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0D382B"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4A6B61"),
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0D382B"),
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyDark",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#2C3E38"),
    )
    badge_style = ParagraphStyle(
        "BadgeText",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0D382B"),
        alignment=1,
    )

    elements = []

    # Header
    elements.append(Paragraph("<b>circular.</b> Refurbishment Intelligence", title_style))
    elements.append(Paragraph("CIRCULAR RECOVERY ASSESSMENT REPORT", subtitle_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A7A5C"), spaceAfter=15))

    # Device & Metadata Table
    meta_data = [
        [
            Paragraph("<b>Device:</b>", body_style),
            Paragraph(f"{device.brand} {device.model}", body_style),
            Paragraph("<b>Device ID:</b>", body_style),
            Paragraph(device.device_id, body_style),
        ],
        [
            Paragraph("<b>Device Type:</b>", body_style),
            Paragraph(device.device_type, body_style),
            Paragraph("<b>Physical Condition:</b>", body_style),
            Paragraph(device.condition, body_style),
        ],
        [
            Paragraph("<b>Power Status:</b>", body_style),
            Paragraph(device.power_status or "Unknown", body_style),
            Paragraph("<b>Battery Condition:</b>", body_style),
            Paragraph(device.battery_condition or "Unknown", body_style),
        ],
        [
            Paragraph("<b>Assessed Date:</b>", body_style),
            Paragraph(assessment.assessed_at.strftime("%B %d, %Y · %I:%M %p") if assessment.assessed_at else "N/A", body_style),
            Paragraph("<b>Assessor:</b>", body_style),
            Paragraph(assessment.assessor, body_style),
        ],
    ]

    meta_table = Table(meta_data, colWidths=[1.3 * inch, 2.3 * inch, 1.4 * inch, 2.0 * inch])
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F8F6")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E6E0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5EFEA")),
            ("PADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    elements.append(meta_table)
    elements.append(Spacer(1, 15))

    # Recommendation Banner
    elements.append(Paragraph("Assessment Decision & Key Metrics", heading_style))
    rec_color = colors.HexColor("#E2F5EE") if assessment.recommendation == "Refurbish" else colors.HexColor("#FFF5E5")
    border_color = colors.HexColor("#1A7A5C") if assessment.recommendation == "Refurbish" else colors.HexColor("#D9822B")

    metrics_data = [
        [
            Paragraph("<b>RECOMMENDED PATHWAY</b>", subtitle_style),
            Paragraph("<b>REPAIRABILITY SCORE</b>", subtitle_style),
            Paragraph("<b>CIRCULAR RECOVERY</b>", subtitle_style),
            Paragraph("<b>CO2 AVOIDED</b>", subtitle_style),
        ],
        [
            Paragraph(f"<b>{assessment.recommendation.upper()}</b>", badge_style),
            Paragraph(f"<b>{assessment.repairability_score:.0f} / 100</b>", badge_style),
            Paragraph(f"<b>{assessment.circular_recovery_score:.0f} / 100</b>", badge_style),
            Paragraph(f"<b>{assessment.co2_avoided_kg:.1f} kg</b>", badge_style),
        ],
    ]
    metrics_table = Table(metrics_data, colWidths=[1.8 * inch, 1.8 * inch, 1.8 * inch, 1.6 * inch])
    metrics_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), rec_color),
            ("BOX", (0, 0), (-1, -1), 1, border_color),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0E2DB")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("PADDING", (0, 0), (-1, -1), 8),
        ])
    )
    elements.append(metrics_table)
    elements.append(Spacer(1, 15))

    # Financial / Circular Value Table
    elements.append(Paragraph("Economic & Recovery Valuation", heading_style))
    fin_data = [
        [Paragraph("<b>Metric</b>", body_style), Paragraph("<b>Estimated Valuation</b>", body_style)],
        [Paragraph("Estimated Repair Cost", body_style), Paragraph(f"INR {assessment.repair_cost:,.2f}", body_style)],
        [Paragraph("Component Recovery Value (Parts)", body_style), Paragraph(f"INR {assessment.component_recovery_value:,.2f}", body_style)],
        [Paragraph("Estimated Refurbished Market Value", body_style), Paragraph(f"INR {assessment.estimated_refurbished_value:,.2f}", body_style)],
        [Paragraph("Potential Net Circular Value", body_style), Paragraph(f"INR {max(0, assessment.estimated_refurbished_value - assessment.repair_cost):,.2f}", body_style)],
    ]
    fin_table = Table(fin_data, colWidths=[4.2 * inch, 2.8 * inch])
    fin_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F3EE")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0E2DB")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5EFEA")),
            ("PADDING", (0, 0), (-1, -1), 5),
        ])
    )
    elements.append(fin_table)
    elements.append(Spacer(1, 15))

    # Technical Explanation
    elements.append(Paragraph("Technical Summary & Decision Rationale", heading_style))
    elements.append(Paragraph(assessment.technical_summary, body_style))
    elements.append(Spacer(1, 20))

    # Footer
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#C5DDD4"), spaceAfter=10))
    elements.append(
        Paragraph(
            "Prepared by Refurbishment Intelligence · circular. E-Waste Intelligence Platform · Confidential Audit Document",
            subtitle_style,
        )
    )

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_summary_csv() -> io.StringIO:
    """Generate summary CSV of all devices and their assessment outcomes."""
    devices = Device.query.order_by(Device.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Device ID",
        "Brand",
        "Model",
        "Device Type",
        "Physical Condition",
        "Status",
        "Repairability Score",
        "Circular Recovery Score",
        "Repair Cost (INR)",
        "Component Recovery Value (INR)",
        "Refurbished Value (INR)",
        "CO2 Avoided (kg)",
        "Recommendation",
        "Received At",
        "Assessed At",
    ])

    for d in devices:
        asm = d.assessment
        writer.writerow([
            d.device_id,
            d.brand,
            d.model,
            d.device_type,
            d.condition,
            d.status,
            f"{asm.repairability_score:.1f}" if asm else "",
            f"{asm.circular_recovery_score:.1f}" if asm else "",
            f"{asm.repair_cost:.2f}" if asm else "",
            f"{asm.component_recovery_value:.2f}" if asm else "",
            f"{asm.estimated_refurbished_value:.2f}" if asm else "",
            f"{asm.co2_avoided_kg:.1f}" if asm else "",
            asm.recommendation if asm else "",
            d.received_at.isoformat() if d.received_at else "",
            asm.assessed_at.isoformat() if (asm and asm.assessed_at) else "",
        ])

    output.seek(0)
    return output

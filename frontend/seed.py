"""Database seeding script for local development and test environments."""

from datetime import datetime, timedelta
import json
from extensions import db
from models.device import Device
from models.transfer import Transfer
from models.assessment import Assessment, AssessmentComponent
from models.recovery import RecoveryAnalysis
from models.report import Report
from services.assessment_engine import evaluate_device_assessment


def seed_database():
    """Seed initial baseline devices and deterministic assessment records."""
    if Device.query.first():
        return  # Already seeded

    devices_data = [
        {
            "device_id": "EW-2026-00128",
            "type": "Laptop",
            "brand": "Dell",
            "model": "Latitude 5420",
            "purchase_year": 2023,
            "age": "3 years",
            "condition": "Damaged",
            "power_status": "Powers on",
            "screen_condition": "Minor scratches",
            "battery_condition": "Poor · 42% capacity",
            "weight_kg": 1.4,
            "damage_description": "Worn battery and damaged keyboard. No liquid damage.",
            "status": "Assessing",
            "received_time_delta_min": 25,
        },
        {
            "device_id": "EW-2026-00127",
            "type": "Smartphone",
            "brand": "Samsung",
            "model": "Galaxy S21",
            "purchase_year": 2024,
            "age": "2 years",
            "condition": "Good",
            "power_status": "Powers on",
            "screen_condition": "Good",
            "battery_condition": "Good",
            "weight_kg": 0.17,
            "damage_description": "Minimal wear. Fully functional.",
            "status": "Completed",
            "received_time_delta_min": 50,
        },
        {
            "device_id": "EW-2026-00126",
            "type": "Monitor",
            "brand": "HP",
            "model": "EliteDisplay E243",
            "purchase_year": 2021,
            "age": "5 years",
            "condition": "Not Working",
            "power_status": "No power",
            "screen_condition": "Good",
            "battery_condition": "N/A",
            "weight_kg": 5.2,
            "damage_description": "Power board failure. Panel intact.",
            "status": "Completed",
            "received_time_delta_min": 70,
        },
        {
            "device_id": "EW-2026-00125",
            "type": "Laptop",
            "brand": "Lenovo",
            "model": "ThinkPad T480",
            "purchase_year": 2022,
            "age": "4 years",
            "condition": "Fair",
            "power_status": "Powers on",
            "screen_condition": "Good",
            "battery_condition": "Fair",
            "weight_kg": 1.6,
            "damage_description": "Minor chassis wear, functioning hardware.",
            "status": "In progress",
            "received_time_delta_min": 95,
        },
        {
            "device_id": "EW-2026-00124",
            "type": "Smartphone",
            "brand": "Apple",
            "model": "iPhone 11",
            "purchase_year": 2021,
            "age": "5 years",
            "condition": "Damaged",
            "power_status": "Powers on",
            "screen_condition": "Cracked",
            "battery_condition": "Poor",
            "weight_kg": 0.19,
            "damage_description": "Cracked front glass, worn battery, camera functional.",
            "status": "Queued",
            "received_time_delta_min": 115,
        },
    ]

    now = datetime.utcnow()

    for idx, d_info in enumerate(devices_data):
        dev_id = d_info["device_id"]
        rec_time = now - timedelta(minutes=d_info["received_time_delta_min"])
        transfer_id = f"TRF-00{840 + idx}"

        device = Device(
            device_id=dev_id,
            device_type=d_info["type"],
            brand=d_info["brand"],
            model=d_info["model"],
            purchase_year=d_info["purchase_year"],
            age=d_info["age"],
            condition=d_info["condition"],
            power_status=d_info["power_status"],
            screen_condition=d_info["screen_condition"],
            battery_condition=d_info["battery_condition"],
            weight_kg=d_info["weight_kg"],
            damage_description=d_info["damage_description"],
            source_application="Collection Application",
            source_transfer_id=transfer_id,
            received_at=rec_time,
            status=d_info["status"],
        )
        db.session.add(device)

        # Inbound Transfer record
        inbound_transfer = Transfer(
            transfer_id=transfer_id,
            device_id=dev_id,
            direction="Inbound",
            sender="Collection",
            receiver="Refurbishment",
            endpoint="/api/v1/refurbishment/devices",
            http_method="POST",
            request_payload=json.dumps({"device_id": dev_id, "transfer_id": transfer_id, "device": d_info}),
            response_payload=json.dumps({"status": "success", "message": "Received"}),
            http_status=201,
            status="Completed",
            idempotency_key=transfer_id,
            retry_count=0,
            created_at=rec_time,
        )
        db.session.add(inbound_transfer)

        # Run assessment algorithm
        results = evaluate_device_assessment(d_info)

        asm_id = f"ASM-00{840 + idx}"
        assessment = Assessment(
            assessment_id=asm_id,
            device_id=dev_id,
            repairability_score=results["repairability_score"],
            circular_recovery_score=results["circular_recovery_score"],
            repair_cost=results["repair_cost"],
            component_recovery_value=results["component_recovery_value"],
            estimated_refurbished_value=results["estimated_refurbished_value"],
            co2_avoided_kg=results["co2_avoided_kg"],
            recommendation=results["recommendation"],
            technical_summary=results["technical_summary"],
            assessor="Refurbishment Admin",
            assessed_at=rec_time + timedelta(minutes=15),
            created_at=rec_time + timedelta(minutes=15),
        )
        db.session.add(assessment)

        # Components
        for comp in results["components"]:
            c_row = AssessmentComponent(
                assessment_id=asm_id,
                component_name=comp["component_name"],
                condition=comp["condition"],
                recoverable=comp["recoverable"],
                estimated_value=comp["estimated_value"],
                notes=comp.get("notes"),
            )
            db.session.add(c_row)

        # Recovery Analysis
        rec_row = RecoveryAnalysis(
            analysis_id=f"REC-00{840 + idx}",
            device_id=dev_id,
            assessment_id=asm_id,
            estimated_recovery_value=results["estimated_refurbished_value"] if results["recommendation"] == "Refurbish" else results["component_recovery_value"],
            repair_cost=results["repair_cost"],
            refurbished_value=results["estimated_refurbished_value"],
            parts_value=results["component_recovery_value"],
            co2_avoided_kg=results["co2_avoided_kg"],
            recovery_path=results["recommendation"],
            analysis_summary=results["technical_summary"],
            created_at=rec_time + timedelta(minutes=15),
        )
        db.session.add(rec_row)

        # Report record
        rep_row = Report(
            report_id=f"REP-00{840 + idx}",
            device_id=dev_id,
            assessment_id=asm_id,
            report_type="assessment_pdf",
            filename=f"assessment_{dev_id}.pdf",
            created_at=rec_time + timedelta(minutes=16),
        )
        db.session.add(rep_row)

        # If completed, add an outbound transfer record
        if d_info["status"] == "Completed":
            out_transfer = Transfer(
                transfer_id=f"TRF-00{850 + idx}",
                device_id=dev_id,
                direction="Outbound",
                sender="Refurbishment",
                receiver="Collection",
                endpoint="/api/v1/assessment-results",
                http_method="POST",
                request_payload=json.dumps({"device_id": dev_id, "assessment_id": asm_id, "recommendation": results["recommendation"]}),
                response_payload=json.dumps({"status": "received", "code": 200}),
                http_status=200,
                status="Completed",
                idempotency_key=asm_id,
                retry_count=0,
                created_at=rec_time + timedelta(minutes=20),
            )
            db.session.add(out_transfer)

    db.session.commit()

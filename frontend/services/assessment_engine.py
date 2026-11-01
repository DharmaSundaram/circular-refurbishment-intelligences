"""Deterministic, explainable, and rule-based Assessment Engine for Refurbishment Intelligence.

Calculates:
- Technical condition score (0-100)
- Age score (0-100)
- Repairability score (0-100)
- Circular recovery score (0-100)
- Estimated repair cost (INR)
- Component recovery values and itemized component breakdown
- Estimated refurbished value (INR)
- Avoided CO2 emissions (kg)
- Confidence level
- Recommended recovery decision: Refurbish, Parts Recovery, Recycle, Reject
- Transparent technical summary & bullet reasons
"""

from typing import Dict, Any, List, Tuple


def evaluate_device_assessment(device_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Run transparent, deterministic rule-based assessment algorithm on device attributes."""
    dtype = (device_dict.get("device_type") or device_dict.get("type") or "Laptop").strip().title()
    brand = (device_dict.get("brand") or "").strip().title()
    model = (device_dict.get("model") or device_dict.get("name") or "").strip()
    condition = (device_dict.get("condition") or "Fair").strip()
    power_status = (device_dict.get("power_status") or "Powers on").strip()
    screen_cond = (device_dict.get("screen_condition") or "Good").strip()
    battery_cond = (device_dict.get("battery_condition") or "Fair").strip()
    damage_desc = (device_dict.get("damage_description") or "").lower()

    # Parse age in years
    age_raw = device_dict.get("age", 3)
    try:
        if isinstance(age_raw, str):
            age_years = int("".join(filter(str.isdigit, age_raw)) or 3)
        else:
            age_years = int(age_raw)
    except Exception:
        age_years = 3

    # Parse weight in kg
    try:
        weight_kg = float(device_dict.get("weight_kg") or 1.5)
        if weight_kg <= 0:
            weight_kg = 1.5
    except (ValueError, TypeError):
        weight_kg = 1.5

    # ---------------------------------------------------------
    # 1. TECHNICAL CONDITION SCORE (0 - 100)
    # ---------------------------------------------------------
    # Evaluates physical and functional hardware health
    tech_score = 0.0

    # Physical condition base (35 max)
    cond_lower = condition.lower()
    if "good" in cond_lower or "excellent" in cond_lower:
        tech_score += 35.0
    elif "fair" in cond_lower or "moderate" in cond_lower:
        tech_score += 26.0
    elif "damaged" in cond_lower:
        tech_score += 16.0
    else:  # "not working", "poor", etc.
        tech_score += 8.0

    # Power status base (30 max)
    power_lower = power_status.lower()
    if "on" in power_lower or "powers on" in power_lower or "working" in power_lower:
        tech_score += 30.0
    elif "intermittent" in power_lower:
        tech_score += 15.0
    else:  # "no power", "off", "dead"
        tech_score += 4.0

    # Screen condition base (20 max)
    screen_lower = screen_cond.lower()
    if "good" in screen_lower or "perfect" in screen_lower or "none" in screen_lower:
        tech_score += 20.0
    elif "scratch" in screen_lower or "minor" in screen_lower or "fair" in screen_lower:
        tech_score += 15.0
    elif "cracked" in screen_lower:
        tech_score += 6.0
    else:  # Broken / dead display
        tech_score += 2.0

    # Battery condition base (15 max)
    battery_lower = battery_cond.lower()
    if "good" in battery_lower or "healthy" in battery_lower or "excellent" in battery_lower:
        tech_score += 15.0
    elif "fair" in battery_lower or "moderate" in battery_lower:
        tech_score += 10.0
    elif "poor" in battery_lower or "worn" in battery_lower or "%" in battery_lower:
        tech_score += 5.0
    else:  # dead / missing
        tech_score += 1.0

    # Damage description deductions
    if "liquid" in damage_desc or "water" in damage_desc:
        tech_score -= 20.0
    if "corrosion" in damage_desc or "burn" in damage_desc:
        tech_score -= 15.0
    if "broken hinge" in damage_desc or "dent" in damage_desc:
        tech_score -= 5.0

    technical_condition_score = round(max(5.0, min(100.0, tech_score)), 1)

    # ---------------------------------------------------------
    # 2. AGE SCORE (0 - 100)
    # ---------------------------------------------------------
    # Evaluates component depreciation and generational obsolescence
    age_score = round(max(10.0, min(100.0, 100.0 - (age_years * 14.0))), 1)

    # ---------------------------------------------------------
    # 3. REPAIRABILITY SCORE (0 - 100)
    # ---------------------------------------------------------
    # Weighted synthesis of Technical Condition (50%), Age (25%), Modularity Index (25%)
    if "laptop" in dtype.lower():
        modularity = 90.0
    elif "tablet" in dtype.lower():
        modularity = 65.0
    elif "smart" in dtype.lower() or "phone" in dtype.lower():
        modularity = 70.0
    elif "monitor" in dtype.lower() or "display" in dtype.lower():
        modularity = 85.0
    else:
        modularity = 75.0

    repairability_raw = (technical_condition_score * 0.50) + (age_score * 0.25) + (modularity * 0.25)
    repairability_score = round(max(5.0, min(100.0, repairability_raw)), 1)

    # ---------------------------------------------------------
    # 4. CONFIDENCE LEVEL
    # ---------------------------------------------------------
    verified_fields = 0
    total_fields = 9
    if device_dict.get("device_type") or device_dict.get("type"):
        verified_fields += 1
    if device_dict.get("brand"):
        verified_fields += 1
    if device_dict.get("model") or device_dict.get("name"):
        verified_fields += 1
    if device_dict.get("condition"):
        verified_fields += 1
    if device_dict.get("power_status"):
        verified_fields += 1
    if device_dict.get("screen_condition"):
        verified_fields += 1
    if device_dict.get("battery_condition"):
        verified_fields += 1
    if device_dict.get("age") is not None or device_dict.get("purchase_year") is not None:
        verified_fields += 1
    if device_dict.get("weight_kg") is not None and float(device_dict.get("weight_kg") or 0) > 0:
        verified_fields += 1

    ratio = verified_fields / total_fields
    if ratio >= 0.90:
        confidence_level = f"High ({int(ratio * 100)}%)"
    elif ratio >= 0.70:
        confidence_level = f"Medium ({int(ratio * 100)}%)"
    else:
        confidence_level = f"Moderate ({int(ratio * 100)}%)"

    # ---------------------------------------------------------
    # 5. COMPONENT RECOVERY BREAKDOWN & VALUES
    # ---------------------------------------------------------
    components = []
    if "laptop" in dtype.lower():
        # RAM
        ram_ok = "liquid" not in damage_desc and "not working" not in cond_lower
        ram_val = 1600.0 if ram_ok else 400.0
        components.append({
            "component_name": "RAM",
            "condition": "Good" if ram_ok else "Fair",
            "recoverable": ram_ok,
            "estimated_value": ram_val,
            "notes": "High retention DDR4/DDR5 modules" if ram_ok else "Untested memory module",
        })
        # SSD
        ssd_ok = "liquid" not in damage_desc
        ssd_val = 2200.0 if ssd_ok else 500.0
        components.append({
            "component_name": "SSD",
            "condition": "Good" if ssd_ok else "Fair",
            "recoverable": ssd_ok,
            "estimated_value": ssd_val,
            "notes": "NVMe storage certified recoverable" if ssd_ok else "Requires secure data wipe & test",
        })
        # Display
        disp_ok = "cracked" not in screen_lower and "broken" not in screen_lower
        disp_val = 3800.0 if disp_ok else 800.0
        components.append({
            "component_name": "Display",
            "condition": "Good" if "good" in screen_lower else ("Fair" if disp_ok else "Damaged"),
            "recoverable": disp_ok,
            "estimated_value": disp_val,
            "notes": "Functional LCD/IPS panel" if disp_ok else "Backlight/refurbish parts only",
        })
        # Battery
        bat_ok = "poor" not in battery_lower and "dead" not in battery_lower and "worn" not in battery_lower
        bat_val = 1400.0 if bat_ok else 600.0
        components.append({
            "component_name": "Battery",
            "condition": "Good" if bat_ok else "Poor",
            "recoverable": bat_ok,
            "estimated_value": bat_val,
            "notes": "Retains viable health cycle" if bat_ok else "Recycle cells / replace required",
        })
        # Motherboard
        mobo_ok = "powers on" in power_lower and "liquid" not in damage_desc
        mobo_val = 4500.0 if mobo_ok else 1200.0
        components.append({
            "component_name": "Motherboard",
            "condition": "Good" if mobo_ok else "Faulty",
            "recoverable": mobo_ok,
            "estimated_value": mobo_val,
            "notes": "Mainboard chipset fully operational" if mobo_ok else "Component-level micro-salvage",
        })

    elif "smart" in dtype.lower() or "phone" in dtype.lower():
        disp_ok = "cracked" not in screen_lower and "broken" not in screen_lower
        components.append({
            "component_name": "Display",
            "condition": "Good" if disp_ok else "Damaged",
            "recoverable": disp_ok,
            "estimated_value": 3200.0 if disp_ok else 600.0,
            "notes": "OLED/LCD touch panel assembly",
        })
        bat_ok = "poor" not in battery_lower and "dead" not in battery_lower
        components.append({
            "component_name": "Battery",
            "condition": "Good" if bat_ok else "Worn",
            "recoverable": bat_ok,
            "estimated_value": 1100.0 if bat_ok else 350.0,
            "notes": "Lithium-ion battery pack",
        })
        cam_ok = "liquid" not in damage_desc
        components.append({
            "component_name": "Camera Module",
            "condition": "Good" if cam_ok else "Fair",
            "recoverable": cam_ok,
            "estimated_value": 1800.0 if cam_ok else 500.0,
            "notes": "Multi-lens camera assembly",
        })
        mobo_ok = "powers on" in power_lower
        components.append({
            "component_name": "Motherboard",
            "condition": "Good" if mobo_ok else "Defective",
            "recoverable": mobo_ok,
            "estimated_value": 4000.0 if mobo_ok else 900.0,
            "notes": "SoC processor & logic board",
        })
        components.append({
            "component_name": "Housing",
            "condition": "Fair",
            "recoverable": True,
            "estimated_value": 800.0,
            "notes": "Chassis aluminum/glass frame",
        })

    elif "monitor" in dtype.lower() or "display" in dtype.lower():
        panel_ok = "broken" not in screen_lower and "cracked" not in screen_lower
        components.append({
            "component_name": "Panel",
            "condition": "Good" if panel_ok else "Cracked",
            "recoverable": panel_ok,
            "estimated_value": 3500.0 if panel_ok else 500.0,
            "notes": "IPS display matrix",
        })
        pwr_ok = "powers on" in power_lower
        components.append({
            "component_name": "Power Board",
            "condition": "Good" if pwr_ok else "Faulty",
            "recoverable": pwr_ok,
            "estimated_value": 1400.0 if pwr_ok else 300.0,
            "notes": "AC-DC converter unit",
        })
        components.append({
            "component_name": "Control Board",
            "condition": "Good",
            "recoverable": True,
            "estimated_value": 1100.0,
            "notes": "Scalar & input interface board",
        })
        components.append({
            "component_name": "Stand",
            "condition": "Good",
            "recoverable": True,
            "estimated_value": 900.0,
            "notes": "Ergonomic base stand assembly",
        })
    else:  # Tablets & other generic electronics
        disp_ok = "cracked" not in screen_lower and "broken" not in screen_lower
        components.append({
            "component_name": "Touch Display Assembly",
            "condition": "Good" if disp_ok else "Damaged",
            "recoverable": disp_ok,
            "estimated_value": 2000.0 if disp_ok else 400.0,
            "notes": "Digitizer glass & panel",
        })
        components.append({
            "component_name": "Core Electronics",
            "condition": "Fair",
            "recoverable": True,
            "estimated_value": 1600.0,
            "notes": "Reusable sub-assemblies",
        })
        components.append({
            "component_name": "Chassis & Frame",
            "condition": "Good",
            "recoverable": True,
            "estimated_value": 800.0,
            "notes": "Recyclable structural materials",
        })

    component_recovery_value = sum(c["estimated_value"] for c in components if c["recoverable"])

    # ---------------------------------------------------------
    # 6. REPAIR COST ESTIMATE (INR)
    # ---------------------------------------------------------
    if "laptop" in dtype.lower():
        base_repair = 3200.0
    elif "smart" in dtype.lower() or "phone" in dtype.lower():
        base_repair = 2400.0
    elif "monitor" in dtype.lower():
        base_repair = 1800.0
    else:
        base_repair = 2000.0

    parts_cost = 0.0
    if "cracked" in screen_lower or "broken" in screen_lower:
        parts_cost += 3400.0
    elif "minor" in screen_lower or "scratch" in screen_lower:
        parts_cost += 400.0

    if "poor" in battery_lower or "worn" in battery_lower or "%" in battery_lower:
        parts_cost += 1800.0

    if "no power" in power_lower:
        parts_cost += 2200.0

    if "liquid" in damage_desc:
        parts_cost += 3500.0

    repair_cost = round(base_repair + parts_cost, 2)

    # ---------------------------------------------------------
    # 7. ESTIMATED REFURBISHED VALUE (INR)
    # ---------------------------------------------------------
    if "laptop" in dtype.lower():
        base_refurb = 28000.0
        if "apple" in brand.lower():
            base_refurb = 38000.0
        elif "dell" in brand.lower() or "thinkpad" in model.lower() or "lenovo" in brand.lower():
            base_refurb = 26000.0
    elif "smart" in dtype.lower() or "phone" in dtype.lower():
        base_refurb = 22000.0
        if "apple" in brand.lower():
            base_refurb = 27000.0
        elif "samsung" in brand.lower():
            base_refurb = 24000.0
    elif "monitor" in dtype.lower():
        base_refurb = 8500.0
    else:
        base_refurb = 12000.0

    # Depreciation with age (10% per year, min 45% remaining)
    deprec = max(0.45, 1.0 - (age_years * 0.10))
    estimated_refurbished_value = round(base_refurb * deprec, 2)

    # ---------------------------------------------------------
    # 8. CIRCULAR RECOVERY SCORE (0 - 100)
    # ---------------------------------------------------------
    recoverable_ratio = component_recovery_value / max(1.0, sum(c["estimated_value"] for c in components))
    margin_ratio = max(0.0, min(1.0, (estimated_refurbished_value - repair_cost) / max(1.0, estimated_refurbished_value)))

    circular_score = (
        (repairability_score * 0.40) +
        (recoverable_ratio * 100.0 * 0.35) +
        ((35.0 if "good" in cond_lower else 20.0) / 35.0 * 100.0 * 0.15) +
        (margin_ratio * 100.0 * 0.10)
    )
    circular_recovery_score = round(max(5.0, min(100.0, circular_score)), 1)

    # ---------------------------------------------------------
    # 9. AVOIDED CO2 EMISSIONS (kg)
    # ---------------------------------------------------------
    if repairability_score >= 68.0:
        co2_factor = 12.8  # Refurbish extends life
    elif repairability_score >= 45.0:
        co2_factor = 7.4   # Component harvesting avoids new manufacture
    else:
        co2_factor = 2.5   # Raw material recycling
    
    co2_avoided_kg = round(weight_kg * co2_factor, 1)
    if co2_avoided_kg < 1.0:
        co2_avoided_kg = 1.5

    # ---------------------------------------------------------
    # 10. RECOMMENDATION DECISION
    # ---------------------------------------------------------
    reasons = []
    economic_margin = estimated_refurbished_value - repair_cost

    if power_status.lower() in ("powers on", "working"):
        reasons.append("Device powers on successfully")
    else:
        reasons.append(f"Power state ({power_status}) requires board-level repair")

    if repairability_score >= 70.0 and economic_margin > 4000.0:
        recommendation = "Refurbish"
        reasons.append(f"Repairability score ({repairability_score:.0f}/100) satisfies threshold (>=70)")
        reasons.append(f"Estimated repair cost (₹{repair_cost:,.0f}) is viable against refurbished value (₹{estimated_refurbished_value:,.0f})")
        reasons.append(f"High component recovery potential (₹{component_recovery_value:,.0f}) supports refurbishment")
        reasons.append("Refurbishment delivers highest circular life extension and CO2 savings")
    elif repairability_score >= 45.0 or component_recovery_value >= 3000.0:
        recommendation = "Parts Recovery"
        reasons.append(f"Repairability score ({repairability_score:.0f}/100) indicates high component value")
        reasons.append(f"Recoverable components (₹{component_recovery_value:,.0f}) exceed repair ROI margin")
        reasons.append("Harvesting sub-assemblies keeps critical micro-components in circulation")
    elif repairability_score >= 20.0:
        recommendation = "Recycle"
        reasons.append(f"Repairability score ({repairability_score:.0f}/100) below economic refurbishment limit")
        reasons.append("Structural degradation warrants controlled material extraction")
        reasons.append("Responsible recycling prevents toxic e-waste landfill contamination")
    else:
        recommendation = "Reject"
        reasons.append("Severe structural or hazardous damage precludes safe circular processing")

    technical_summary = (
        f"{dtype} ({brand} {model}) presented in {condition.lower()} condition with {power_status.lower()} power state. "
        f"Multi-factor analysis yields a technical condition score of {technical_condition_score:.0f}/100, "
        f"repairability score of {repairability_score:.0f}/100, and circular recovery score of {circular_recovery_score:.0f}/100. "
        f"Component recovery value estimated at ₹{component_recovery_value:,.0f} across "
        f"{len([c for c in components if c['recoverable']])} reusable sub-systems. Estimated avoided emissions: {co2_avoided_kg:.1f} kg CO2e. "
        f"Recommended pathway: {recommendation} (Confidence: {confidence_level})."
    )

    return {
        "technical_condition_score": technical_condition_score,
        "age_score": age_score,
        "repairability_score": repairability_score,
        "circular_recovery_score": circular_recovery_score,
        "repair_cost": repair_cost,
        "estimated_repair_cost": repair_cost,
        "component_recovery_value": round(component_recovery_value, 2),
        "estimated_refurbished_value": estimated_refurbished_value,
        "co2_avoided_kg": co2_avoided_kg,
        "environmental_benefit": co2_avoided_kg,
        "confidence_level": confidence_level,
        "recommendation": recommendation,
        "recommended_action": recommendation,
        "technical_summary": technical_summary,
        "reasons": reasons,
        "components": components,
    }

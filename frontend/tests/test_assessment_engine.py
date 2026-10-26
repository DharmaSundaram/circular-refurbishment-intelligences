import unittest
import math
from services.assessment_engine import evaluate_device_assessment


class AssessmentEngineTests(unittest.TestCase):
    def test_deterministic_calculation(self):
        device = {
            "type": "Laptop",
            "brand": "Dell",
            "model": "Latitude 5420",
            "condition": "Damaged",
            "power_status": "Powers on",
            "screen_condition": "Minor scratches",
            "battery_condition": "Poor · 42% capacity",
            "weight_kg": 1.4,
            "damage_description": "Worn battery and damaged keyboard. No liquid damage.",
            "age": 3,
        }

        res1 = evaluate_device_assessment(device)
        res2 = evaluate_device_assessment(device)

        self.assertEqual(res1["repairability_score"], res2["repairability_score"])
        self.assertEqual(res1["circular_recovery_score"], res2["circular_recovery_score"])
        self.assertEqual(res1["repair_cost"], res2["repair_cost"])
        self.assertEqual(res1["recommendation"], res2["recommendation"])

    def test_boundary_and_invalid_values(self):
        # Extremely damaged or empty attributes
        empty_dev = {
            "type": "",
            "brand": "",
            "model": "",
            "condition": "Not Working",
            "power_status": "No power",
            "screen_condition": "Broken",
            "battery_condition": "Dead",
            "weight_kg": 0.0,
            "damage_description": "Severe liquid damage and corrosion.",
            "age": "invalid_age_str",
        }

        res = evaluate_device_assessment(empty_dev)
        self.assertTrue(0 <= res["repairability_score"] <= 100)
        self.assertTrue(0 <= res["circular_recovery_score"] <= 100)
        self.assertFalse(math.isnan(res["repairability_score"]))
        self.assertFalse(math.isinf(res["repairability_score"]))
        self.assertIn(res["recommendation"], ["Refurbish", "Parts Recovery", "Recycle", "Reject"])

    def test_refurbish_recommendation(self):
        good_dev = {
            "type": "Laptop",
            "brand": "Dell",
            "model": "Precision 5560",
            "condition": "Good",
            "power_status": "Powers on",
            "screen_condition": "Good",
            "battery_condition": "Good",
            "weight_kg": 1.8,
            "age": 1,
        }
        res = evaluate_device_assessment(good_dev)
        self.assertGreaterEqual(res["repairability_score"], 70.0)
        self.assertEqual(res["recommendation"], "Refurbish")

    def test_co2_avoided_positive(self):
        dev = {"weight_kg": 2.5, "condition": "Good", "power_status": "Powers on"}
        res = evaluate_device_assessment(dev)
        self.assertGreater(res["co2_avoided_kg"], 0.0)


if __name__ == "__main__":
    unittest.main()

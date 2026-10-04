"""Unit tests for Authoritative Amazon FBA Prep Rules (Engineering Rule 5).

Rule 5: 'Where the channel publishes the requirement, retrieve it.
Don't let a model recall it from memory, and don't infer it from examples.'
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.rules.authoritative_rules import (
    get_required_suffocation_font_size,
    is_suffocation_warning_mandated,
    validate_fnsku_placement,
    validate_original_barcode_coverage,
    validate_expiry_visibility
)

class TestAuthoritativeRules(unittest.TestCase):
    def test_amazon_suffocation_font_size_tiers(self):
        """Validates exact Amazon FBA suffocation warning font size table."""
        # Tier 1: Total dimension >= 60 inches -> 24pt
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=30, bag_length_inches=32), 24)
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=25, bag_length_inches=35), 24)

        # Tier 2: 40 - 59 inches -> 18pt
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=20, bag_length_inches=25), 18)
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=15, bag_length_inches=25), 18)

        # Tier 3: 30 - 39 inches -> 14pt
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=12, bag_length_inches=20), 14)
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=10, bag_length_inches=20), 14)

        # Tier 4: < 30 inches -> 10pt
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=8, bag_length_inches=10), 10)
        self.assertEqual(get_required_suffocation_font_size(bag_width_inches=5, bag_length_inches=5), 10)

    def test_suffocation_warning_mandated_aperture(self):
        """Amazon rule: polybag opening >= 5 inches requires warning."""
        self.assertTrue(is_suffocation_warning_mandated(5.0))
        self.assertTrue(is_suffocation_warning_mandated(12.0))
        self.assertFalse(is_suffocation_warning_mandated(4.9))

    def test_fnsku_geometry_placement_rules(self):
        """Validates FNSKU planar placement and rejection of seams/curves."""
        # Planar surface -> Valid
        valid, msg = validate_fnsku_placement(surface_type="flat", crosses_seam=False, crosses_curve=False)
        self.assertTrue(valid)

        # Across seam -> Invalid
        valid, msg = validate_fnsku_placement(surface_type="flat", crosses_seam=True, crosses_curve=False)
        self.assertFalse(valid)
        self.assertIn("seam", msg.lower())

        # Across curve -> Invalid
        valid, msg = validate_fnsku_placement(surface_type="flat", crosses_seam=False, crosses_curve=True)
        self.assertFalse(valid)
        self.assertIn("curved", msg.lower())

    def test_original_barcode_coverage_rule(self):
        """Amazon rule: 100% of original barcode must be covered."""
        # 100% covered -> Valid
        valid, msg = validate_original_barcode_coverage(original_upc_visible_percent=0.0)
        self.assertTrue(valid)

        # Even 5% exposed -> Invalid
        valid, msg = validate_original_barcode_coverage(original_upc_visible_percent=5.0)
        self.assertFalse(valid)
        self.assertIn("partially exposed", msg.lower())

if __name__ == "__main__":
    unittest.main()

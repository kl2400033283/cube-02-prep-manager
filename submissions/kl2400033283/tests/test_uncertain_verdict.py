"""Unit tests for UNCERTAIN Verdict Handling (Engineering Rule 4).

Rule 4: 'Uncertain is a valid verdict. It isn't a low-confidence pass.
A model that declines to judge a bad photo is more credible to an operations person
than one that is confidently wrong. Build it as a first-class outcome.'
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.schemas.evidence import (
    PrepInspectionInput,
    OverallDecisionEnum,
    VerdictEnum
)
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
from submissions.kl2400033283.agent.db.database import TenantDatabase

class TestUncertainVerdict(unittest.TestCase):
    def setUp(self):
        self.test_db_path = Path(__file__).resolve().parent / "test_uncertain.db"
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = TenantDatabase(db_file=self.test_db_path)
        self.agent = PrepManagerAgent(db=self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_severe_glare_produces_uncertain_not_pass(self):
        """Proves that polybag specular glare triggers UNCERTAIN rather than guessing."""
        input_data = PrepInspectionInput(
            unit_id="UNIT-0881",
            org_id="org_demo_alpha",
            work_order_id="WO-3010",
            fba_shipment_id="FBA-100",
            sku="SKU-GLARE-TEST",
            asin="B0GLARE",
            fnsku="X00GLARE",
            wo_polybag=True,
            wo_suffocation_warning=True,
            test_mode_features={
                "original_barcode_covered": "uncertain",
                "suffocation_warning": "legible",
                "fnsku_label_placement": "flat",
                "polybag_present_sealed": "yes"
            }
        )

        record = self.agent.process_unit(input_data)
        self.assertEqual(record.outcome.decision, OverallDecisionEnum.UNCERTAIN)

        bc_check = next(c for c in record.checks if c.check_key == "original_barcode_covered")
        self.assertEqual(bc_check.verdict, VerdictEnum.UNCERTAIN)
        self.assertIn("glare", bc_check.detail.lower())

    def test_motion_blur_produces_uncertain(self):
        """Proves that conveyor motion blur triggers UNCERTAIN."""
        input_data = PrepInspectionInput(
            unit_id="UNIT-0882",
            org_id="org_demo_alpha",
            work_order_id="WO-3010",
            fba_shipment_id="FBA-100",
            sku="SKU-BLUR-TEST",
            asin="B0BLUR",
            fnsku="X00BLUR",
            wo_polybag=True,
            wo_suffocation_warning=True,
            test_mode_features={
                "original_barcode_covered": "yes",
                "suffocation_warning": "uncertain",
                "fnsku_label_placement": "flat",
                "polybag_present_sealed": "yes"
            }
        )

        record = self.agent.process_unit(input_data)
        self.assertEqual(record.outcome.decision, OverallDecisionEnum.UNCERTAIN)

        warn_check = next(c for c in record.checks if c.check_key == "suffocation_warning")
        self.assertEqual(warn_check.verdict, VerdictEnum.UNCERTAIN)

if __name__ == "__main__":
    unittest.main()

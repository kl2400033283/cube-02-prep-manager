"""Unit test verifying single-call batched model execution (Engineering Rule 2).

Rule 2: 'Make ONE call per unit carrying all checks, never one call per check.
At prep volumes that is the difference between a 90% gross margin and none.'
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.schemas.evidence import PrepInspectionInput
from submissions.kl2400033283.agent.vision.pipeline import BatchedPrepVisionPipeline
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
from submissions.kl2400033283.agent.db.database import TenantDatabase

class TestBatchCall(unittest.TestCase):
    def setUp(self):
        self.test_db_path = Path(__file__).resolve().parent / "test_batch.db"
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = TenantDatabase(db_file=self.test_db_path)
        self.vision = BatchedPrepVisionPipeline()
        self.agent = PrepManagerAgent(db=self.db, vision_pipeline=self.vision)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_single_model_call_per_unit_evaluates_all_six_checks(self):
        """Proves that a single inspection invocation calls the vision engine exactly once."""
        initial_calls = self.vision.call_counter

        input_data = PrepInspectionInput(
            unit_id="UNIT-0077",
            org_id="org_demo_alpha",
            work_order_id="WO-3001",
            fba_shipment_id="FBA-100",
            sku="SKU-PUZZLE",
            asin="B0DUMMY729",
            fnsku="X00DUMMY077",
            wo_polybag=True,
            wo_suffocation_warning=True,
            wo_expiry_date=True,
            wo_handling_marks="fragile"
        )

        record = self.agent.process_unit(input_data)
        calls_made = self.vision.call_counter - initial_calls

        # Assert exactly ONE call was made
        self.assertEqual(calls_made, 1, f"Expected exactly 1 batched model call, but {calls_made} calls were made!")

        # Assert that all 6 checks were evaluated in that single call
        check_keys = [c.check_key for c in record.checks]
        self.assertEqual(len(check_keys), 6)
        self.assertIn("polybag_present_sealed", check_keys)
        self.assertIn("suffocation_warning", check_keys)
        self.assertIn("fnsku_label_placement", check_keys)
        self.assertIn("original_barcode_covered", check_keys)
        self.assertIn("expiry_date", check_keys)
        self.assertIn("handling_marks", check_keys)

if __name__ == "__main__":
    unittest.main()

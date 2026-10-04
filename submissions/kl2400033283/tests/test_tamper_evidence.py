"""Unit tests for Cryptographic Evidence Verification & Overrides (Engineering Honesty Rules).

Honesty Rules:
- Say what you built: We have a content hash, verified across payload fields.
- Overrides are data: Never discard overrides silently; capture original, new, reason, operator.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.schemas.evidence import (
    PrepInspectionInput,
    VerdictEnum,
    OverallDecisionEnum
)
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
from submissions.kl2400033283.agent.db.database import TenantDatabase

class TestTamperEvidenceAndOverrides(unittest.TestCase):
    def setUp(self):
        self.test_db_path = Path(__file__).resolve().parent / "test_tamper.db"
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = TenantDatabase(db_file=self.test_db_path)
        self.agent = PrepManagerAgent(db=self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_canonical_content_hash_integrity_and_tamper_detection(self):
        """Proves that content hash verifies valid records and fails when modified."""
        input_data = PrepInspectionInput(
            unit_id="UNIT-0551",
            org_id="org_demo_alpha",
            work_order_id="WO-3020",
            fba_shipment_id="FBA-100",
            sku="SKU-TAMPER-TEST",
            asin="B0TAMP1",
            fnsku="X00TAMP1"
        )
        record = self.agent.process_unit(input_data)
        self.assertTrue(record.verify_integrity(), "Fresh record must pass cryptographic integrity check")

        # Simulate tampering with a check verdict
        tampered_record = record.model_copy(deep=True)
        tampered_record.checks[0].verdict = VerdictEnum.FAIL
        self.assertFalse(tampered_record.verify_integrity(), "Tampered verdict must invalidate SHA-256 content hash!")

        # Simulate tampering with outcome decision
        tampered_record_2 = record.model_copy(deep=True)
        tampered_record_2.outcome.decision = OverallDecisionEnum.FAIL
        self.assertFalse(tampered_record_2.verify_integrity(), "Tampered decision must invalidate content hash!")

    def test_override_is_appended_without_wiping_audit_trail(self):
        """Proves that human overrides append an audit log without discarding original judgments."""
        input_data = PrepInspectionInput(
            unit_id="UNIT-0552",
            org_id="org_demo_alpha",
            work_order_id="WO-3020",
            fba_shipment_id="FBA-100",
            sku="SKU-OVERRIDE-TEST",
            asin="B0OVER1",
            fnsku="X00OVER1",
            test_mode_features={
                "original_barcode_covered": "no"  # Fails initially
            }
        )
        record = self.agent.process_unit(input_data)
        self.assertEqual(record.outcome.decision, OverallDecisionEnum.FAIL)

        # Apply human override
        updated = self.agent.apply_override(
            org_id="org_demo_alpha",
            record_id=record.record_id,
            check_key="original_barcode_covered",
            new_verdict_str="PASS",
            reason="MANUALLY_COVERED_WITH_BLACKOUT_TAPE",
            operator_id="op_elena"
        )

        # Assert audit trail properties
        self.assertEqual(len(updated.overrides), 1, "Must contain exactly 1 override log entry")
        override_entry = updated.overrides[0]
        self.assertEqual(override_entry.check_key, "original_barcode_covered")
        self.assertEqual(override_entry.original_verdict, VerdictEnum.FAIL)
        self.assertEqual(override_entry.new_verdict, VerdictEnum.PASS)
        self.assertEqual(override_entry.reason, "MANUALLY_COVERED_WITH_BLACKOUT_TAPE")
        self.assertEqual(override_entry.operator_id, "op_elena")

        # New content hash is calculated and verified
        self.assertTrue(updated.verify_integrity(), "Updated record with override must retain valid cryptographic hash")

    def test_override_requires_mandatory_reason_code(self):
        """Proves that overrides without an explicit justification reason are rejected."""
        input_data = PrepInspectionInput(
            unit_id="UNIT-0553",
            org_id="org_demo_alpha",
            work_order_id="WO-3020",
            fba_shipment_id="FBA-100",
            sku="SKU-OVERRIDE-TEST",
            asin="B0OVER2",
            fnsku="X00OVER2"
        )
        record = self.agent.process_unit(input_data)

        with self.assertRaises(ValueError):
            self.agent.apply_override(
                org_id="org_demo_alpha",
                record_id=record.record_id,
                check_key="suffocation_warning",
                new_verdict_str="PASS",
                reason="",  # Empty reason rejected!
                operator_id="op_elena"
            )

if __name__ == "__main__":
    unittest.main()

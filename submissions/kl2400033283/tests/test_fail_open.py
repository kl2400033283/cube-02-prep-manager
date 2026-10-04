"""Unit tests for Fail-Open Circuit Breaker Behavior (Engineering Rule 3).

Rule 3: 'A model error or timeout still saves the capture and still produces a record,
marked pending. Nothing blocks the operator. Anything that makes a warehouse line
wait gets worked around within a day of deployment.'
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.schemas.evidence import (
    PrepInspectionInput,
    OverallDecisionEnum,
    RecordStatusEnum,
    VerdictEnum
)
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
from submissions.kl2400033283.agent.db.database import TenantDatabase

class TestFailOpen(unittest.TestCase):
    def setUp(self):
        self.test_db_path = Path(__file__).resolve().parent / "test_failopen.db"
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = TenantDatabase(db_file=self.test_db_path)
        self.agent = PrepManagerAgent(db=self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_model_exception_triggers_fail_open(self):
        """Proves that unhandled model error saves record as pending without raising unhandled exception."""
        input_data = PrepInspectionInput(
            unit_id="UNIT-0991",
            org_id="org_demo_alpha",
            work_order_id="WO-3005",
            fba_shipment_id="FBA-100",
            sku="SKU-FAIL-TEST",
            asin="B0FAIL1",
            fnsku="X00FAIL1"
        )

        # Force simulated service crash (HTTP 503)
        record = self.agent.process_unit(input_data, force_simulate_failure=True)

        # Assertions
        self.assertEqual(record.status, RecordStatusEnum.FAILED_OPEN)
        self.assertEqual(record.outcome.decision, OverallDecisionEnum.PENDING_REVIEW)
        self.assertIn("SYSTEM_FAIL_OPEN", record.outcome.summary)
        self.assertTrue(record.verify_integrity(), "Content hash must be valid on fail-open records")

        # Verify persisted in database
        saved = self.db.get_evidence_record("org_demo_alpha", record.record_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.outcome.decision, OverallDecisionEnum.PENDING_REVIEW)

    def test_model_timeout_triggers_fail_open(self):
        """Proves that latency exceeding warehouse budget triggers instant fail-open."""
        input_data = PrepInspectionInput(
            unit_id="UNIT-0992",
            org_id="org_demo_alpha",
            work_order_id="WO-3005",
            fba_shipment_id="FBA-100",
            sku="SKU-TIMEOUT-TEST",
            asin="B0TIMEOUT",
            fnsku="X00TIMEOUT"
        )

        # Force simulated latency timeout
        record = self.agent.process_unit(input_data, force_simulate_timeout=True)

        self.assertEqual(record.status, RecordStatusEnum.FAILED_OPEN)
        self.assertEqual(record.outcome.decision, OverallDecisionEnum.PENDING_REVIEW)
        self.assertIn("CircuitBreakerTimeoutError", record.outcome.summary)

if __name__ == "__main__":
    unittest.main()

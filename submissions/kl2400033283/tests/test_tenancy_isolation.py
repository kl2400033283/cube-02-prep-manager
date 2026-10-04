"""Automated Unit & Security Tests for Tenancy Isolation (Engineering Rule 1).

Enforces:
- Organization-scoped tables with forced tenant filtering
- Tenant A sees 0 rows from Tenant B
- Image assets cannot be accessed by guessing paths from another tenant
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.schemas.evidence import (
    PrepInspectionInput,
    EvidenceRecord
)
from submissions.kl2400033283.agent.db.database import TenantDatabase, TenantAccessDeniedError
from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent

class TestTenancyIsolation(unittest.TestCase):
    def setUp(self):
        # Create a fresh isolated test database in test fixtures
        self.test_db_path = Path(__file__).resolve().parent / "test_tenancy.db"
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = TenantDatabase(db_file=self.test_db_path)
        self.agent = PrepManagerAgent(db=self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_zero_cross_tenant_record_leakage(self):
        """Proves Tenant A cannot see records owned by Tenant B."""
        # 1. Tenant Alpha creates a unit
        input_alpha = PrepInspectionInput(
            unit_id="UNIT-0101",
            org_id="org_demo_alpha",
            work_order_id="WO-ALPHA-1",
            fba_shipment_id="FBA-ALPHA",
            sku="SKU-ALPHA-SECRET",
            asin="B0ALPHA1",
            fnsku="X00ALPHA1"
        )
        rec_alpha = self.agent.process_unit(input_alpha)

        # 2. Tenant Bravo creates a unit
        input_bravo = PrepInspectionInput(
            unit_id="UNIT-0202",
            org_id="org_demo_bravo",
            work_order_id="WO-BRAVO-1",
            fba_shipment_id="FBA-BRAVO",
            sku="SKU-BRAVO-SECRET",
            asin="B0BRAVO1",
            fnsku="X00BRAVO1"
        )
        rec_bravo = self.agent.process_unit(input_bravo)

        # 3. Assert Tenant Bravo querying Tenant Alpha's record returns None
        leak_query = self.db.get_evidence_record(org_id="org_demo_bravo", record_id=rec_alpha.record_id)
        self.assertIsNone(leak_query, "Tenant Bravo was able to query Tenant Alpha's record!")

        # 4. Assert Tenant Alpha querying Tenant Bravo's record returns None
        leak_query_rev = self.db.get_evidence_record(org_id="org_demo_alpha", record_id=rec_bravo.record_id)
        self.assertIsNone(leak_query_rev, "Tenant Alpha was able to query Tenant Bravo's record!")

        # 5. Assert tenant list_records is strictly isolated
        alpha_records = self.db.list_records(org_id="org_demo_alpha")
        self.assertEqual(len(alpha_records), 1)
        self.assertEqual(alpha_records[0]["unit_id"], "UNIT-0101")

        bravo_records = self.db.list_records(org_id="org_demo_bravo")
        self.assertEqual(len(bravo_records), 1)
        self.assertEqual(bravo_records[0]["unit_id"], "UNIT-0202")

        # 6. Execute formal automated zero leakage assertion
        is_safe = self.db.assert_zero_cross_tenant_leakage("org_demo_alpha", "org_demo_bravo")
        self.assertTrue(is_safe, "Cross-tenant leakage detected between Alpha and Bravo!")

    def test_cross_tenant_image_access_prevention(self):
        """Proves Tenant Bravo cannot view Tenant Alpha's image by guessing path."""
        # Tenant Alpha creates a unit with image
        input_alpha = PrepInspectionInput(
            unit_id="UNIT-0103",
            org_id="org_demo_alpha",
            work_order_id="WO-ALPHA-2",
            fba_shipment_id="FBA-ALPHA",
            sku="SKU-PROT-1",
            asin="B0ALPHA2",
            fnsku="X00ALPHA2",
            image_paths=["fixtures/prep/UNIT-0103_front.jpg"]
        )
        rec = self.agent.process_unit(input_alpha)
        alpha_img_path = rec.images[0].file_path

        # Generate legitimate token for Alpha
        alpha_token = self.db.generate_image_token("org_demo_alpha", alpha_img_path)
        self.assertTrue(self.db.verify_image_access("org_demo_alpha", alpha_img_path, alpha_token))

        # Tenant Bravo attempts to access Alpha's image using Alpha's token
        self.assertFalse(
            self.db.verify_image_access("org_demo_bravo", alpha_img_path, alpha_token),
            "Tenant Bravo successfully bypassed image tenant token verification!"
        )

        # Tenant Bravo attempts to access Alpha's image using a token forged under Bravo's org
        bravo_forged_token = self.db.generate_image_token("org_demo_bravo", alpha_img_path)
        self.assertFalse(
            self.db.verify_image_access("org_demo_bravo", alpha_img_path, bravo_forged_token),
            "Tenant Bravo was able to access Tenant Alpha's image using forged org token!"
        )

    def test_unauthorized_organization_rejection(self):
        """Proves that unapproved organizations are blocked upfront."""
        input_rogue = PrepInspectionInput(
            unit_id="UNIT-9999",
            org_id="org_rogue_intruder",
            work_order_id="WO-ROGUE",
            fba_shipment_id="FBA-ROGUE",
            sku="SKU-ROGUE",
            asin="B0ROGUE",
            fnsku="X00ROGUE"
        )
        with self.assertRaises(TenantAccessDeniedError):
            self.agent.process_unit(input_rogue)

if __name__ == "__main__":
    unittest.main()

"""End-to-End Integration Tests for Prep Manager REST API and Pipeline."""

import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.api import app

class TestEndToEndAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_api_health_endpoint(self):
        """Verifies health check and version metadata."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["agent"], "Prep Manager (Agent 02)")

    def test_api_inspect_and_retrieve_flow(self):
        """Tests unit inspection, storage, retrieval, and cryptographic verification via HTTP."""
        payload = {
            "unit_id": "UNIT-0777",
            "org_id": "org_demo_alpha",
            "work_order_id": "WO-API-1",
            "fba_shipment_id": "FBA-API",
            "sku": "SKU-E2E-TEST",
            "asin": "B0E2E777",
            "fnsku": "X00E2E777",
            "operator_id": "op_test",
            "wo_polybag": True,
            "wo_suffocation_warning": True,
            "wo_expiry_date": True,
            "test_mode_features": {
                "polybag_present_sealed": "yes",
                "suffocation_warning": "legible",
                "fnsku_label_placement": "flat",
                "original_barcode_covered": "yes",
                "expiry_date": "legible",
                "handling_marks": "all_present"
            }
        }

        # 1. Post inspection
        resp = self.client.post("/api/inspect", json=payload, headers={"x-org-id": "org_demo_alpha"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["integrity_verified"])
        rec = data["record"]
        self.assertEqual(rec["outcome"]["decision"], "PASS")

        # 2. Retrieve record via GET
        get_resp = self.client.get(f"/api/records/{rec['record_id']}", headers={"x-org-id": "org_demo_alpha"})
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.json()
        self.assertTrue(get_data["integrity_verified"])
        self.assertEqual(get_data["record"]["subject"]["unit_id"], "UNIT-0777")

        # 3. Assert Tenant Bravo cannot retrieve this record (404 Not Found)
        cross_resp = self.client.get(f"/api/records/{rec['record_id']}", headers={"x-org-id": "org_demo_bravo"})
        self.assertEqual(cross_resp.status_code, 404)

    def test_api_tenancy_leak_audit_endpoint(self):
        """Verifies the automated tenant isolation endpoint."""
        resp = self.client.get("/api/tenancy/test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["isolation_verified"])
        self.assertEqual(data["cross_tenant_leakage_rows"], 0)

if __name__ == "__main__":
    unittest.main()

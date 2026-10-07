"""Round 3 pod contract: handle()/POST /run outputs validate against the vendored CUBE v1.0 schemas."""

import copy
import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from _helpers import make_agent, temp_db
from submissions.kl2400033283.agent import api as api_module
from submissions.kl2400033283.agent import pod_adapter
from submissions.kl2400033283.agent.contract_validation import errors

SAMPLE = Path(__file__).resolve().parent.parent / "contract" / "round3" / "sample" / "agent-input.prep.json"


def example(**subject):
    req = json.loads(SAMPLE.read_text(encoding="utf-8"))
    req["subject"].update(subject)
    return req


class TestPodAdapter(unittest.TestCase):
    def setUp(self):
        self.agent = make_agent()

    def test_example_input_is_valid_and_output_validates(self):
        req = example()
        self.assertEqual(errors("agent-input", req), [])
        out = pod_adapter.handle(req, self.agent)
        self.assertEqual(errors("agent-output", out), [])
        ev = out["evidence"]
        self.assertTrue(ev["record_id"].startswith("PRP-"))
        self.assertEqual(ev["content_hash"], pod_adapter.content_hash(ev))
        self.assertEqual(out["verdict"], ev["decision"]["verdict"])
        self.assertEqual(ev["subject"]["org_id"], "org_demo_alpha")
        self.assertIn("rule_source", ev["payload"])
        self.assertIsNone(ev["payload"]["measurements"])
        self.assertEqual(ev["model"]["name"], "rules")  # no capture: operator record judged by rules, said plainly
        keys = {c["check_key"] for c in ev["checks"]}
        self.assertTrue(keys <= {"polybag_sealed", "suffocation_warning", "fnsku_label_placement",
                                 "original_barcode_covered", "expiry_legible", "handling_marks", "receiving_cleared"})
        self.assertEqual(ev["upstream_refs"], ["RCV-0014"])

    def test_idempotent_same_request_same_record(self):
        a = pod_adapter.handle(example(), self.agent)
        b = pod_adapter.handle(example(), self.agent)
        self.assertEqual(a["evidence"]["record_id"], b["evidence"]["record_id"])
        self.assertEqual(a, b)

    def test_foreign_or_unknown_tenant_is_lookup_error(self):
        with self.assertRaises(LookupError):
            pod_adapter.handle(example(org_id="org_demo_bravo"), self.agent)  # UNIT-0014 belongs to alpha
        with self.assertRaises(LookupError):
            pod_adapter.handle(example(org_id="org_evil"), self.agent)

    def test_receiving_reject_blocks_release(self):
        req = example()
        req["request_id"] += "-rej"
        rcv = req["previous_evidence"][-1]
        rcv["decision"]["verdict"], rcv["decision"]["outcome"] = "FAIL", "reject"
        out = pod_adapter.handle(req, self.agent)
        self.assertEqual(errors("agent-output", out), [])
        self.assertEqual(out["verdict"], "FAIL")
        gate = next(c for c in out["evidence"]["checks"] if c["check_key"] == "receiving_cleared")
        self.assertEqual(gate["evidence_refs"], ["RCV-0014"])

    def test_workflow_override_of_receiving_is_respected(self):
        req = example()
        req["request_id"] += "-ovr"
        rcv = req["previous_evidence"][-1]
        rcv["decision"]["verdict"] = "UNCERTAIN"
        req["context"] = {"overrides": [{"supersedes": {"record_id": rcv["record_id"]}, "new_verdict": "PASS"}]}
        out = pod_adapter.handle(req, self.agent)
        gate = next(c for c in out["evidence"]["checks"] if c["check_key"] == "receiving_cleared")
        self.assertEqual(gate["verdict"], "PASS")

    def test_image_input_runs_vision_and_uncertain_has_reason(self):
        req = example()
        req["request_id"] += "-img"
        req["inputs"] = [{"ref": "scenario:fnsku-on-seam", "kind": "image"}]
        out = pod_adapter.handle(req, self.agent)
        self.assertEqual(errors("agent-output", out), [])
        ev = out["evidence"]
        self.assertEqual(len(ev["inputs"][0]["sha256"]), 64)
        self.assertNotEqual(ev["model"]["name"], "rules")
        for c in ev["checks"]:
            if c["verdict"] == "UNCERTAIN":
                self.assertIn("uncertain_reason", c)

    def test_path_traversal_and_hash_mismatch_refused(self):
        req = example()
        req["request_id"] += "-trav"
        req["inputs"] = [{"ref": "../../../../Windows/win.ini", "kind": "image"},
                         {"ref": "scenario:correct-prep", "kind": "image", "sha256": "0" * 64}]
        out = pod_adapter.handle(req, self.agent)
        self.assertEqual(errors("agent-output", out), [])
        self.assertIn("not found", out["evidence"]["decision"]["reason"])
        self.assertIn("mismatch", out["evidence"]["decision"]["reason"])

    def test_pending_output_validates(self):
        out = pod_adapter.pending_output(example(), "agent_exception", "boom")
        self.assertEqual(errors("agent-output", out), [])
        self.assertEqual((out["status"], out["verdict"]), ("pending", "UNCERTAIN"))


class TestPodHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = temp_db()
        api_module.db = db
        api_module.agent = make_agent(db=db)
        cls.c = TestClient(api_module.app)

    def test_health(self):
        h = self.c.get("/health").json()
        self.assertEqual((h["status"], h["stage"], h["contract_version"]), ("ok", "prep", "1.0"))

    def test_run_statuses(self):
        r = self.c.post("/run", json=example())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(errors("agent-output", r.json()), [])
        wrong = copy.deepcopy(example())
        wrong["stage"] = "pack"
        self.assertEqual(self.c.post("/run", json=wrong).status_code, 422)
        self.assertEqual(self.c.post("/run", json={"hello": 1}).status_code, 422)
        self.assertEqual(self.c.post("/run", json=example(org_id="org_demo_bravo")).status_code, 404)


if __name__ == "__main__":
    unittest.main()

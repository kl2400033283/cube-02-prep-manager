"""End-to-end: every challenge test scenario through the full agent loop, plus fail-open and budgets."""

import time
import unittest

from _helpers import make_agent, scenario_input
from submissions.kl2400033283.agent.sim.scenarios import SCENARIOS
from submissions.kl2400033283.agent.vision.providers.claude_provider import ClaudeVisionProvider


class TestScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = make_agent()

    def test_all_challenge_scenarios_reach_expected_decision(self):
        for s in SCENARIOS:
            with self.subTest(s.scenario_id):
                rec = self.agent.inspect(scenario_input(s.scenario_id))
                self.assertEqual(rec.outcome.decision.value, s.expected, rec.outcome.summary)
                self.assertTrue(rec.verify_integrity())

    def test_specific_reasons(self):
        expect = {
            "fnsku-on-seam": ("fnsku_label_placement", "FNSKU_ON_SEAM"),
            "fnsku-on-curve": ("fnsku_label_placement", "FNSKU_ON_CURVE"),
            "barcode-visible": ("original_barcode_covered", "ORIGINAL_BARCODE_EXPOSED"),
            "obscured-warning": ("suffocation_warning", "WARNING_OBSCURED"),
            "missing-warning": ("suffocation_warning", "WARNING_MISSING"),
            "covered-expiry": ("expiry_date", "EXPIRY_COVERED"),
            "missing-handling-mark": ("handling_marks", "HANDLING_MARK_MISSING"),
            "undersized-warning": ("suffocation_warning", "WARNING_PRINT_TOO_SMALL"),
            "work-order-gap": ("polybag_present_sealed", "POLYBAG_MISSING"),
        }
        for sid, (key, code) in expect.items():
            with self.subTest(sid):
                rec = self.agent.inspect(scenario_input(sid))
                c = next(c for c in rec.checks if c.check_key == key)
                self.assertEqual(c.reason_code, code)
                self.assertEqual(c.verdict.value, "FAIL")
                self.assertTrue(c.regions or code in ("WARNING_MISSING", "POLYBAG_MISSING", "FNSKU_MISSING"),
                                "FAIL verdicts must point at evidence on the image")

    def test_every_record_has_a_full_trace(self):
        rec = self.agent.inspect(scenario_input("correct-prep"))
        steps = [s.step for s in rec.trace]
        for needed in ("RESOLVE_REQUIREMENTS", "INGEST_IMAGES", "QUALITY_GATE", "ROUTE", "PERCEIVE",
                       "VERIFY_AND_JUDGE", "DECIDE", "SEAL_EVIDENCE"):
            self.assertIn(needed, steps)

    def test_reinspection_never_overwrites_evidence(self):
        a = self.agent.inspect(scenario_input("correct-prep"))
        b = self.agent.inspect(scenario_input("correct-prep"))
        self.assertNotEqual(a.record_id, b.record_id)
        self.assertIsNotNone(self.agent.db.get_evidence_record("org_demo_alpha", a.record_id))


class TestFailOpenAndBudgets(unittest.TestCase):
    def test_timeout_fails_open_in_bounded_time(self):
        agent = make_agent(timeout_ms=300)
        t = time.perf_counter()
        rec = agent.inspect(scenario_input("correct-prep"), fault="timeout")
        elapsed = (time.perf_counter() - t) * 1000
        self.assertEqual(rec.outcome.decision.value, "PENDING_REVIEW")
        self.assertEqual(rec.status.value, "failed_open")
        self.assertTrue(all(c.verdict.value == "UNCERTAIN" and c.reason_code == "SYSTEM_TIMEOUT" for c in rec.checks))
        self.assertLess(elapsed, 300 + 700, "fail-open must not wait for the hung call")
        self.assertTrue(rec.images, "capture must be preserved")
        self.assertTrue(rec.verify_integrity())

    def test_provider_outage_fails_open(self):
        rec = make_agent().inspect(scenario_input("correct-prep"), fault="provider_error")
        self.assertEqual(rec.outcome.decision.value, "PENDING_REVIEW")
        self.assertEqual(rec.outcome.dispatch.value, "AMBER_REVIEW")

    def test_unusable_frame_skips_model_call(self):
        calls = []
        fake = ClaudeVisionProvider(api_key="test", transport=lambda p: calls.append(p) or {})
        agent = make_agent(claude=fake, mode="claude", allow_paid=True)
        rec = agent.inspect(scenario_input("blurred-capture"))
        self.assertEqual(calls, [], "no paid call on an unusable frame")
        self.assertEqual(rec.outcome.decision.value, "UNCERTAIN")
        self.assertIn("recapture", rec.trace[[s.step for s in rec.trace].index("ROUTE")].detail.lower())

    def test_at_most_one_model_call_per_unit(self):
        calls = []

        def transport(payload):
            calls.append(payload)
            return {"content": [], "usage": {"input_tokens": 1000, "output_tokens": 200}}
        agent = make_agent(claude=ClaudeVisionProvider(api_key="test", transport=transport), mode="claude", allow_paid=True)
        agent.inspect(scenario_input("correct-prep"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["tools"]), 1)

    def test_uncalibrated_photo_without_vision_model_never_passes_or_fails(self):
        # Real-world photo + no Claude key: station CV is out of its validated domain.
        # It may point at things (regions kept) but must not decide them.
        for sid in ("fnsku-on-seam", "correct-prep", "work-order-gap"):
            with self.subTest(sid):
                rec = make_agent().inspect(scenario_input(sid, station_calibrated=False))
                decided = [c for c in rec.checks if c.verdict.value in ("PASS", "FAIL")]
                self.assertEqual(decided, [])
                self.assertEqual(rec.outcome.decision.value, "UNCERTAIN")
                self.assertIn("OUT OF DOMAIN", rec.perception.routing_reason)

    def test_station_cv_has_zero_model_cost(self):
        rec = make_agent().inspect(scenario_input("sealed-polybag"))
        self.assertEqual(rec.perception.model_calls, 0)
        self.assertEqual(rec.perception.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()

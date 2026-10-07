"""Regression tests for the 6 Oct 2026 repo review (Repo 2: Prep Manager)."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageFilter

from _helpers import make_agent, scenario_input
from submissions.kl2400033283.agent.core import rules_engine
from submissions.kl2400033283.agent.core.prep_agent import _safe_message
from submissions.kl2400033283.agent.rules.authoritative_rules import (
    RULES, is_valid_expiry_format, resolve_requirements, rule_source,
)
from submissions.kl2400033283.agent.sim.scenarios import BY_ID
from submissions.kl2400033283.agent.vision.observations import CheckObservation, indeterminate
from submissions.kl2400033283.agent.vision.providers.claude_provider import ClaudeVisionProvider
from submissions.kl2400033283.agent.vision.providers.cv_provider import StationCVProvider, fuse_views
from submissions.kl2400033283.agent.vision.providers.ollama_provider import OllamaVisionProvider
from submissions.kl2400033283.agent.vision.quality import assess_quality, load_image

ORDER = StationCVProvider._SEVERITY


def ob(k, state, signal=0.9):
    return CheckObservation(check_key=k, state=state, signal=signal)


class TestFusion(unittest.TestCase):
    def test_one_view_without_bag_does_not_fail_a_sealed_unit(self):
        k = "polybag_present_sealed"
        f = fuse_views(k, [ob(k, "SEALED"), ob(k, "ABSENT")], ORDER[k])
        self.assertEqual(f.state, "INDETERMINATE")
        self.assertTrue(f.measurements["view_conflict"])

    def test_label_present_in_any_view_counts(self):
        k = "fnsku_label_placement"
        self.assertEqual(fuse_views(k, [ob(k, "ABSENT"), ob(k, "FLAT")], ORDER[k]).state, "FLAT")

    def test_absence_needs_every_view(self):
        k = "suffocation_warning"
        self.assertEqual(fuse_views(k, [ob(k, "ABSENT"), indeterminate(k, "x")], ORDER[k]).state, "INDETERMINATE")
        self.assertEqual(fuse_views(k, [ob(k, "ABSENT"), ob(k, "ABSENT")], ORDER[k]).state, "ABSENT")

    def test_defect_in_any_view_wins(self):
        k = "fnsku_label_placement"
        self.assertEqual(fuse_views(k, [ob(k, "FLAT"), ob(k, "ON_SEAM")], ORDER[k]).state, "ON_SEAM")


class TestRules(unittest.TestCase):
    def test_impossible_dates_rejected(self):
        self.assertFalse(is_valid_expiry_format("02-30-2027"))
        self.assertFalse(is_valid_expiry_format("13-2027"))
        self.assertTrue(is_valid_expiry_format("02-28-2027"))
        self.assertTrue(is_valid_expiry_format("03-2027"))

    def _fnsku(self, read, want):
        obs = CheckObservation(check_key="fnsku_label_placement", state="FLAT", signal=0.9,
                               measurements={"fnsku_text": read})
        return rules_engine._verdict_for("fnsku_label_placement", obs, {"expected_fnsku": want})

    def test_fnsku_exact_match_only(self):
        self.assertEqual(self._fnsku("X0088526L2", "X0088526L2")[0].value, "PASS")
        self.assertEqual(self._fnsku("X00BBSZG12", "X0088526L2")[1], "FNSKU_CONFUSABLE_OCR")  # never PASS
        self.assertEqual(self._fnsku("X00ABCDEF9", "X0088526L2")[0].value, "FAIL")

    def test_liquid_and_glass_need_attestation(self):
        for cat, rid in (("liquid", "FBA-LQ-01"), ("fragile_glass", "FBA-GL-01")):
            plan = resolve_requirements(cat, False, False, False, [], None, None, None, None)
            self.assertIn(rid, [a.rule_id for a in plan.attestations])

    def test_work_order_gap_is_amber_not_green(self):
        agent = make_agent()
        rec = agent.inspect(scenario_input("correct-prep", category="apparel_textile", wo_polybag=False))
        if rec.outcome.decision.value == "PASS":
            self.assertEqual(rec.outcome.dispatch.value, "AMBER_REVIEW")

    def test_every_amazon_rule_has_a_source_url(self):
        for r in RULES.values():
            if r.source == "amazon_fba":
                self.assertTrue(r.source_url and r.source_url.startswith("https://"), r.rule_id)
        self.assertEqual(rule_source(["FBA-EX-01"])[0]["retrieved_on"], "2026-10-07")


class TestProviders(unittest.TestCase):
    def test_truncated_claude_answer_is_not_trusted(self):
        obs = ClaudeVisionProvider(api_key="k").parse_response({"stop_reason": "max_tokens", "content": [
            {"type": "tool_use", "name": "report_observations", "input": {}}]})
        self.assertTrue(all(o.state == "INDETERMINATE" for o in obs.checks.values()))

    def test_prompts_do_not_leak_expected_fnsku(self):
        img = load_image(BY_ID["correct-prep"].ensure_rendered())
        req = ClaudeVisionProvider(api_key="k").build_request([img], {"category": "general", "fnsku": "X00SECRET1"})
        self.assertNotIn("X00SECRET1", str(req["messages"]))

    def test_ollama_requires_the_configured_model_and_can_be_disabled(self):
        self.assertFalse(OllamaVisionProvider(disabled=True).available)
        self.assertFalse(OllamaVisionProvider(base_url="http://127.0.0.1:9").available)  # nothing listening


class TestRobustness(unittest.TestCase):
    def test_native_resolution_blur_is_caught(self):
        src = Image.open(BY_ID["correct-prep"].ensure_rendered()).convert("RGB")
        big = src.resize((src.width * 3, src.height * 3), Image.LANCZOS).filter(ImageFilter.GaussianBlur(5))
        p = Path(tempfile.mkdtemp()) / "big_blur.jpg"
        big.save(p, quality=95)
        q = assess_quality(load_image(p))
        self.assertIn("BLUR", q.issues)
        self.assertTrue(assess_quality(load_image(BY_ID["correct-prep"].ensure_rendered())).usable)

    def test_fail_open_messages_do_not_leak_paths(self):
        msg = _safe_message(FileNotFoundError(r"No such file: 'C:\Users\someone\secret\data_store\uploads\a.jpg'"))
        self.assertNotIn("someone", msg)
        self.assertIn("a.jpg", msg)
        msg = _safe_message(OSError("cannot open /srv/app/data/x.png"))
        self.assertNotIn("/srv/app", msg)

    def test_old_database_gets_new_columns_and_uploads_work(self):
        import sqlite3
        from submissions.kl2400033283.agent.db.database import TenantDatabase
        d = Path(tempfile.mkdtemp())
        conn = sqlite3.connect(str(d / "old.db"))
        conn.execute("CREATE TABLE assets (org_id TEXT NOT NULL, asset_id TEXT NOT NULL, sha256 TEXT NOT NULL,"
                     " storage_path TEXT NOT NULL, content_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,"
                     " created_at TEXT NOT NULL, PRIMARY KEY (org_id, asset_id))")
        conn.commit()
        conn.close()
        db = TenantDatabase(d / "old.db", d / "uploads")
        aid = db.save_asset("org_demo_alpha", b"x" * 200, "ab" * 32, "image/jpeg", ".jpg", original_sha256="cd" * 32)
        self.assertEqual(db.get_asset("org_demo_alpha", aid)["original_sha256"], "cd" * 32)

    def test_tenants_get_separate_perception_pools(self):
        from submissions.kl2400033283.agent.core.prep_agent import _pool_for
        self.assertIsNot(_pool_for("org_demo_alpha"), _pool_for("org_demo_bravo"))


if __name__ == "__main__":
    unittest.main()

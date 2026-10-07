"""Requirement resolution (Rule 5) and the deterministic rules engine."""

import unittest

from _helpers import *  # noqa: F401,F403  (sets sys.path)
from submissions.kl2400033283.agent.core import rules_engine
from submissions.kl2400033283.agent.rules.authoritative_rules import (
    RULES, is_valid_expiry_format, required_warning_font_pt, resolve_requirements,
)
from submissions.kl2400033283.agent.schemas.evidence import ImageQuality, Region, VerdictEnum
from submissions.kl2400033283.agent.vision.observations import CheckObservation, UnitObservation


def plan(category="general", **kw):
    args = dict(wo_polybag=False, wo_suffocation_warning=False, wo_expiry_date=False, wo_handling_marks=[],
                bag_length_in=None, bag_width_in=None, bag_opening_in=None, polybag_spec_mil=None)
    args.update(kw)
    return resolve_requirements(category, **args)


GOOD_Q = [ImageQuality(sharpness=100, glare_pct=0.0, exposure_mean=90, usable=True)]
GLARE_Q = [ImageQuality(sharpness=100, glare_pct=4.0, exposure_mean=90, usable=True, issues=["GLARE"])]


def obs(provider="station_cv", **states):
    checks = {k: CheckObservation(check_key=k, state=v[0], signal=v[1], measurements=v[2] if len(v) > 2 else {})
              for k, v in states.items()}
    return UnitObservation(provider=provider, model_version="t", checks=checks)


class TestRequirementResolution(unittest.TestCase):
    def test_font_table_matches_published_tiers(self):
        self.assertEqual(required_warning_font_pt(14, 12), 10)   # 26 in
        self.assertEqual(required_warning_font_pt(20, 15), 14)   # 35 in
        self.assertEqual(required_warning_font_pt(30, 15), 18)   # 45 in
        self.assertEqual(required_warning_font_pt(34, 28), 24)   # 62 in

    def test_expiry_formats(self):
        for ok in ("03-2027", "12-31-2026", "01/2028"):
            self.assertTrue(is_valid_expiry_format(ok), ok)
        for bad in ("2027-03-01", "31-12-2026", "13-2027", "March 2027", "02-30-2027", "02-29-2027"):
            self.assertFalse(is_valid_expiry_format(bad), bad)

    def test_category_rule_overrides_incomplete_work_order(self):
        p = plan("baby_product", wo_polybag=False)
        self.assertTrue(p.requirements["polybag_present_sealed"].required)
        self.assertIn("WORK_ORDER_OMITS_REQUIREMENT", [d.code for d in p.discrepancies])

    def test_work_order_marks_are_customer_requirements_not_amazon_rules(self):
        p = plan("fragile_glass", wo_handling_marks=["fragile"])
        r = p.requirements["handling_marks"]
        self.assertEqual(r.rule_ids, ["WO-HM-01"])
        self.assertEqual(RULES["WO-HM-01"].source, "work_order")

    def test_sets_require_sold_as_set_even_if_work_order_forgets(self):
        p = plan("set_multipack")
        self.assertIn("sold_as_set", p.requirements["handling_marks"].params["marks"])

    def test_small_bag_opening_does_not_require_warning(self):
        p = plan("apparel_textile", wo_polybag=True, bag_opening_in=4, bag_length_in=6, bag_width_in=4)
        self.assertFalse(p.requirements["suffocation_warning"].required)

    def test_film_thickness_is_an_attestation_not_a_visual_check(self):
        p = plan("plush_toy", wo_polybag=True)
        att = {a.rule_id: a.status for a in p.attestations}
        self.assertEqual(att["FBA-PB-02"], "DOCUMENT_REQUIRED")
        self.assertFalse(RULES["FBA-PB-02"].visually_verifiable)
        p2 = plan("plush_toy", wo_polybag=True, polybag_spec_mil=2.0)
        self.assertEqual({a.rule_id: a.status for a in p2.attestations}["FBA-PB-02"], "ATTESTED_BY_DOCUMENT")


class TestRulesEngine(unittest.TestCase):
    def judge(self, p, o, q=GOOD_Q):
        return {c.check_key: c for c in rules_engine.judge(p, o, q, "t", 0)}

    def test_every_determinate_verdict_cites_a_rule(self):
        p = plan("general")
        res = self.judge(p, obs(fnsku_label_placement=("ON_SEAM", 0.9), original_barcode_covered=("COVERED", 0.9)))
        for c in res.values():
            if c.verdict in (VerdictEnum.PASS, VerdictEnum.FAIL):
                self.assertTrue(c.rule_ids, c.check_key)

    def test_low_signal_becomes_uncertain_not_pass(self):
        res = self.judge(plan(), obs(fnsku_label_placement=("FLAT", 0.2), original_barcode_covered=("COVERED", 0.9)))
        self.assertEqual(res["fnsku_label_placement"].verdict, VerdictEnum.UNCERTAIN)
        self.assertEqual(res["fnsku_label_placement"].reason_code, "LOW_SIGNAL")

    def test_model_claim_vetoed_when_glare_covers_its_evidence(self):
        o = obs(provider="claude_vision", fnsku_label_placement=("FLAT", 0.95),
                original_barcode_covered=("COVERED", 0.95, {"region_glare_pct": 12.0}))
        res = self.judge(plan(), o, GLARE_Q)
        self.assertEqual(res["original_barcode_covered"].verdict, VerdictEnum.UNCERTAIN)
        self.assertEqual(res["original_barcode_covered"].reason_code, "CROSS_CHECK_GLARE_VETO")

    def test_mild_glare_elsewhere_does_not_veto(self):
        # Plastic film always has some shine; 4% clipped in the frame but 0% on the evidence box.
        o = obs(provider="free_vision", original_barcode_covered=("COVERED", 0.95, {"region_glare_pct": 0.0}),
                fnsku_label_placement=("FLAT", 0.9))
        res = self.judge(plan(), o, GLARE_Q)
        self.assertEqual(res["original_barcode_covered"].verdict, VerdictEnum.PASS)
        self.assertEqual(res["fnsku_label_placement"].verdict, VerdictEnum.PASS)  # no box, frame glare only 4%

    def test_severe_frame_glare_vetoes_unlocated_claim(self):
        severe = [ImageQuality(sharpness=100, glare_pct=15.0, exposure_mean=120, usable=True, issues=["GLARE"])]
        res = self.judge(plan(), obs(provider="free_vision", fnsku_label_placement=("FLAT", 0.9),
                                     original_barcode_covered=("COVERED", 0.9)), severe)
        self.assertEqual(res["fnsku_label_placement"].verdict, VerdictEnum.UNCERTAIN)

    def test_text_actually_read_by_ocr_is_not_vetoed_by_glare(self):
        p = plan("apparel_textile", wo_polybag=True, wo_suffocation_warning=True, bag_opening_in=10)
        o = obs(provider="local_ocr", suffocation_warning=("LEGIBLE", 0.9, {"wording_ok": True}))
        self.assertEqual(self.judge(p, o, GLARE_Q)["suffocation_warning"].verdict, VerdictEnum.PASS)

    def test_invalid_observed_state_is_rejected(self):
        o = UnitObservation(provider="claude_vision", model_version="t", checks={
            "fnsku_label_placement": CheckObservation(check_key="fnsku_label_placement", state="PASS", signal=1.0)})
        res = self.judge(plan(), o)
        self.assertEqual(res["fnsku_label_placement"].verdict, VerdictEnum.UNCERTAIN)

    def test_font_size_tolerance_band(self):
        p = plan("apparel_textile", wo_polybag=True, wo_suffocation_warning=True, bag_length_in=34, bag_width_in=28, bag_opening_in=20)
        verdict = lambda pt: self.judge(p, obs(suffocation_warning=("LEGIBLE", 0.9, {"est_font_pt": pt})))["suffocation_warning"].verdict
        self.assertEqual(verdict(25.0), VerdictEnum.PASS)
        self.assertEqual(verdict(22.0), VerdictEnum.UNCERTAIN)   # within 15 % below 24 pt
        self.assertEqual(verdict(14.0), VerdictEnum.FAIL)

    def test_expiry_format_checked_when_text_is_read(self):
        p = plan("consumable_dated", wo_expiry_date=True)
        bad = self.judge(p, obs(expiry_date=("LEGIBLE", 0.9, {"date_text": "2027-03-01"})))["expiry_date"]
        good = self.judge(p, obs(expiry_date=("LEGIBLE", 0.9, {"date_text": "EXP 03-2027"})))["expiry_date"]
        self.assertEqual(bad.verdict, VerdictEnum.FAIL)
        self.assertEqual(bad.reason_code, "EXPIRY_FORMAT_INVALID")
        self.assertEqual(good.verdict, VerdictEnum.PASS)

    def test_overall_policy_fail_beats_uncertain_beats_pass(self):
        p = plan()
        res = rules_engine.judge(p, obs(fnsku_label_placement=("ON_EDGE", 0.9), original_barcode_covered=("INDETERMINATE", 0.1)), GOOD_Q, "t", 0)
        decision, dispatch, _, actions = rules_engine.decide(res, p)
        self.assertEqual(decision.value, "FAIL")
        self.assertEqual(dispatch.value, "RED_REWORK")
        self.assertTrue(actions)

    def test_fnsku_confusable_ocr_and_mismatch(self):
        p = plan()
        p.requirements["fnsku_label_placement"].params["expected_fnsku"] = "X002A7B9K3"
        # Exact match
        exact = self.judge(p, obs(fnsku_label_placement=("FLAT", 0.9, {"fnsku_text": "X002A7B9K3"})))["fnsku_label_placement"]
        self.assertEqual(exact.verdict, VerdictEnum.PASS)
        # Confusable OCR difference: 0 vs O or B vs 8 -> UNCERTAIN, not false PASS or silent mismatch
        confusable = self.judge(p, obs(fnsku_label_placement=("FLAT", 0.9, {"fnsku_text": "X0O2A789K3"})))["fnsku_label_placement"]
        self.assertEqual(confusable.verdict, VerdictEnum.UNCERTAIN)
        self.assertEqual(confusable.reason_code, "FNSKU_CONFUSABLE_OCR")
        # Distinct SKU -> FAIL
        mismatch = self.judge(p, obs(fnsku_label_placement=("FLAT", 0.9, {"fnsku_text": "X002A7Z9K9"})))["fnsku_label_placement"]
        self.assertEqual(mismatch.verdict, VerdictEnum.FAIL)
        self.assertEqual(mismatch.reason_code, "FNSKU_MISMATCH")

    def test_pending_attestation_routes_to_amber_review(self):
        # Plush toy requires polybag; when film spec is missing, FBA-PB-02 is DOCUMENT_REQUIRED
        p = plan("plush_toy", wo_polybag=True, polybag_spec_mil=None)
        # All visual checks PASS
        checks = rules_engine.judge(p, obs(polybag_present_sealed=("SEALED", 0.95),
                                           suffocation_warning=("LEGIBLE", 0.95, {"wording_ok": True}),
                                           fnsku_label_placement=("FLAT", 0.95),
                                           original_barcode_covered=("COVERED", 0.95)), GOOD_Q, "t", 0)
        decision, dispatch, summary, actions = rules_engine.decide(checks, p)
        self.assertEqual(decision.value, "UNCERTAIN")
        self.assertEqual(dispatch.value, "AMBER_REVIEW")
        self.assertIn("documentation required", summary.lower())


if __name__ == "__main__":
    unittest.main()

"""Deterministic rules engine: observations + requirements -> verdicts.

This is the only component allowed to say PASS, FAIL or UNCERTAIN. It is
plain code, so every verdict is reproducible and cites the rule it applied.

Verdict policy
--------------
* PASS       - the requirement applies and positive evidence shows it is met.
* FAIL       - the requirement applies and positive evidence shows it is not met.
* UNCERTAIN  - the evidence cannot support either (blur, glare, out-of-view,
               weak signal, borderline measurement, cross-check veto).
* NOT_REQUIRED - neither Amazon rules nor the work order require it.

Absence of a defect is never inferred from a degraded frame: "I could not see
an exposed barcode" under glare is UNCERTAIN, not PASS.
"""

from typing import Dict, List, Optional, Tuple

from submissions.kl2400033283.agent.rules.authoritative_rules import (
    CHECK_KEYS, CHECK_TITLES, HANDLING_MARKS, RequirementPlan, is_valid_expiry_format,
)
from submissions.kl2400033283.agent.schemas.evidence import (
    CheckResult, DispatchSignal, ImageQuality, OverallDecisionEnum, VerdictEnum,
)
from submissions.kl2400033283.agent.vision.observations import CheckObservation, UnitObservation, indeterminate

MIN_SIGNAL = 0.35            # below this, a determinate observation is not trusted
FONT_FAIL_RATIO = 0.85       # measured < 85% of required size -> FAIL
# Absence-of-defect states that a glare-affected frame cannot prove (cross-check veto).
CLEAN_STATES = {"COVERED", "FLAT", "LEGIBLE", "SEALED"}
# Glare veto thresholds for model claims. Plastic film always has a few specular highlights, so the
# veto looks at glare INSIDE the evidence box the model pointed to; without a box, only severe
# whole-frame glare vetoes.
REGION_GLARE_VETO_PCT = 5.0
FRAME_GLARE_VETO_PCT = 8.0

V = VerdictEnum


def _verdict_for(check_key: str, obs: CheckObservation, params: Dict) -> Tuple[VerdictEnum, str, str, Optional[str]]:
    """Return (verdict, reason_code, detail, remediation) for one observed state."""
    s, m = obs.state, obs.measurements
    note = obs.notes[0] if obs.notes else ""

    # A readable FNSKU check: exact match required.
    # If it differs only by OCR-confusable characters (e.g. B/8, S/5, O/0), route to UNCERTAIN
    # so a human verifies instead of silently accepting a wrong SKU or failing a blurry read.
    if check_key == "fnsku_label_placement" and m.get("fnsku_text") and params.get("expected_fnsku"):
        raw_read = _clean_code(m["fnsku_text"])
        raw_want = _clean_code(params["expected_fnsku"])
        if len(raw_read) >= 8 and raw_read != raw_want:
            if _fnsku_key(raw_read) == _fnsku_key(raw_want):
                return (V.UNCERTAIN, "FNSKU_CONFUSABLE_OCR",
                        f"Label reads FNSKU '{m['fnsku_text']}' which differs from expected '{params['expected_fnsku']}' "
                        "only by OCR-confusable characters. Physical verification required.",
                        "Verify barcode text against physical label.")
            return (V.FAIL, "FNSKU_MISMATCH",
                    f"Label reads FNSKU {m['fnsku_text']} but the work order is for {params['expected_fnsku']}.",
                    "Re-print and apply the FNSKU for this ASIN/condition.")

    if s == "INDETERMINATE" and m.get("view_conflict"):
        return V.UNCERTAIN, "VIEW_CONFLICT", note, "Views disagree: inspect the unit by hand and recapture."
    if s == "INDETERMINATE":
        return V.UNCERTAIN, "EVIDENCE_INSUFFICIENT", note or "Evidence does not support a reliable judgment.", \
            "Recapture this face with even lighting and the relevant area in focus."

    if check_key == "polybag_present_sealed":
        if s == "SEALED":
            return V.PASS, "POLYBAG_SEALED", note, None
        if s == "UNSEALED":
            gap = m.get("open_gap_in")
            return V.FAIL, "POLYBAG_OPEN", note + (f" Open gap ~{gap} in." if gap else ""), \
                "Re-seal the full width of the bag mouth (heat seal or tape); no gaps allowed."
        if s == "ABSENT":
            return V.FAIL, "POLYBAG_MISSING", note, "Bag the unit in a transparent polybag (>= 1.5 mil) and seal it."
        if s == "SEAL_NOT_VISIBLE":
            return V.UNCERTAIN, "SEAL_NOT_IN_VIEW", note, "Capture the sealed edge of the bag."

    if check_key == "suffocation_warning":
        if s == "LEGIBLE":
            if m.get("wording_ok") is False:
                return V.FAIL, "WARNING_WORDING_MISSING", "Panel text does not contain a suffocation warning.", \
                    "Apply a standard suffocation warning label."
            req_pt, est = params.get("min_font_pt"), m.get("est_font_pt")
            if req_pt and est:
                if est < FONT_FAIL_RATIO * req_pt:
                    return V.FAIL, "WARNING_PRINT_TOO_SMALL", \
                        f"Warning print measured ~{est:g} pt; bag size requires >= {req_pt} pt (FBA-SW-02).", \
                        f"Replace with a warning printed at >= {req_pt} pt."
                if est < req_pt:
                    return V.UNCERTAIN, "WARNING_SIZE_BORDERLINE", \
                        f"Warning print measured ~{est:g} pt vs required {req_pt} pt: inside measurement tolerance.", \
                        "Verify print size against the label spec sheet."
                return V.PASS, "WARNING_LEGIBLE", f"{note} Print ~{est:g} pt meets >= {req_pt} pt.", None
            size_note = " Print size not measured (no calibrated scale)." if req_pt else ""
            return V.PASS, "WARNING_LEGIBLE", note + size_note, None
        if s == "OBSCURED":
            return V.FAIL, "WARNING_OBSCURED", note, "Re-fold or re-bag so the warning lies flat and fully visible."
        if s == "ABSENT":
            return V.FAIL, "WARNING_MISSING", note, \
                f"Apply a suffocation warning{' >= ' + str(params['min_font_pt']) + ' pt' if params.get('min_font_pt') else ''}."

    if check_key == "fnsku_label_placement":
        if s == "FLAT":
            return V.PASS, "FNSKU_ON_FLAT_FACE", note, None
        fixes = {
            "ON_SEAM": ("FNSKU_ON_SEAM", "Move the label off the seam onto a single flat panel."),
            "ON_CURVE": ("FNSKU_ON_CURVE", "Re-apply on the flattest face or use a hang-tag/bag label so it lies flat."),
            "ON_EDGE": ("FNSKU_ACROSS_EDGE", "Re-apply fully on one face, >= 1/4 in from the edges."),
            "ABSENT": ("FNSKU_MISSING", "Print and apply the FNSKU label."),
        }
        if s in fixes:
            code, fix = fixes[s]
            return V.FAIL, code, note, fix

    if check_key == "original_barcode_covered":
        if s == "COVERED":
            return V.PASS, "SINGLE_SCANNABLE_BARCODE", note, None
        if s == "EXPOSED":
            return V.FAIL, "ORIGINAL_BARCODE_EXPOSED", note, \
                "Cover every UPC/EAN completely with the FNSKU label or an opaque blank label."

    if check_key == "expiry_date":
        if s == "LEGIBLE":
            text = m.get("date_text")
            if text:
                if not is_valid_expiry_format(text.replace("EXP", "").strip()):
                    return V.FAIL, "EXPIRY_FORMAT_INVALID", \
                        f"Read '{text}'; Amazon requires MM-DD-YYYY or MM-YYYY (FBA-EX-01).", \
                        "Apply an expiry sticker in MM-DD-YYYY or MM-YYYY format over the original date."
                return V.PASS, "EXPIRY_VISIBLE", f"Read '{text}', format valid.", None
            return V.PASS, "EXPIRY_VISIBLE", note + " Date format not machine-read.", None
        if s == "OCCLUDED":
            return V.FAIL, "EXPIRY_COVERED", note, "Move the covering label; the date must be visible outside the prep."
        if s == "ILLEGIBLE":
            return V.FAIL, "EXPIRY_ILLEGIBLE", note, "Re-label the date on the outside of the polybag/wrap."
        if s == "ABSENT":
            return V.FAIL, "EXPIRY_NOT_FOUND", note + " (Station protocol: date must face the camera.)", \
                "Apply an expiry label on the outside of the prep, on the camera face."

    return V.UNCERTAIN, "UNRECOGNISED_OBSERVATION", f"Unrecognised observed state '{s}'.", None


_OCR_CONFUSABLES = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})


def _clean_code(code: str) -> str:
    return "".join(ch for ch in str(code).upper() if ch.isalnum())


def _fnsku_key(code: str) -> str:
    """Normalise OCR-confusable characters for similarity comparison."""
    return _clean_code(code).translate(_OCR_CONFUSABLES)


def _marks_verdict(obs: CheckObservation, required: List[str]) -> Tuple[VerdictEnum, str, str, Optional[str]]:
    if obs.state == "INDETERMINATE":
        return V.UNCERTAIN, "EVIDENCE_INSUFFICIENT", obs.notes[0] if obs.notes else "", \
            "Recapture the face carrying the handling stickers."
    found = set(obs.measurements.get("detected_marks", []))
    missing = [m for m in required if m not in found]
    if not missing:
        return V.PASS, "HANDLING_MARKS_PRESENT", f"Required marks present: {', '.join(required)}.", None
    names = ", ".join(HANDLING_MARKS[m] for m in missing)
    if obs.measurements.get("glare_on_product"):
        return V.UNCERTAIN, "MARK_POSSIBLY_UNDER_GLARE", f"Not found: {names}; glare may be hiding it.", \
            "Recapture without glare."
    return V.FAIL, "HANDLING_MARK_MISSING", f"Missing required mark(s): {names}.", f"Apply: {names}."


def judge(plan: RequirementPlan, observation: UnitObservation, qualities: List[ImageQuality],
          model_version: str, latency_ms: int, in_domain: bool = True) -> List[CheckResult]:
    """in_domain=False: the perception engine is outside its validated domain (station CV on an
    uncalibrated photo). Its observations are kept as hints but may not produce PASS or FAIL."""
    glare_frames = any("GLARE" in q.issues for q in qualities if q.usable)
    worst_frame_glare = max((q.glare_pct for q in qualities if q.usable), default=0.0)
    results: List[CheckResult] = []
    for k in CHECK_KEYS:
        req = plan.requirements[k]
        if not req.required:
            results.append(CheckResult(
                check_key=k, title=CHECK_TITLES[k], verdict=V.NOT_REQUIRED, confidence=1.0,
                detail=req.note or "Not required by Amazon category rules or the work order.",
                reason_code="NOT_APPLICABLE", model_version=model_version, latency_ms=latency_ms))
            continue

        obs = observation.get(k) or indeterminate(k, "Perception returned no observation for this check.")
        if not obs.is_valid_state():
            obs = indeterminate(k, f"Rejected invalid observed state '{obs.state}'.")

        if k == "handling_marks":
            verdict, code, detail, fix = _marks_verdict(obs, req.params.get("marks", []))
        else:
            verdict, code, detail, fix = _verdict_for(k, obs, req.params)

        # Independent cross-checks (different mechanism from the perception provider).
        if verdict in (V.PASS, V.FAIL) and obs.signal < MIN_SIGNAL:
            verdict, code = V.UNCERTAIN, "LOW_SIGNAL"
            detail = f"Observation '{obs.state}' too weak to rely on (signal {obs.signal:.2f}). {detail}"
            fix = "Recapture for a clearer view."
        # Generative perception can claim a clean state it didn't really see; deterministic engines
        # (station CV handles glare itself, OCR only reports text it actually read) are exempt.
        region_glare = obs.measurements.get("region_glare_pct")
        glare_blocks_claim = (region_glare > REGION_GLARE_VETO_PCT) if region_glare is not None             else worst_frame_glare > FRAME_GLARE_VETO_PCT
        if (verdict == V.PASS and obs.state in CLEAN_STATES and glare_blocks_claim
                and observation.provider not in ("station_cv", "local_ocr")):
            verdict, code = V.UNCERTAIN, "CROSS_CHECK_GLARE_VETO"
            detail = f"Model reported '{obs.state}' but the quality gate measured sensor-clipped glare. {detail}"
            fix = "Recapture without glare (diffuse lighting / tilt)."

        if not in_domain and verdict in (V.PASS, V.FAIL):
            detail = (f"Out-of-domain capture: the station CV engine is only validated on calibrated gantry frames, "
                      f"so its reading ('{obs.state}') is a hint, not evidence. {detail}")
            verdict, code = V.UNCERTAIN, "OUT_OF_DOMAIN_CAPTURE"
            fix = ("Re-run with Claude vision (set ANTHROPIC_API_KEY) or capture on the calibrated station camera.")

        if verdict in (V.PASS, V.FAIL):
            confidence = min(0.99, 0.5 + 0.5 * obs.signal) * (0.9 if glare_frames else 1.0)
        else:
            confidence = min(0.49, obs.signal)

        results.append(CheckResult(
            check_key=k, title=CHECK_TITLES[k], verdict=verdict, confidence=round(confidence, 3),
            detail=detail.strip(), reason_code=code, rule_ids=req.rule_ids, required_by=req.required_by,
            observed_state=obs.state, measurements=obs.measurements, regions=obs.regions,
            remediation=fix if verdict != V.PASS else None, model_version=model_version, latency_ms=latency_ms))
    return results


def decide(checks: List[CheckResult], plan: RequirementPlan) -> Tuple[OverallDecisionEnum, DispatchSignal, str, List[str]]:
    fails = [c for c in checks if c.verdict == V.FAIL]
    uncertain = [c for c in checks if c.verdict == V.UNCERTAIN]
    doc_fail = [a for a in plan.attestations if a.status == "DOCUMENT_NONCOMPLIANT"]
    doc_pending = [a for a in plan.attestations if a.status == "DOCUMENT_REQUIRED"]
    actions: List[str] = [f"{c.title}: {c.remediation}" for c in fails if c.remediation]
    actions += [f"{c.title}: {c.remediation or 'Manual review.'}" for c in uncertain]
    actions += [f"{a.rule_id}: {a.detail}" for a in plan.attestations if a.status in ("DOCUMENT_REQUIRED", "DOCUMENT_NONCOMPLIANT")]

    if fails or doc_fail:
        names = ", ".join(c.title for c in fails) or "document check"
        return (OverallDecisionEnum.FAIL, DispatchSignal.RED_REWORK,
                f"PREP FAIL - {len(fails) + len(doc_fail)} requirement(s) not met: {names}.", actions)
    if uncertain or doc_pending:
        reasons = [c.title for c in uncertain] + [f"documentation required ({a.rule_id})" for a in doc_pending]
        names = ", ".join(reasons)
        return (OverallDecisionEnum.UNCERTAIN, DispatchSignal.AMBER_REVIEW,
                f"PREP UNCERTAIN - evidence or documentation pending for: {names}. Routed to human review.", actions)
    gaps = [d for d in plan.discrepancies]
    if gaps:
        # The unit itself is compliant, but the work order is wrong: hold it for a person (AMBER) so the
        # work order gets fixed before the next unit is prepped from it. Never silently GREEN.
        actions += [f"Work order: {d.detail}" for d in gaps]
        return (OverallDecisionEnum.PASS, DispatchSignal.AMBER_REVIEW,
                f"PREP PASS on the unit, but {len(gaps)} work-order gap(s) need a person: "
                + "; ".join(d.code for d in gaps) + ".", actions)
    return (OverallDecisionEnum.PASS, DispatchSignal.GREEN_RELEASE,
            "PREP PASS - every applicable requirement verified from the images.", actions)

"""Round 3 pod adapter: ``handle(agent_input) -> agent_output`` (CUBE contract v1.0).

The orchestrator calls Prep with an Agent Input (shared/schemas/agent-input.schema.json). This module
turns it into a Prep Manager inspection and returns an Agent Output whose ``evidence`` is a CUBE
Evidence Record v1. The Round 2 engine (perception -> rules engine -> sealed internal record) is
unchanged; this file only maps contracts.

Behaviour (see shared/contracts/agent-api.md):
* Idempotent: same (org, request_id) -> the stored output is returned again (same record_id).
* Tenancy: an unknown org, or a subject that exists only under another org -> LookupError (404).
* Inputs: ``inputs[].ref`` are resolved under INPUT_DIR (the orchestrator's data/input), plus
  ``asset:<id>`` (this agent's own tenant-scoped uploads) and ``scenario:<id>`` (demo captures).
  Absolute paths and ``..`` are refused. A supplied sha256 that does not match the file drops it.
* No capture at all: if a work order row with operator-recorded observations is available, the
  rules engine judges those (model.name = "rules", provider "operator_record"); otherwise every
  check is UNCERTAIN / insufficient_evidence. It never pretends a photo was looked at.
* Upstream: the latest Receiving record (after workflow overrides) gates the result.
* Payload: prep_price_usd (work order), measurements = null (no scale/dimensioner integrated), and
  rule_source (URL + retrieval date per cited rule).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from submissions.kl2400033283.agent.config import AGENT_VERSION, ALLOWED_ORGS
from submissions.kl2400033283.agent.rules.authoritative_rules import CHECK_KEYS, rule_source
from submissions.kl2400033283.agent.schemas.evidence import (
    EvidenceRecord, PrepInspectionInput, RecordStatusEnum, VerdictEnum,
)
from submissions.kl2400033283.agent.vision.observations import CheckObservation, UnitObservation, indeterminate

STAGE = "prep"
AGENT_ID = f"prep-manager@{AGENT_VERSION}"
CONTRACT_VERSION = "1.0"
_HERE = Path(__file__).resolve().parent
_VENDORED_SAMPLE = _HERE.parent / "contract" / "round3" / "sample" / "prep_sample.csv"

KEY_MAP = {  # internal check key -> Round 3 recommended key
    "polybag_present_sealed": "polybag_sealed",
    "suffocation_warning": "suffocation_warning",
    "fnsku_label_placement": "fnsku_label_placement",
    "original_barcode_covered": "original_barcode_covered",
    "expiry_date": "expiry_legible",
    "handling_marks": "handling_marks",
}
EXPECTED = {
    "polybag_present_sealed": "sealed", "suffocation_warning": "legible", "fnsku_label_placement": "flat",
    "original_barcode_covered": "covered", "expiry_date": "legible", "handling_marks": "all_present",
}
OUTCOME = {"PASS": "compliant", "FAIL": "non_compliant", "UNCERTAIN": "pending_review"}
RECOMMEND = {"PASS": "continue", "UNCERTAIN": "review", "FAIL": "route_to_recovery"}

# internal reason_code -> contract uncertain_reason
UNCERTAIN_REASON = {
    "CROSS_CHECK_GLARE_VETO": "poor_image", "MARK_POSSIBLY_UNDER_GLARE": "poor_image",
    "IMAGE_UNUSABLE": "poor_image", "SEAL_NOT_IN_VIEW": "occluded",
    "SYSTEM_TIMEOUT": "model_error", "SYSTEM_FAIL_OPEN": "model_error",
    "FNSKU_CONFUSABLE_OCR": "conflicting_evidence", "VIEW_CONFLICT": "conflicting_evidence",
    "UPSTREAM_RECEIVING_UNCERTAIN": "conflicting_evidence",
    "OUT_OF_DOMAIN_CAPTURE": "other", "UNRECOGNISED_OBSERVATION": "other",
}

# Round 2 sample CSV value -> closed-vocabulary observed state (operator-recorded path)
CSV_STATE = {
    "polybag_present_sealed": {"yes": "SEALED", "not_sealed": "UNSEALED", "missing": "ABSENT"},
    "suffocation_warning": {"legible": "LEGIBLE", "obscured_by_fold": "OBSCURED", "missing": "ABSENT"},
    "fnsku_label_placement": {"flat": "FLAT", "on_seam": "ON_SEAM", "on_curve": "ON_CURVE",
                              "on_edge": "ON_EDGE", "missing": "ABSENT"},
    "original_barcode_covered": {"yes": "COVERED", "no": "EXPOSED"},
    "expiry_date": {"legible": "LEGIBLE", "illegible_after_wrap": "ILLEGIBLE"},
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(record: Dict) -> str:
    """Contract v1: SHA-256 of canonical JSON excluding content_hash and overrides."""
    return hashlib.sha256(_canonical({k: v for k, v in record.items() if k not in ("content_hash", "overrides")})).hexdigest()


def record_id_for(request_id: str) -> str:
    return "PRP-" + re.sub(r"[^A-Za-z0-9._-]", "-", request_id)[:120]


# ---------------------------------------------------------------------- work order lookup
def _work_order(org_id: str, subject_id: str, context: Dict) -> Optional[Dict]:
    """Work order / operator row for this unit, tenant-scoped. LookupError if it exists only elsewhere."""
    wo = context.get("work_order") if isinstance(context.get("work_order"), dict) else None
    if wo:
        return wo
    rows: List[Dict] = []
    try:  # inside the pod: the organiser's tenant-scoped reader
        from shared.utils import sample_data  # type: ignore
        rows = list(sample_data.rows("prep"))
    except Exception:
        path = Path(os.environ.get("PREP_SAMPLE_CSV", _VENDORED_SAMPLE))
        if path.exists():
            import csv
            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
    mine = [r for r in rows if r.get("unit_id") == subject_id and r.get("org_id") == org_id]
    if mine:
        return mine[0]
    if any(r.get("unit_id") == subject_id for r in rows):
        raise LookupError(f"{subject_id} does not belong to {org_id}")  # never answer cross-tenant
    return None


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def _inspection_input(org_id: str, subject_id: str, wo: Optional[Dict], paths: List[str],
                      refs: List[str]) -> PrepInspectionInput:
    wo = wo or {}
    marks = [m.strip() for m in str(wo.get("wo_handling_marks", "")).replace(";", ",").split(",") if m.strip()]
    safe = lambda v, d: v if v and re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", str(v)) else d  # noqa: E731
    return PrepInspectionInput(
        unit_id=safe(subject_id, "UNIT-UNKNOWN"), org_id=org_id, client_id="round3_pod",
        work_order_id=safe(wo.get("work_order_id"), "WO-UNSPECIFIED"),
        fba_shipment_id=safe(wo.get("fba_shipment_id"), "FBA-UNSPECIFIED"),
        sku=str(wo.get("sku") or "SKU-UNSPECIFIED")[:64], asin=str(wo.get("asin") or "UNKNOWN")[:20],
        fnsku=str(wo.get("fnsku") or "UNKNOWN")[:20], operator_id=safe(wo.get("operator_id"), "op_pod"),
        category=str(wo.get("category") or "general"),
        wo_polybag=_truthy(wo.get("wo_polybag")), wo_suffocation_warning=_truthy(wo.get("wo_suffocation_warning")),
        wo_expiry_date=_truthy(wo.get("wo_expiry_date")), wo_handling_marks=marks[:6],
        station_calibrated=False, image_paths=paths[:4], image_asset_ids=refs[:4])


def _recorded_observation(wo: Dict, marks: List[str]) -> UnitObservation:
    checks: Dict[str, CheckObservation] = {}
    for k in CHECK_KEYS:
        raw = str(wo.get(k, "")).strip().lower()
        note = f"Operator-recorded value '{raw}' (no capture in this request)."
        if k == "handling_marks":
            if raw == "all_present":
                checks[k] = CheckObservation(check_key=k, state="DETECTED", signal=0.8,
                                             measurements={"detected_marks": marks}, notes=[note])
            elif raw == "some_missing":
                checks[k] = CheckObservation(check_key=k, state="DETECTED", signal=0.8,
                                             measurements={"detected_marks": []}, notes=[note])
            else:
                checks[k] = indeterminate(k, note)
            continue
        state = CSV_STATE.get(k, {}).get(raw)
        checks[k] = (CheckObservation(check_key=k, state=state, signal=0.8, notes=[note]) if state
                     else indeterminate(k, note))
    return UnitObservation(provider="operator_record", model_version="rules", checks=checks, model_calls=0,
                           raw_notes=["Judged from the operator-recorded work-order row; no image was analysed."])


# ---------------------------------------------------------------------- inputs
def _input_root() -> Path:
    return Path(os.environ.get("INPUT_DIR", Path.cwd() / "data" / "input")).resolve()


def _resolve_inputs(org_id: str, inputs: List[Dict], db) -> Tuple[List[str], List[str], List[Dict], List[str]]:
    """-> (paths, refs, contract inputs, notes). Never follows absolute paths or '..'."""
    from submissions.kl2400033283.agent.sim.scenarios import BY_ID as SCENARIOS
    paths, refs, used, notes = [], [], [], []
    root = _input_root()
    for item in inputs or []:
        ref = str(item.get("ref", ""))
        kind = item.get("kind") or "image"
        want = item.get("sha256")
        path: Optional[Path] = None
        if ref.startswith("asset:"):
            row = db.get_asset(org_id, ref.split(":", 1)[1])
            path = Path(row["storage_path"]) if row else None
        elif ref.startswith("scenario:") and ref.split(":", 1)[1] in SCENARIOS:
            path = SCENARIOS[ref.split(":", 1)[1]].ensure_rendered()
        elif ref and not Path(ref).is_absolute() and ".." not in Path(ref).parts:
            cand = (root / ref).resolve()
            if root in cand.parents and cand.is_file():
                path = cand
        if path is None or not path.exists():
            notes.append(f"input '{ref}' not found")
            used.append({"ref": ref, "sha256": want if want and re.fullmatch(r"[a-f0-9]{64}", str(want)) else None,
                         "kind": kind if kind in ("image", "video", "document", "csv_row", "other") else "other"})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if want and want != digest:
            notes.append(f"input '{ref}' sha256 mismatch: ignored")
            continue
        used.append({"ref": ref, "sha256": digest, "kind": "image" if path.suffix.lower() in IMAGE_EXT else "other"})
        if path.suffix.lower() in IMAGE_EXT and len(paths) < 4:
            paths.append(str(path))
            refs.append(ref)
    return paths, refs, used, notes


# ---------------------------------------------------------------------- upstream
def _effective_verdict(request: Dict, record: Dict) -> str:
    latest = [o for o in (request.get("context") or {}).get("overrides", [])
              if isinstance(o, dict) and (o.get("supersedes") or {}).get("record_id") == record.get("record_id")]
    return latest[-1].get("new_verdict", record["decision"]["verdict"]) if latest else record["decision"]["verdict"]


def _receiving_gate(request: Dict) -> Optional[Dict]:
    found = [r for r in request.get("previous_evidence", []) if r.get("stage") == "receiving"]
    if not found:
        return None
    rec = found[-1]
    verdict = _effective_verdict(request, rec)
    outcome = rec.get("decision", {}).get("outcome")
    hold = bool((rec.get("payload") or {}).get("prep_hold"))
    base = {"check_key": "receiving_cleared", "expected": "accept", "observed": outcome,
            "evidence_refs": [rec["record_id"]], "confidence": None}
    if outcome == "reject" or hold or (verdict == "FAIL" and outcome not in ("accept_with_exceptions",)):
        return {**base, "verdict": "FAIL",
                "detail": f"Receiving record {rec['record_id']} is {verdict}/{outcome}"
                          f"{' with prep_hold' if hold else ''}: the unit must not be released from prep."}
    if verdict != "PASS":
        return {**base, "verdict": "UNCERTAIN", "uncertain_reason": "conflicting_evidence",
                "detail": f"Receiving record {rec['record_id']} is {verdict}/{outcome}: confirm before release."}
    return {**base, "verdict": "PASS", "detail": f"Receiving record {rec['record_id']} accepted the unit."}


# ---------------------------------------------------------------------- mapping
def _check(c, refs: List[str], operator: bool) -> Optional[Dict]:
    if c.verdict == VerdictEnum.NOT_REQUIRED:
        return None
    out: Dict[str, Any] = {"check_key": KEY_MAP[c.check_key], "verdict": c.verdict.value,
                           "confidence": None if operator else round(float(c.confidence), 3),
                           "expected": EXPECTED[c.check_key],
                           "observed": ("all_present" if c.verdict == VerdictEnum.PASS else "some_missing")
                           if c.check_key == "handling_marks" and c.observed_state == "DETECTED"
                           else (c.observed_state or "unknown").lower(),
                           "detail": f"{c.detail} [{c.reason_code}; rules {', '.join(c.rule_ids) or '-'}]"[:600]}
    if refs:
        out["evidence_refs"] = refs
    if c.verdict == VerdictEnum.UNCERTAIN:
        reason = UNCERTAIN_REASON.get(c.reason_code or "", "insufficient_evidence")
        if "unusable" in (c.detail or "").lower():
            reason = "poor_image"
        out["uncertain_reason"] = reason
    return out


def _to_contract(request: Dict, rec: EvidenceRecord, inputs: List[Dict], refs: List[str], wo: Optional[Dict],
                 notes: List[str], gate: Optional[Dict]) -> Dict:
    s = request["subject"]
    operator = rec.perception is not None and rec.perception.provider == "operator_record"
    checks = [c for c in (_check(c, refs, operator) for c in rec.checks) if c]
    if gate:
        checks.append(gate)
    verdicts = {c["verdict"] for c in checks}
    verdict = "FAIL" if "FAIL" in verdicts else ("UNCERTAIN" if "UNCERTAIN" in verdicts or not checks else "PASS")
    pending = rec.status == RecordStatusEnum.FAILED_OPEN
    confs = [c["confidence"] for c in checks if isinstance(c.get("confidence"), (int, float))]
    p = rec.perception
    model = {"name": "rules" if operator or not p else p.provider,
             "version": "rules" if operator or not p else p.model_version,
             "provider": "operator_record" if operator else (p.provider if p else None),
             "prompt_version": None, "calls": p.model_calls if p else 0, "cost_usd": p.cost_usd if p else 0.0}
    cited = sorted({r for c in rec.checks for r in c.rule_ids} | {a["rule_id"] for a in rec.attestations})
    reason = rec.outcome.summary
    if operator:
        reason = (f"PREP {verdict} from operator-recorded work-order values judged by the rules engine; "
                  f"no capture was supplied, so nothing was verified from images. ({rec.outcome.summary})")
    if gate and gate["verdict"] != "PASS":
        reason = f"{reason} Upstream: {gate['detail']}"
    if notes:
        reason = f"{reason} Inputs: {'; '.join(notes)}."
    refs_map = {"work_order_id": rec.subject.work_order_id, "fba_shipment_id": rec.subject.fba_shipment_id,
                "sku": rec.subject.sku, "asin": rec.subject.asin, "fnsku": rec.subject.fnsku}
    error = None
    if pending:
        error = {"code": "model_error", "message": rec.outcome.summary[:300], "retryable": True, "stage": STAGE,
                 "agent_id": AGENT_ID, "at": _now(), "detail": None}
    record: Dict[str, Any] = {
        "schema_version": CONTRACT_VERSION,
        "record_id": record_id_for(request["request_id"]),
        "workflow_id": request["workflow_id"],
        "stage": STAGE,
        "agent_id": AGENT_ID,
        "subject": {"org_id": s["org_id"], "subject_id": s["subject_id"], "unit_id": s["subject_id"],
                    "unit_scope": "unit",
                    "refs": {k: v for k, v in refs_map.items() if v and not v.endswith(("UNSPECIFIED", "UNKNOWN"))}},
        "client_id": rec.client_id,
        "status": "pending" if pending else "completed",
        "captured_at": (wo or {}).get("captured_at") or rec.captured_at,
        "produced_at": _now(),
        "latency_ms": int(rec.total_latency_ms or 0),
        "operator_id": (wo or {}).get("operator_id") or rec.operator_label,
        "model": model,
        "inputs": inputs,
        "checks": checks,
        "decision": {"verdict": verdict, "outcome": OUTCOME[verdict],
                     "confidence": round(min(confs), 3) if confs else None,
                     "reason": reason[:1000], "needs_human": verdict == "UNCERTAIN"},
        "payload": {
            "prep_price_usd": float(wo["prep_price_usd"]) if wo and wo.get("prep_price_usd") not in (None, "") else None,
            "measurements": None,
            "measurements_note": "Not measured: no scale or dimensioner is integrated at this station yet.",
            "rule_source": rule_source(cited),
            "attestations": rec.attestations,
            "work_order_discrepancies": rec.discrepancies,
            "internal_record_id": rec.record_id,
            "internal_content_hash": rec.content_hash,
            "perception_route": rec.perception.routing_reason if rec.perception else None,
        },
        "upstream_refs": [r["record_id"] for r in request.get("previous_evidence", []) if r.get("record_id")],
        "overrides": [],
        "error": error,
    }
    record["content_hash"] = content_hash(record)
    action = "retry" if pending else RECOMMEND[verdict]
    return {"schema_version": CONTRACT_VERSION, "workflow_id": record["workflow_id"], "stage": STAGE,
            "agent_id": AGENT_ID, "status": record["status"], "verdict": verdict,
            "confidence": record["decision"]["confidence"], "timestamp": record["produced_at"], "model": model,
            "error": error, "next_step_recommendation": {"action": action, "reason": record["decision"]["reason"][:500]},
            "evidence": record}


def pending_output(request: Dict, code: str, message: str) -> Dict:
    """Fail-open output when even the adapter failed: no checks, UNCERTAIN, status pending, error set."""
    s = request["subject"]
    err = {"code": code, "message": message[:300], "retryable": True, "stage": STAGE, "agent_id": AGENT_ID,
           "at": _now(), "detail": None}
    model = {"name": "none", "version": "0", "provider": None, "calls": 0, "cost_usd": 0.0}
    record = {
        "schema_version": CONTRACT_VERSION, "record_id": record_id_for("PENDING-" + request["request_id"]),
        "workflow_id": request["workflow_id"], "stage": STAGE, "agent_id": AGENT_ID,
        "subject": {"org_id": s["org_id"], "subject_id": s["subject_id"], "unit_id": s["subject_id"],
                    "unit_scope": "unit", "refs": {}},
        "client_id": None, "status": "pending", "captured_at": _now(), "produced_at": _now(), "latency_ms": None,
        "operator_id": None, "model": model, "inputs": [], "checks": [],
        "decision": {"verdict": "UNCERTAIN", "outcome": "pending_review", "confidence": None,
                     "reason": f"{code}: {message}"[:500], "needs_human": True},
        "payload": {}, "upstream_refs": [r.get("record_id") for r in request.get("previous_evidence", [])
                                         if r.get("record_id")],
        "overrides": [], "error": err}
    record["content_hash"] = content_hash(record)
    return {"schema_version": CONTRACT_VERSION, "workflow_id": record["workflow_id"], "stage": STAGE,
            "agent_id": AGENT_ID, "status": "pending", "verdict": "UNCERTAIN", "confidence": None,
            "timestamp": record["produced_at"], "model": model, "error": err,
            "next_step_recommendation": {"action": "retry", "reason": message[:300]}, "evidence": record}


# ---------------------------------------------------------------------- entry point
_AGENT = None


def _agent():
    global _AGENT
    if _AGENT is None:
        from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent
        _AGENT = PrepManagerAgent()
    return _AGENT


def handle(request: Dict, agent=None) -> Dict:
    """CUBE in-process interface. Raises LookupError for unknown / foreign subjects (-> 404)."""
    agent = agent or _agent()
    if request.get("stage") != STAGE:
        raise ValueError("stage must be 'prep'")
    s = request["subject"]
    org_id, subject_id = s["org_id"], s["subject_id"]
    if org_id not in ALLOWED_ORGS:
        raise LookupError(f"unknown org {org_id}")
    cached = agent.db.get_pod_output(org_id, request["request_id"])
    if cached:
        return cached
    context = request.get("context") or {}
    wo = _work_order(org_id, subject_id, context)
    paths, refs, inputs, notes = _resolve_inputs(org_id, request.get("inputs") or [], agent.db)
    inp = _inspection_input(org_id, subject_id, wo, paths, refs)
    recorded = _recorded_observation(wo, inp.wo_handling_marks) if (not paths and wo) else None
    internal_id = record_id_for(request["request_id"]) + "-" + hashlib.sha256(
        request["request_id"].encode()).hexdigest()[:6]
    rec = agent.inspect(inp, record_id=internal_id, captured_at=(wo or {}).get("captured_at"),
                        recorded_observation=recorded)
    out = _to_contract(request, rec, inputs, refs, wo, notes, _receiving_gate(request))
    agent.db.save_pod_output(org_id, request["request_id"], out["evidence"]["record_id"], out)
    return agent.db.get_pod_output(org_id, request["request_id"]) or out

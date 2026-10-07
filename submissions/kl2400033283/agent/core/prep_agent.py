"""Prep Manager agent: a bounded, traced inspection loop.

    RECEIVE -> RESOLVE_REQUIREMENTS -> INGEST_IMAGES -> QUALITY_GATE -> ROUTE
            -> PERCEIVE (<= 1 model call, hard timeout) -> VERIFY_AND_JUDGE
            -> DECIDE -> SEAL_EVIDENCE -> PERSIST

What makes it an agent rather than a script:
* it works out *what to check* per unit (category rules x work order) and
  flags where the work order disagrees with Amazon's rules;
* it decides *whether and how to look* - skips the paid model call when no
  frame is usable and asks for a recapture instead; routes open-world photos
  to Claude vision and calibrated station frames to the deterministic engine;
* it refuses to over-claim: a deterministic verifier can veto the perception
  result, and UNCERTAIN is returned whenever evidence is insufficient;
* it never blocks the line: any fault or timeout fails open to a
  PENDING_REVIEW record with the capture preserved.
Every step is recorded in ``record.trace`` with its latency.
"""

import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from submissions.kl2400033283.agent.config import (
    ALLOWED_ORGS, ALLOW_PAID_MODELS, CV_ENGINE_VERSION, PERCEPTION_MODE, PERCEPTION_TIMEOUT_MS, RULES_VERSION,
)
from submissions.kl2400033283.agent.core import rules_engine
from submissions.kl2400033283.agent.core.overrides import direction as override_direction
from submissions.kl2400033283.agent.db.database import TenantAccessDeniedError, TenantDatabase
from submissions.kl2400033283.agent.rules.authoritative_rules import CHECK_KEYS, CHECK_TITLES, resolve_requirements
from submissions.kl2400033283.agent.schemas.evidence import (
    CheckResult, DispatchSignal, EvidenceRecord, ImageDimensions, ImageEvidence, OutcomeSummary,
    OverallDecisionEnum, OverrideEntry, PerceptionInfo, PrepInspectionInput, RecordStatusEnum,
    SubjectMetadata, TraceStep, VerdictEnum,
)
from submissions.kl2400033283.agent.vision.observations import UnitObservation, indeterminate
from submissions.kl2400033283.agent.vision.providers.claude_provider import ClaudeVisionProvider
from submissions.kl2400033283.agent.vision.providers.cv_provider import StationCVProvider
from submissions.kl2400033283.agent.vision.providers.ocr_provider import LocalOCRProvider
from submissions.kl2400033283.agent.vision.providers.free_vision_provider import FreeVisionProvider
from submissions.kl2400033283.agent.vision.providers.ollama_provider import OllamaVisionProvider
from submissions.kl2400033283.agent.vision.quality import assess_quality, load_image

log = logging.getLogger("prep_manager.agent")

# One small perception pool per tenant: a burst of slow free-model calls from one org can
# never starve another org's inspections (they would otherwise queue behind it and time out).
_POOLS: dict = {}
_POOLS_LOCK = threading.Lock()


def _pool_for(org_id: str) -> ThreadPoolExecutor:
    with _POOLS_LOCK:
        if org_id not in _POOLS:
            _POOLS[org_id] = ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"perception-{org_id}")
        return _POOLS[org_id]


_PATH_RE = re.compile(r"([A-Za-z]:)?[\\/][^\s'\"]*[\\/]([^\\/\s'\"]+)")


def _safe_message(exc: Exception) -> str:
    """Exception text without absolute filesystem paths (never leak server layout into evidence)."""
    return _PATH_RE.sub(lambda m: m.group(2), f"{type(exc).__name__}: {exc}")[:300]


class PerceptionTimeout(TimeoutError):
    pass


class _Tracer:
    def __init__(self):
        self.steps: List[TraceStep] = []
        self.t0 = time.perf_counter()

    def run(self, name: str, fn: Callable, detail: Callable = None):
        t = time.perf_counter()
        try:
            out = fn()
        except Exception as exc:
            self.steps.append(TraceStep(step=name, status="error", latency_ms=round((time.perf_counter() - t) * 1000, 2),
                                        detail=f"{type(exc).__name__}: {exc}"[:300]))
            raise
        self.steps.append(TraceStep(step=name, status="ok", latency_ms=round((time.perf_counter() - t) * 1000, 2),
                                    detail=(detail(out) if detail else "")[:300]))
        return out

    def note(self, name: str, status: str, detail: str):
        self.steps.append(TraceStep(step=name, status=status, latency_ms=0.0, detail=detail[:300]))

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.t0) * 1000, 2)


class PrepManagerAgent:
    def __init__(self, db: Optional[TenantDatabase] = None, cv: Optional[StationCVProvider] = None,
                 claude: Optional[ClaudeVisionProvider] = None, mode: str = PERCEPTION_MODE,
                 timeout_ms: int = PERCEPTION_TIMEOUT_MS, ocr: Optional[LocalOCRProvider] = None,
                 allow_paid: bool = ALLOW_PAID_MODELS, free_vision: Optional[FreeVisionProvider] = None,
                 ollama: Optional[OllamaVisionProvider] = None):
        self.db = db or TenantDatabase()
        self.cv = cv or StationCVProvider()
        self.claude = claude or ClaudeVisionProvider()
        self.ocr = ocr or LocalOCRProvider()
        self.allow_paid = allow_paid
        self.free_vision = free_vision or FreeVisionProvider(fallback=self.ocr)
        self.ollama = ollama or OllamaVisionProvider()
        self.mode = mode
        self.timeout_ms = timeout_ms
        self.model_calls = 0  # lifetime counter, used by tests to prove <= 1 call per unit

    # ------------------------------------------------------------------ routing
    def _claude_usable(self) -> bool:
        return self.allow_paid and self.claude.available

    def route(self, calibrated: bool):
        if self.mode == "cv":
            return self.cv, "Forced station CV (PREP_PERCEPTION=cv)."
        if self.mode == "claude":
            if not self._claude_usable():
                return self.cv, ("Claude requested but the free-only lock is on (PREP_ALLOW_PAID_MODELS!=1) "
                                 "or no key; fell back to station CV.")
            return self.claude, "Forced Claude vision (PREP_PERCEPTION=claude)."
        if self.mode == "free":
            if self.free_vision.available:
                return self.free_vision, f"Forced free vision model ({self.free_vision.model})."
            return self.ocr, "Free vision forced but OPENROUTER_API_KEY not set; using offline OCR."
        if self.mode == "ollama":
            if self.ollama.available:
                return self.ollama, "Forced local Ollama LLaVA vision (PREP_PERCEPTION=ollama)."
            return self.cv, "Ollama forced but local Ollama/LLaVA is unavailable; fell back to station CV."
        if self.mode == "ocr":
            if self.ocr.available:
                return self.ocr, "Forced local OCR (PREP_PERCEPTION=ocr)."
            return self.cv, "Local OCR forced but not installed; fell back to station CV."
        if calibrated:
            return self.cv, "Calibrated station frame: deterministic station CV (no model cost)."
        if self.ollama.available:
            return self.ollama, (f"Open-world photo: routed to local Ollama vision model {self.ollama.model} "
                                 "(offline, no external API).")
        if self._claude_usable():
            return self.claude, "Open-world photo (uncalibrated): routed to Claude vision (paid models enabled)."
        if self.free_vision.available:
            return self.free_vision, (f"Open-world photo: free vision model {self.free_vision.model} "
                                      "($0, OpenRouter free tier).")
        if self.ocr.available:
            return self.ocr, ("Open-world photo, free-only mode: offline local OCR + barcode decoding "
                              "(text-provable checks only).")
        return self.cv, "No vision model configured: station CV engine (best-effort on uncalibrated photo)."

    # ------------------------------------------------------------------ main loop
    def inspect(self, inp: PrepInspectionInput, fault: Optional[str] = None,
                record_id: Optional[str] = None, captured_at: Optional[str] = None,
                recorded_observation: Optional[UnitObservation] = None) -> EvidenceRecord:
        """``recorded_observation``: when no capture exists (Round 3 pod replaying Round 2 data), an
        operator-recorded observation is judged by the same rules engine. It is labelled as such in
        the record; it is never presented as vision."""
        if inp.org_id not in ALLOWED_ORGS:
            raise TenantAccessDeniedError(f"Unknown tenant: {inp.org_id}")

        tr = _Tracer()
        captured_at = captured_at or datetime.now(timezone.utc).isoformat()
        record_id = record_id or f"PRP-{inp.unit_id.replace('UNIT-', '')}-{uuid.uuid4().hex[:8]}"
        tr.note("RECEIVE", "ok", f"unit={inp.unit_id} images={len(inp.image_paths)} category={inp.category}")

        plan = tr.run("RESOLVE_REQUIREMENTS", lambda: self._plan(inp),
            lambda p: f"{sum(r.required for r in p.requirements.values())} checks required, "
                      f"{len(p.discrepancies)} work-order discrepancies, {len(p.attestations)} attestations")

        images: List[ImageEvidence] = []
        perception: Optional[PerceptionInfo] = None
        try:
            loaded = tr.run("INGEST_IMAGES", lambda: [load_image(Path(p)) for p in inp.image_paths],
                            lambda l: f"{len(l)} image(s) hashed")
            qualities = tr.run("QUALITY_GATE", lambda: [assess_quality(i) for i in loaded],
                               lambda qs: "; ".join(f"view{n}: {'usable' if q.usable else 'UNUSABLE'} {q.issues or ''}"
                                                    for n, q in enumerate(qs)))
            for n, (img, q) in enumerate(zip(loaded, qualities)):
                images.append(ImageEvidence(
                    view=["front", "back", "label_detail", "extra"][n],
                    file_path=img.path.name,
                    asset_id=inp.image_asset_ids[n] if n < len(inp.image_asset_ids) else None,
                    sha256_digest=img.sha256,
                    dimensions=ImageDimensions(width=img.original_size[0], height=img.original_size[1]),
                    quality=q))

            provider, why = self.route(inp.station_calibrated)
            # The station CV engine is validated only on calibrated gantry frames; elsewhere it may
            # point at things but not decide them.
            in_domain = not (provider is self.cv and not inp.station_calibrated)
            if not in_domain:
                why += " OUT OF DOMAIN: findings downgraded to UNCERTAIN."

            usable = [q for q in qualities if q.usable]
            if not loaded and recorded_observation is not None:
                why = "No capture supplied: judging the operator-recorded observation with the rules engine."
                tr.note("ROUTE", "ok", why)
                observation = recorded_observation
                in_domain = True  # no perception engine involved; the rules engine judges a recorded state
                usable = [True]
                loaded = [None]
            elif not loaded:
                tr.note("ROUTE", "skipped", "No images supplied: nothing to perceive.")
                observation = UnitObservation(provider="none", model_version="n/a",
                                              checks={k: indeterminate(k, "No images supplied.") for k in CHECK_KEYS})
            elif not usable:
                tr.note("ROUTE", "skipped", "Every frame failed the quality gate: model call skipped (saves cost); recapture requested.")
                issues = sorted({i for q in qualities for i in q.issues})
                observation = UnitObservation(provider="quality_gate", model_version=CV_ENGINE_VERSION, checks={
                    k: indeterminate(k, f"Image unusable ({', '.join(issues)}); recapture required.") for k in CHECK_KEYS})
            else:
                tr.note("ROUTE", "ok", f"{provider.name}: {why}")
                observation = tr.run("PERCEIVE", lambda: self._perceive(provider, loaded, qualities, inp, fault),
                                     lambda o: f"{o.provider} calls={o.model_calls} cost=${o.cost_usd:.5f}")
                self._measure_region_glare(observation, loaded)
            perception = PerceptionInfo(provider=observation.provider, model_version=observation.model_version,
                                        model_calls=observation.model_calls, cost_usd=observation.cost_usd,
                                        routing_reason=((why + " " + " ".join(observation.raw_notes)).strip()[:400]
                                                        if loaded and usable else "Perception skipped."))

            model_ms = int(next((s.latency_ms for s in tr.steps if s.step == "PERCEIVE"), 0))
            checks = tr.run("VERIFY_AND_JUDGE", lambda: rules_engine.judge(
                plan, observation, qualities, observation.model_version, model_ms, in_domain),
                lambda cs: ", ".join(f"{c.check_key}={c.verdict.value}" for c in cs))
            decision, dispatch, summary, actions = tr.run(
                "DECIDE", lambda: rules_engine.decide(checks, plan), lambda d: f"{d[0].value} -> {d[1].value}")
            status = RecordStatusEnum.COMPLETED
        except Exception as exc:  # FAIL OPEN (Engineering Rule 3): the line never waits
            log.warning("fail-open on %s: %s", inp.unit_id, exc)
            reason = "SYSTEM_TIMEOUT" if isinstance(exc, PerceptionTimeout) else "SYSTEM_FAIL_OPEN"
            checks = [CheckResult(check_key=k, title=CHECK_TITLES[k], verdict=VerdictEnum.UNCERTAIN, confidence=0.0,
                                  detail=f"Fail-open: {_safe_message(exc)}", reason_code=reason,
                                  remediation="Manual inspection required (system fault).")
                      for k in CHECK_KEYS]
            decision, dispatch = OverallDecisionEnum.PENDING_REVIEW, DispatchSignal.AMBER_REVIEW
            summary = f"{reason}: unit released to PENDING_REVIEW; capture preserved, line not stopped."
            actions = ["Re-inspect this unit at the review bench."]
            status = RecordStatusEnum.FAILED_OPEN
            if perception is None:
                perception = PerceptionInfo(provider="fail_open", model_version="n/a", model_calls=0,
                                            cost_usd=0.0, routing_reason=reason)

        record = EvidenceRecord(
            record_id=record_id, organization_id=inp.org_id, client_id=inp.client_id,
            subject=SubjectMetadata(unit_id=inp.unit_id, sku=inp.sku, asin=inp.asin, fnsku=inp.fnsku,
                                    work_order_id=inp.work_order_id, fba_shipment_id=inp.fba_shipment_id,
                                    category=inp.category),
            captured_at=captured_at, operator_label=inp.operator_id, images=images, checks=checks,
            outcome=OutcomeSummary(decision=decision, decided_at=datetime.now(timezone.utc).isoformat(),
                                   summary=summary, dispatch=dispatch, action_items=actions),
            status=status, rules_version=RULES_VERSION,
            requirements=[asdict(r) for r in plan.requirements.values()],
            attestations=[asdict(a) for a in plan.attestations],
            discrepancies=[asdict(d) for d in plan.discrepancies],
            perception=perception,
        )
        tr.note("SEAL_EVIDENCE", "ok", "SHA-256 over canonical record")
        record.trace = tr.steps
        record.total_latency_ms = tr.elapsed_ms
        record.content_hash = record.compute_content_hash()
        try:
            self.db.save_new_record(record)
        except TenantAccessDeniedError:
            raise
        except Exception as exc:  # persistence fault must not block the line - but must not be hidden either
            log.error("persist failed for %s: %s", record_id, _safe_message(exc))
            record.persisted = False
            try:
                self.db.spool(record)
                record.trace.append(TraceStep(step="PERSIST", status="error", latency_ms=0.0,
                                              detail="Database write failed; record spooled to disk for replay."))
            except Exception as exc2:
                log.error("spool failed for %s: %s", record_id, _safe_message(exc2))
        return record

    def _perceive(self, provider, loaded, qualities, inp: PrepInspectionInput, fault: Optional[str]) -> UnitObservation:
        if fault == "provider_error":
            raise ConnectionError("Vision service unavailable (HTTP 503) [simulated]")
        # Blind read: the expected FNSKU is NOT given to the model (it would just echo it back).
        # The rules engine compares what was read with the work order.
        context = {"category": inp.category}

        budget_ms = self.timeout_ms if fault else getattr(provider, "timeout_ms", self.timeout_ms)

        def call():
            if fault == "timeout":
                time.sleep(budget_ms / 1000.0 + 0.2)
            return provider.observe(loaded, qualities, inp.station_calibrated, context=context)

        future = _pool_for(inp.org_id).submit(call)
        try:
            obs = future.result(timeout=budget_ms / 1000.0)
        except FutureTimeout:
            raise PerceptionTimeout(f"Perception exceeded {budget_ms} ms budget")
        self.model_calls += obs.model_calls
        if obs.model_calls > 1:
            raise RuntimeError("Budget violation: more than one model call for a unit")
        return obs

    @staticmethod
    def _measure_region_glare(observation: UnitObservation, loaded) -> None:
        """For model providers: sensor-clipped % inside each evidence box the model pointed to.

        Deterministic, independent of the model; the rules engine uses it to veto 'clean' claims
        only when glare actually covers the evidence.
        """
        if observation.provider in ("station_cv", "local_ocr", "quality_gate", "none"):
            return
        for obs in observation.checks.values():
            worst = None
            for r in obs.regions:
                if r.view_index >= len(loaded):
                    continue
                img = loaded[r.view_index]
                h, w = img.gray.shape
                x0, y0, x1, y1 = (int(r.bbox[0] * w), int(r.bbox[1] * h), int(r.bbox[2] * w), int(r.bbox[3] * h))
                if x1 - x0 < 4 or y1 - y0 < 4:
                    continue
                patch = img.rgb[max(0, y0):y1, max(0, x0):x1]
                pct = float((patch.min(axis=2) >= 253).mean() * 100.0)
                worst = pct if worst is None else max(worst, pct)
            if worst is not None:
                obs.measurements["region_glare_pct"] = round(worst, 2)

    @staticmethod
    def _plan(inp: PrepInspectionInput):
        plan = resolve_requirements(
            inp.category, inp.wo_polybag, inp.wo_suffocation_warning, inp.wo_expiry_date, inp.wo_handling_marks,
            inp.bag_length_in, inp.bag_width_in, inp.bag_opening_in, inp.polybag_spec_mil)
        if inp.fnsku and inp.fnsku.upper() not in ("UNKNOWN", ""):
            plan.requirements["fnsku_label_placement"].params["expected_fnsku"] = inp.fnsku.upper()
        return plan

    # ------------------------------------------------------------------ overrides
    def apply_override(self, org_id: str, record_id: str, check_key: str, new_verdict: str,
                       reason: str, operator_id: str, role: str = "operator",
                       expected_content_hash: Optional[str] = None) -> EvidenceRecord:
        """Append an override. Relaxing a verdict (e.g. FAIL->PASS) needs the supervisor role."""
        if not reason or len(reason.strip()) < 4:
            raise ValueError("Override rejected: a reason (>= 4 characters) is mandatory.")
        if check_key not in CHECK_KEYS:
            raise ValueError(f"Unknown check_key '{check_key}'.")
        verdict = VerdictEnum(new_verdict.upper())
        record = self.db.get_evidence_record(org_id, record_id)
        if record is None:
            raise TenantAccessDeniedError(f"Record {record_id} not found for tenant {org_id}")
        original = next(c.verdict for c in record.checks if c.check_key == check_key)
        if original == verdict:
            raise ValueError(f"'{check_key}' is already {verdict.value}; nothing to override.")
        way = override_direction(original, verdict)
        if way == "relax" and role != "supervisor":
            raise OverridePermissionError(
                f"Relaxing {original.value} -> {verdict.value} needs a supervisor key; operators may only tighten.")
        entry = OverrideEntry(check_key=check_key, original_verdict=original, new_verdict=verdict,
                              reason=reason.strip(), operator_id=operator_id, role=role, direction=way,
                              overridden_at=datetime.now(timezone.utc).isoformat())
        return self.db.record_override(org_id, record_id, entry, expected_content_hash=expected_content_hash)


class OverridePermissionError(PermissionError):
    """The caller's role may not make this change."""

"""Deterministic override application + keyed seals.

The same functions are used when an override is stored and when ``/verify`` replays the chain,
so the chain is reproducible: original record -> override 1 -> override 2 ... and every
intermediate content hash must match its seal.

Seal = HMAC-SHA256(SEAL_KEY, "org|record|seq|kind|content_hash|prev_mac"). The key is held
outside the database (config.SEAL_KEY), so editing a row and recomputing the plain SHA-256 no
longer produces a valid seal.
"""

import hashlib
import hmac
from typing import Optional

from submissions.kl2400033283.agent.config import SEAL_KEY, SEAL_KEY_ID
from submissions.kl2400033283.agent.schemas.evidence import (
    DispatchSignal, EvidenceRecord, OverallDecisionEnum, OverrideEntry, RecordStatusEnum, VerdictEnum,
)

# How strict each verdict is. Moving to a less strict verdict "relaxes" the agent's judgment.
_STRICTNESS = {VerdictEnum.FAIL: 3, VerdictEnum.UNCERTAIN: 2, VerdictEnum.PASS: 1, VerdictEnum.NOT_REQUIRED: 0}


def direction(original: VerdictEnum, new: VerdictEnum) -> str:
    return "relax" if _STRICTNESS[new] < _STRICTNESS[original] else "tighten"


def apply_override(record: EvidenceRecord, entry: OverrideEntry) -> EvidenceRecord:
    """Return a NEW record with the override applied. Never mutates the input."""
    rec = record.model_copy(deep=True)
    entry = entry.model_copy(deep=True)
    entry.previous_content_hash = rec.content_hash
    for ch in rec.checks:
        if ch.check_key == entry.check_key:
            ch.verdict = entry.new_verdict
    verdicts = [c.verdict for c in rec.checks]
    if VerdictEnum.FAIL in verdicts:
        rec.outcome.decision, rec.outcome.dispatch = OverallDecisionEnum.FAIL, DispatchSignal.RED_REWORK
    elif VerdictEnum.UNCERTAIN in verdicts:
        rec.outcome.decision, rec.outcome.dispatch = OverallDecisionEnum.UNCERTAIN, DispatchSignal.AMBER_REVIEW
    else:
        rec.outcome.decision, rec.outcome.dispatch = OverallDecisionEnum.PASS, DispatchSignal.GREEN_RELEASE
    rec.outcome.decided_by = f"{entry.role}:{entry.operator_id}"
    rec.outcome.decided_at = entry.overridden_at
    rec.status = RecordStatusEnum.OVERRIDDEN
    rec.overrides.append(entry)
    rec.seal = None
    rec.persisted = None
    rec.content_hash = rec.compute_content_hash()
    rec.overrides[-1].new_content_hash = rec.content_hash
    return rec


def make_mac(org_id: str, record_id: str, seq: int, kind: str, content_hash: str, prev_mac: str) -> str:
    msg = f"{org_id}|{record_id}|{seq}|{kind}|{content_hash}|{prev_mac}".encode("utf-8")
    return hmac.new(SEAL_KEY, msg, hashlib.sha256).hexdigest()


def check_mac(org_id: str, record_id: str, seq: int, kind: str, content_hash: str, prev_mac: str, mac: str) -> bool:
    return hmac.compare_digest(make_mac(org_id, record_id, seq, kind, content_hash, prev_mac), mac or "")


def seal_info(seq: int, kind: str, mac: str) -> dict:
    return {"seq": seq, "kind": kind, "mac": mac, "key_id": SEAL_KEY_ID, "algorithm": "HMAC-SHA256"}


def latest(prev: Optional[dict]) -> str:
    return prev["mac"] if prev else ""

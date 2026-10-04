"""Core Prep Manager Agent State Machine with Fail-Open Circuit Breaker.

Enforces Engineering Rule 3: 'Fail open. A model error or timeout still saves
the capture and still produces a record, marked pending. Nothing blocks the operator.'
"""

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from submissions.kl2400033283.agent.config import (
    MAX_VISION_LATENCY_MS,
    ALLOWED_ORGS,
    DEFAULT_MODEL_VERSION
)
from submissions.kl2400033283.agent.schemas.evidence import (
    PrepInspectionInput,
    EvidenceRecord,
    CheckResult,
    VerdictEnum,
    OverallDecisionEnum,
    RecordStatusEnum,
    SubjectMetadata,
    OutcomeSummary,
    OverrideEntry,
    ImageEvidence,
    ImageDimensions
)
from submissions.kl2400033283.agent.db.database import TenantDatabase, TenantAccessDeniedError
from submissions.kl2400033283.agent.vision.pipeline import BatchedPrepVisionPipeline

class CircuitBreakerTimeoutError(TimeoutError):
    """Raised when the vision pipeline exceeds the real-time warehouse latency budget."""
    pass

class PrepManagerAgent:
    """Production visual compliance agent for prep center inbound inspection."""

    def __init__(self, db: Optional[TenantDatabase] = None, vision_pipeline: Optional[BatchedPrepVisionPipeline] = None):
        self.db = db or TenantDatabase()
        self.vision = vision_pipeline or BatchedPrepVisionPipeline()

    def process_unit(self, input_data: PrepInspectionInput, force_simulate_failure: bool = False, force_simulate_timeout: bool = False) -> EvidenceRecord:
        """Inspects a prepared product unit with fail-open guarantees."""
        start_time = time.perf_counter()
        captured_at = datetime.now(timezone.utc).isoformat()
        
        # Enforce tenancy isolation check upfront
        if input_data.org_id not in ALLOWED_ORGS:
            raise TenantAccessDeniedError(f"Access denied for unauthorized tenant: {input_data.org_id}")

        record_id = f"PRP-{input_data.unit_id.replace('UNIT-', '')}"

        # -------------------------------------------------------------
        # Execution with Fail-Open Circuit Breaker
        # -------------------------------------------------------------
        try:
            if force_simulate_timeout:
                time.sleep(0.01)
                raise CircuitBreakerTimeoutError(f"Model processing latency exceeded {MAX_VISION_LATENCY_MS}ms budget")
            
            if force_simulate_failure:
                raise ConnectionError("Upstream multimodal vision service unavailable (HTTP 503)")

            # Batched model call (Rule 2)
            checks, overall_decision, summary, latency_ms, image_evidences = self.vision.inspect_unit_batched(input_data)
            status = RecordStatusEnum.COMPLETED

        except Exception as exc:
            # FAIL-OPEN HANDLER (Rule 3)
            # The line NEVER waits. Create a pending record, allow physical flow, log fallback.
            checks = [
                CheckResult(
                    check_key=key,
                    verdict=VerdictEnum.UNCERTAIN,
                    confidence=0.0,
                    detail=f"Fail-open fallback: {type(exc).__name__}: {str(exc)}",
                    model_version=DEFAULT_MODEL_VERSION,
                    latency_ms=int((time.perf_counter() - start_time) * 1000)
                )
                for key in [
                    "polybag_present_sealed", "suffocation_warning", "fnsku_label_placement",
                    "original_barcode_covered", "expiry_date", "handling_marks"
                ]
            ]
            overall_decision = OverallDecisionEnum.PENDING_REVIEW
            summary = f"SYSTEM_FAIL_OPEN: {type(exc).__name__}. Unit cleared downstream with PENDING_REVIEW status to avoid warehouse line stoppage."
            status = RecordStatusEnum.FAILED_OPEN
            image_evidences = [
                ImageEvidence(
                    view="front",
                    file_path=input_data.image_paths[0] if input_data.image_paths else f"fixtures/prep/{input_data.unit_id}_front.jpg",
                    sha256_digest="fail_open_cached_digest",
                    dimensions=ImageDimensions(width=1920, height=1080)
                )
            ]

        # Construct Subject Metadata
        subject = SubjectMetadata(
            unit_id=input_data.unit_id,
            sku=input_data.sku,
            asin=input_data.asin,
            fnsku=input_data.fnsku,
            work_order_id=input_data.work_order_id,
            fba_shipment_id=input_data.fba_shipment_id
        )

        # Construct Outcome Summary
        outcome = OutcomeSummary(
            decision=overall_decision,
            decided_by="agent_02_prep",
            decided_at=datetime.now(timezone.utc).isoformat(),
            summary=summary
        )

        # Construct Full Evidence Record
        record = EvidenceRecord(
            record_id=record_id,
            schema_version="2026.1",
            organization_id=input_data.org_id,
            client_id="seller_nexus_commerce",
            subject=subject,
            captured_at=captured_at,
            operator_label=input_data.operator_id,
            images=image_evidences,
            checks=checks,
            outcome=outcome,
            overrides=[],
            status=status
        )

        # Calculate cryptographic SHA-256 digest
        record.content_hash = record.compute_content_hash()

        # Persist to tenant database
        self.db.save_evidence_record(record)

        return record

    def apply_override(
        self,
        org_id: str,
        record_id: str,
        check_key: str,
        new_verdict_str: str,
        reason: str,
        operator_id: str
    ) -> EvidenceRecord:
        """Records an operator override with mandatory reason code (Engineering Honesty Rule)."""
        if not reason or reason.strip() == "":
            raise ValueError("Override rejected: mandatory reason code is required.")

        record = self.db.get_evidence_record(org_id, record_id)
        if not record:
            raise TenantAccessDeniedError(f"Record {record_id} not found in tenant {org_id}")

        # Find original verdict
        orig_verdict = VerdictEnum.UNCERTAIN
        for c in record.checks:
            if c.check_key == check_key:
                orig_verdict = c.verdict
                break

        new_verdict = VerdictEnum(new_verdict_str.upper())
        override_entry = OverrideEntry(
            check_key=check_key,
            original_verdict=orig_verdict,
            new_verdict=new_verdict,
            reason=reason.strip(),
            operator_id=operator_id,
            overridden_at=datetime.now(timezone.utc).isoformat()
        )

        updated_record = self.db.record_override(org_id, record_id, override_entry)
        return updated_record

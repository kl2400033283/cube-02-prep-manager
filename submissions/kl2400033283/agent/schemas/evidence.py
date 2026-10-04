"""Pydantic data models for Prep Manager evidence contracts and validation."""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class VerdictEnum(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"
    NOT_REQUIRED = "NOT_REQUIRED"

class OverallDecisionEnum(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"
    PENDING_REVIEW = "PENDING_REVIEW"

class RecordStatusEnum(str, Enum):
    COMPLETED = "completed"
    PENDING = "pending"
    OVERRIDDEN = "overridden"
    FAILED_OPEN = "failed_open"

class ImageDimensions(BaseModel):
    width: int
    height: int

class ImageEvidence(BaseModel):
    view: str = Field(..., description="front, back, label_detail, etc.")
    file_path: str
    sha256_digest: str
    dimensions: ImageDimensions

class CheckResult(BaseModel):
    check_key: str
    verdict: VerdictEnum
    confidence: float = Field(..., ge=0.0, le=1.0)
    detail: str
    evidence_metadata: Dict[str, Any] = Field(default_factory=dict)
    model_version: str = "prep-vision-hybrid-v2.6"
    latency_ms: int = 0

class OverrideEntry(BaseModel):
    check_key: str
    original_verdict: VerdictEnum
    new_verdict: VerdictEnum
    reason: str
    operator_id: str
    overridden_at: str

class AgentMetadata(BaseModel):
    agent_id: str = "agent_02_prep"
    agent_name: str = "Prep Manager"
    version: str = "1.2.0"
    stage: int = 2

class SubjectMetadata(BaseModel):
    unit_id: str
    sku: str
    asin: str
    fnsku: str
    work_order_id: str
    fba_shipment_id: str

class OutcomeSummary(BaseModel):
    decision: OverallDecisionEnum
    decided_by: str = "agent_02_prep"
    decided_at: str
    summary: str

class EvidenceRecord(BaseModel):
    record_id: str
    schema_version: str = "2026.1"
    organization_id: str
    client_id: str
    agent: AgentMetadata = Field(default_factory=AgentMetadata)
    subject: SubjectMetadata
    captured_at: str
    operator_label: str
    images: List[ImageEvidence]
    checks: List[CheckResult]
    outcome: OutcomeSummary
    overrides: List[OverrideEntry] = Field(default_factory=list)
    status: RecordStatusEnum = RecordStatusEnum.COMPLETED
    content_hash: str = ""

    def compute_content_hash(self) -> str:
        """Computes the canonical SHA-256 hash across verifiable fields."""
        canonical_dict = {
            "record_id": self.record_id,
            "unit_id": self.subject.unit_id,
            "organization_id": self.organization_id,
            "images": [img.sha256_digest for img in self.images],
            "checks": [{c.check_key: c.verdict.value} for c in self.checks],
            "outcome": self.outcome.decision.value,
            "captured_at": self.captured_at
        }
        serialized = json.dumps(canonical_dict, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        """Verifies that the content hash matches the stored payload."""
        expected = self.compute_content_hash()
        return self.content_hash == expected

class PrepInspectionInput(BaseModel):
    unit_id: str
    org_id: str
    work_order_id: str
    fba_shipment_id: str
    sku: str
    asin: str
    fnsku: str
    prep_price_usd: float = 0.50
    operator_id: str = "op_default"
    # Work order flags
    wo_polybag: bool = False
    wo_suffocation_warning: bool = False
    wo_expiry_date: bool = False
    wo_handling_marks: Optional[str] = None
    # Image file paths
    image_paths: List[str] = Field(default_factory=list)
    # Simulation / synthetic testing overrides
    test_mode_features: Optional[Dict[str, Any]] = None

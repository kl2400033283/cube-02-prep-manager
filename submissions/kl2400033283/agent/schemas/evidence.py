"""Evidence contract (CUBE fixed contract + Prep Manager extensions).

Contract fields required by the handbook: record_id, schema_version,
organization_id, client_id, agent, subject, captured_at, operator_label,
images, checks[] (check_key, verdict, confidence, detail, model_version,
latency_ms), outcome (decision, decided_by, decided_at), overrides[], status,
content_hash. Everything else is additive so downstream agents that only
know the base contract keep working.
"""

import hashlib
import json
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from submissions.kl2400033283.agent.config import AGENT_VERSION, SCHEMA_VERSION

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,63}$"


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
    OVERRIDDEN = "overridden"
    FAILED_OPEN = "failed_open"


class DispatchSignal(str, Enum):
    GREEN_RELEASE = "GREEN_RELEASE"      # ship onward
    RED_REWORK = "RED_REWORK"            # pull for rework
    AMBER_REVIEW = "AMBER_REVIEW"        # human review / recapture, line keeps moving


class ImageDimensions(BaseModel):
    width: int
    height: int


class ImageQuality(BaseModel):
    sharpness: float = Field(..., description="99.9th percentile |Laplacian| (edge strength); low = blur")
    glare_pct: float = Field(..., description="% of pixels clipped at sensor max")
    exposure_mean: float = Field(..., description="Mean luminance 0-255")
    usable: bool
    issues: List[str] = Field(default_factory=list)


class ImageEvidence(BaseModel):
    view: str
    file_path: str = Field(..., description="Storage reference (never served directly)")
    asset_id: Optional[str] = None
    sha256_digest: str
    dimensions: ImageDimensions
    quality: Optional[ImageQuality] = None


class Region(BaseModel):
    """Where on which image the evidence for a check was found. Normalised 0-1."""
    view_index: int = 0
    label: str
    bbox: List[float] = Field(..., min_length=4, max_length=4)


class CheckResult(BaseModel):
    check_key: str
    title: str = ""
    verdict: VerdictEnum
    confidence: float = Field(..., ge=0.0, le=1.0)
    detail: str
    reason_code: str = ""
    rule_ids: List[str] = Field(default_factory=list)
    required_by: List[str] = Field(default_factory=list)
    observed_state: str = ""
    measurements: Dict[str, Any] = Field(default_factory=dict)
    regions: List[Region] = Field(default_factory=list)
    remediation: Optional[str] = None
    model_version: str = ""
    latency_ms: int = 0


class OverrideEntry(BaseModel):
    check_key: str
    original_verdict: VerdictEnum
    new_verdict: VerdictEnum
    reason: str
    operator_id: str
    overridden_at: str
    role: str = "operator"                 # from the credential, never from the request body
    direction: str = "tighten"             # tighten (stricter) | relax (needs supervisor)
    previous_content_hash: str = ""
    new_content_hash: str = ""


class AgentMetadata(BaseModel):
    agent_id: str = "agent_02_prep"
    agent_name: str = "Prep Manager"
    version: str = AGENT_VERSION
    stage: int = 2


class PerceptionInfo(BaseModel):
    provider: str
    model_version: str
    model_calls: int
    cost_usd: float
    routing_reason: str


class TraceStep(BaseModel):
    step: str
    status: str            # ok | skipped | degraded | error
    latency_ms: float
    detail: str = ""


class SubjectMetadata(BaseModel):
    unit_id: str
    sku: str
    asin: str
    fnsku: str
    work_order_id: str
    fba_shipment_id: str
    category: str = "general"


class OutcomeSummary(BaseModel):
    decision: OverallDecisionEnum
    decided_by: str = "agent_02_prep"
    decided_at: str
    summary: str
    dispatch: DispatchSignal = DispatchSignal.AMBER_REVIEW
    action_items: List[str] = Field(default_factory=list)


class EvidenceRecord(BaseModel):
    record_id: str
    schema_version: str = SCHEMA_VERSION
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
    # Prep Manager extensions
    rules_version: str = ""
    requirements: List[Dict[str, Any]] = Field(default_factory=list)
    attestations: List[Dict[str, Any]] = Field(default_factory=list)
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)
    perception: Optional[PerceptionInfo] = None
    trace: List[TraceStep] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    content_hash: str = ""
    # Storage annotations - NOT part of the hashed content.
    seal: Optional[Dict[str, Any]] = None      # {seq, kind, mac, key_id}: keyed HMAC held outside the DB
    persisted: Optional[bool] = None           # False if the store failed and the record was spooled

    def canonical_payload(self) -> str:
        """Every field except the hash and storage annotations, serialised deterministically."""
        data = self.model_dump(mode="json", exclude={"content_hash", "seal", "persisted"})
        # An override's resulting hash cannot be part of the content it hashes.
        for o in data.get("overrides", []):
            o.pop("new_content_hash", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def compute_content_hash(self) -> str:
        return hashlib.sha256(self.canonical_payload().encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        return bool(self.content_hash) and self.content_hash == self.compute_content_hash()


class PrepInspectionInput(BaseModel):
    """Internal agent input. The public API builds this; it never takes raw paths from clients."""
    model_config = ConfigDict(extra="forbid")

    unit_id: str = Field(..., pattern=ID_PATTERN)
    org_id: str = Field(..., pattern=ID_PATTERN)
    work_order_id: str = Field("WO-UNSPECIFIED", pattern=ID_PATTERN)
    fba_shipment_id: str = Field("FBA-UNSPECIFIED", pattern=ID_PATTERN)
    sku: str = Field("SKU-UNSPECIFIED", max_length=64)
    asin: str = Field("UNKNOWN", max_length=20)
    fnsku: str = Field("UNKNOWN", max_length=20)
    operator_id: str = Field("op_default", pattern=ID_PATTERN)
    client_id: str = Field("client_default", pattern=ID_PATTERN)

    # Product information
    category: str = "general"
    bag_length_in: Optional[float] = Field(None, gt=0, le=120)
    bag_width_in: Optional[float] = Field(None, gt=0, le=120)
    bag_opening_in: Optional[float] = Field(None, gt=0, le=120)
    polybag_spec_mil: Optional[float] = Field(None, gt=0, le=20)

    # Work order (what the prep center intended)
    wo_polybag: bool = False
    wo_suffocation_warning: bool = False
    wo_expiry_date: bool = False
    wo_handling_marks: List[str] = Field(default_factory=list, max_length=6)

    station_calibrated: bool = Field(False, description="Frame comes from the calibrated station gantry (known px/in)")
    image_paths: List[str] = Field(default_factory=list, max_length=4)
    image_asset_ids: List[Optional[str]] = Field(default_factory=list, max_length=4)

"""Perception output contract.

Perception providers report *what they saw*, never verdicts. The rules engine
alone turns observations into PASS/FAIL/UNCERTAIN. This separation is the main
defence against a model inventing compliance rules or being talked into a
verdict by text printed on a package (prompt injection through the image).
"""

from typing import Dict, List, Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from submissions.kl2400033283.agent.schemas.evidence import Region

# Allowed observed states per check. Anything else is rejected at validation.
OBSERVED_STATES: Dict[str, List[str]] = {
    "polybag_present_sealed": ["SEALED", "UNSEALED", "ABSENT", "SEAL_NOT_VISIBLE", "INDETERMINATE"],
    "suffocation_warning": ["LEGIBLE", "OBSCURED", "ABSENT", "INDETERMINATE"],
    "fnsku_label_placement": ["FLAT", "ON_SEAM", "ON_CURVE", "ON_EDGE", "ABSENT", "INDETERMINATE"],
    "original_barcode_covered": ["COVERED", "EXPOSED", "INDETERMINATE"],
    "expiry_date": ["LEGIBLE", "OCCLUDED", "ILLEGIBLE", "ABSENT", "INDETERMINATE"],
    "handling_marks": ["DETECTED", "INDETERMINATE"],
}


class CheckObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_key: str
    state: str
    signal: float = Field(0.5, ge=0.0, le=1.0, description="Detection strength / margin, 0-1")
    measurements: Dict[str, Any] = Field(default_factory=dict)
    regions: List[Region] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    def is_valid_state(self) -> bool:
        return self.state in OBSERVED_STATES.get(self.check_key, [])


class UnitObservation(BaseModel):
    provider: str
    model_version: str
    checks: Dict[str, CheckObservation]
    model_calls: int = 0
    cost_usd: float = 0.0
    raw_notes: List[str] = Field(default_factory=list)

    def get(self, check_key: str) -> Optional[CheckObservation]:
        return self.checks.get(check_key)


def indeterminate(check_key: str, note: str) -> CheckObservation:
    return CheckObservation(check_key=check_key, state="INDETERMINATE", signal=0.0, notes=[note])


def remap_views(observation: "UnitObservation", qualities) -> "UnitObservation":
    """Model providers see only the usable frames, numbered 0..n-1. Map each region's view_index
    back to the index of the original capture so evidence boxes point at the right image."""
    usable = [i for i, q in enumerate(qualities) if q.usable]
    for obs in observation.checks.values():
        for r in obs.regions:
            if 0 <= r.view_index < len(usable):
                r.view_index = usable[r.view_index]
    return observation

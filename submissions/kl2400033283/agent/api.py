"""Prep Manager REST API (v1) + operator console.

Run:  uvicorn submissions.kl2400033283.agent.api:app --port 8000
Docs: http://localhost:8000/docs  (OpenAPI, try-it-out)

Auth: every /api/v1 route except health, agent card, rules, categories and
scenario thumbnails needs ``X-API-Key``; the key decides the tenant.
"""

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
import pydantic.json_schema

# Python 3.9 compatibility for pydantic json schema generation
try:
    def _flat_literals(ann):
        for a in getattr(ann, '__args__', []):
            if hasattr(a, '__args__'):
                yield from _flat_literals(a)
            else:
                yield a
    _types = list(_flat_literals(pydantic.json_schema.CoreSchemaOrFieldType))
    if _types:
        pydantic.json_schema.GenerateJsonSchema.build_schema_type_to_method = (
            lambda self: {k: getattr(self, k.replace('-', '_') + '_schema') for k in _types}
        )
except Exception:
    pass

from submissions.kl2400033283.agent.config import (
    AGENT_VERSION, ALLOWED_ORGS, CLAUDE_MODEL, CORS_ORIGINS, DEMO_KEYS_ACTIVE, EVAL_RESULTS_PATH,
    PERCEPTION_MODE, PERCEPTION_TIMEOUT_MS, RULES_VERSION, SCENARIO_DIR, SCHEMA_VERSION,
    SIGNING_SECRET_EPHEMERAL, CV_ENGINE_VERSION, SEAL_KEY_ID, MAX_UPLOAD_BYTES,
)
from submissions.kl2400033283.agent import pod_adapter
from submissions.kl2400033283.agent.core.prep_agent import OverridePermissionError, PrepManagerAgent
from submissions.kl2400033283.agent.db.database import ConcurrentOverrideError, TenantAccessDeniedError, TenantDatabase
from submissions.kl2400033283.agent.rules.authoritative_rules import (
    CATEGORY_PROFILES, CHECK_TITLES, HANDLING_MARKS, RULES, rules_catalog,
)
from submissions.kl2400033283.agent.schemas.evidence import ID_PATTERN, EvidenceRecord, PrepInspectionInput, VerdictEnum
from submissions.kl2400033283.agent.security import (
    SECURITY_HEADERS, Principal, read_limited, require_principal, require_tenant, sign_asset,
    validate_image_upload, verify_asset_signature,
)
from submissions.kl2400033283.agent.contract_validation import errors as pod_contract_errors
from submissions.kl2400033283.agent.sim.scenarios import BY_ID as SCENARIOS_BY_ID, SCENARIOS

log = logging.getLogger("prep_manager.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

AGENT_CARD = {
    "name": "Prep Manager",
    "agent_id": "agent_02_prep",
    "tagline": "Visual prep-compliance inspector for Amazon FBA inbound units.",
    "description": [
        "Prep Manager photographs a prepared unit and verifies, check by check, that its polybag, suffocation "
        "warning, FNSKU label, barcode coverage, expiry date and handling marks meet Amazon's published prep rules.",
        "Every verdict is PASS, FAIL or an honest UNCERTAIN, backed by pixel evidence, a cited rule and a "
        "keyed-seal (HMAC) record that a downstream claims agent can verify months later.",
    ],
    "version": AGENT_VERSION,
    "schema_version": SCHEMA_VERSION,
    "rules_version": RULES_VERSION,
    "checks": CHECK_TITLES,
}

TAGS = [
    {"name": "agent", "description": "Agent card, health, rules registry"},
    {"name": "inspection", "description": "Run inspections and upload captures"},
    {"name": "evidence", "description": "Evidence records, integrity, overrides, dispute packets"},
    {"name": "analytics", "description": "Live metrics and offline evaluation results"},
    {"name": "resilience", "description": "Fail-open drills and tenancy audit"},
    {"name": "round3", "description": "CUBE Round 3 pod contract: GET /health, POST /run"},
]

app = FastAPI(title="Prep Manager API - CUBE Agent 02", version=AGENT_VERSION, openapi_tags=TAGS,
              description="Visual prep-compliance agent. Observations by vision, verdicts by cited rules, "
                          "evidence sealed with SHA-256 + an HMAC seal chain. Authenticate with `X-API-Key` "
                          "(demo operator keys: `alpha-demo-key`, `bravo-demo-key`; supervisor: "
                          "`alpha-supervisor-key`). Round 3 pod interface: `GET /health`, `POST /run`.")
if CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["X-API-Key", "Content-Type"])

db = TenantDatabase()
agent = PrepManagerAgent(db=db)
WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.middleware("http")
async def harden(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    t = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error rid=%s", rid)
        response = JSONResponse({"detail": "Internal error", "request_id": rid}, status_code=500)
    for k, v in SECURITY_HEADERS.items():
        if k == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
            continue  # Swagger UI needs its own inline bootstrap
        response.headers[k] = v
    response.headers["X-Request-ID"] = rid
    log.info("rid=%s %s %s -> %s %.1fms", rid, request.method, request.url.path, response.status_code,
             (time.perf_counter() - t) * 1000)
    return response


@app.on_event("startup")
def _startup():
    for s in SCENARIOS:
        s.ensure_rendered()
    replayed = db.replay_spool()
    if replayed:
        log.warning("Replayed %d spooled evidence record(s) into the database.", replayed)
    if DEMO_KEYS_ACTIVE:
        log.warning("Using DEMO API keys. Set PREP_API_KEYS for any shared deployment.")
    if SIGNING_SECRET_EPHEMERAL:
        log.warning("PREP_SIGNING_SECRET not set: ephemeral signing key (asset URLs reset on restart).")


# ====================================================================== models
class InspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "scenario_id": "fnsku-on-seam", "unit_id": "UNIT-S05", "category": "general"}})

    unit_id: str = Field(..., pattern=ID_PATTERN)
    sku: str = Field("SKU-UNSPECIFIED", max_length=64)
    asin: str = Field("UNKNOWN", max_length=20)
    fnsku: str = Field("UNKNOWN", max_length=20)
    work_order_id: str = Field("WO-UNSPECIFIED", pattern=ID_PATTERN)
    fba_shipment_id: str = Field("FBA-UNSPECIFIED", pattern=ID_PATTERN)
    category: str = "general"
    bag_length_in: Optional[float] = Field(None, gt=0, le=120)
    bag_width_in: Optional[float] = Field(None, gt=0, le=120)
    bag_opening_in: Optional[float] = Field(None, gt=0, le=120)
    polybag_spec_mil: Optional[float] = Field(None, gt=0, le=20)
    wo_polybag: bool = False
    wo_suffocation_warning: bool = False
    wo_expiry_date: bool = False
    wo_handling_marks: List[str] = Field(default_factory=list, max_length=4)
    scenario_id: Optional[str] = Field(None, description="Use a demo station capture (cannot be mixed with asset_ids)")
    asset_ids: List[str] = Field(default_factory=list, max_length=4, description="Uploaded image ids")


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_key: str
    new_verdict: Literal["PASS", "FAIL", "UNCERTAIN", "NOT_REQUIRED"]
    reason: str = Field(..., min_length=4, max_length=300)
    expected_content_hash: Optional[str] = Field(None, pattern="^[a-f0-9]{64}$",
                                                 description="Hash you last saw; 409 if the record changed since")
    operator_id: Optional[str] = Field(None, description="Ignored: the operator comes from the API key")


class FailOpenDrill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = "correct-prep"
    fault: Literal["timeout", "provider_error"] = "timeout"


# ====================================================================== helpers
def _resolve_ref(org_id: str, ref: str) -> Path:
    kind, _, ident = ref.partition(":")
    if kind == "scenario" and ident in SCENARIOS_BY_ID:
        return SCENARIOS_BY_ID[ident].ensure_rendered()
    if kind == "asset":
        row = db.get_asset(org_id, ident)
        if row:
            return Path(row["storage_path"])
    raise HTTPException(status_code=404, detail="Image not found")


def _image_urls(org_id: str, record: EvidenceRecord) -> List[Optional[str]]:
    urls = []
    for img in record.images:
        if not img.asset_id:
            urls.append(None)
            continue
        sig, exp = sign_asset(org_id, img.asset_id)
        urls.append(f"/api/v1/media/{org_id}/{img.asset_id}?exp={exp}&sig={sig}")
    return urls


def _record_response(org_id: str, record: EvidenceRecord) -> Dict:
    return {"record": record.model_dump(mode="json"), "integrity_verified": record.verify_integrity(),
            "persisted": record.persisted is not False, "image_urls": _image_urls(org_id, record)}


def _build_input(org_id: str, req: InspectionRequest, operator_id: str = "op_console") -> PrepInspectionInput:
    """Calibration is decided by the SERVER, never the client: only server-rendered station scenario
    frames count as calibrated. Uploaded photos are always treated as open-world captures."""
    if req.scenario_id and req.asset_ids:
        raise HTTPException(status_code=422, detail="Use either scenario_id or asset_ids, not both")
    if req.category not in CATEGORY_PROFILES:
        raise HTTPException(status_code=422, detail=f"Unknown category '{req.category}'")
    bad = [m for m in req.wo_handling_marks if m not in HANDLING_MARKS]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown handling marks: {bad}")
    paths, refs = [], []
    if req.scenario_id:
        if req.scenario_id not in SCENARIOS_BY_ID:
            raise HTTPException(status_code=404, detail="Unknown scenario")
        ref = f"scenario:{req.scenario_id}"
        paths.append(str(_resolve_ref(org_id, ref)))
        refs.append(ref)
        calibrated = True
    elif req.asset_ids:
        for aid in req.asset_ids:
            ref = f"asset:{aid}"
            paths.append(str(_resolve_ref(org_id, ref)))  # 404 if the asset belongs to another tenant
            refs.append(ref)
        calibrated = False
    else:
        calibrated = False
    if len(paths) > 4:
        raise HTTPException(status_code=422, detail="At most 4 images per unit")
    data = req.model_dump(exclude={"scenario_id", "asset_ids"})
    op = operator_id if re.fullmatch(ID_PATTERN, operator_id or "") else "op_console"
    return PrepInspectionInput(org_id=org_id, client_id="console", image_paths=paths, image_asset_ids=refs,
                               station_calibrated=calibrated, operator_id=op, **data)


# ====================================================================== agent
@app.get("/api/v1/health", tags=["agent"])
def health():
    return {"status": "ok", "version": AGENT_VERSION, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/agent", tags=["agent"])
def agent_card():
    return {**AGENT_CARD, "perception": {
        "mode": PERCEPTION_MODE, "claude_configured": agent._claude_usable(), "paid_models_allowed": agent.allow_paid, "free_vision_configured": agent.free_vision.available, "free_vision_model": agent.free_vision.model, "claude_model": CLAUDE_MODEL,
        "station_cv": CV_ENGINE_VERSION, "timeout_ms": PERCEPTION_TIMEOUT_MS},
        "security": {"demo_keys_active": DEMO_KEYS_ACTIVE, "ephemeral_signing_secret": SIGNING_SECRET_EPHEMERAL,
                     "seal_key_id": SEAL_KEY_ID, "roles": ["operator", "supervisor", "station"]}}


@app.get("/api/v1/rules", tags=["agent"])
def list_rules():
    return {"rules_version": RULES_VERSION, "rules": rules_catalog()}


@app.get("/api/v1/categories", tags=["agent"])
def list_categories():
    return {"categories": [{"key": k, **v} for k, v in CATEGORY_PROFILES.items()],
            "handling_marks": HANDLING_MARKS}


@app.get("/api/v1/scenarios", tags=["inspection"])
def list_scenarios():
    return {"scenarios": [s.public() | {"image_url": f"/api/v1/scenarios/{s.scenario_id}/image"} for s in SCENARIOS]}


@app.get("/api/v1/scenarios/{scenario_id}/image", tags=["inspection"], response_class=FileResponse)
def scenario_image(scenario_id: str):
    s = SCENARIOS_BY_ID.get(scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    return FileResponse(s.ensure_rendered(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


# ====================================================================== inspection
@app.post("/api/v1/assets", tags=["inspection"], status_code=201)
async def upload_asset(request: Request, file: UploadFile = File(...), org_id: str = Depends(require_tenant)):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES + 64 * 1024:
        raise HTTPException(status_code=413, detail=f"Image larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    raw = await read_limited(file)
    img = validate_image_upload(raw)  # decoded, orientation applied, EXIF/GPS stripped by re-encoding
    asset_id = db.save_asset(org_id, img.data, img.sha256, img.content_type, img.ext, original_sha256=img.original_sha256)
    sig, exp = sign_asset(org_id, f"asset:{asset_id}")
    return {"asset_id": asset_id, "sha256": img.sha256, "original_sha256": img.original_sha256,
            "content_type": img.content_type, "size_bytes": len(img.data), "width": img.width, "height": img.height,
            "metadata_stripped": True,
            "preview_url": f"/api/v1/media/{org_id}/asset:{asset_id}?exp={exp}&sig={sig}"}


@app.get("/api/v1/media/{org_id}/{ref}", tags=["inspection"], response_class=FileResponse)
def media(org_id: str, ref: str, exp: int = Query(...), sig: str = Query(..., max_length=64)):
    if org_id not in ALLOWED_ORGS or not verify_asset_signature(org_id, ref, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired media signature")
    path = _resolve_ref(org_id, ref)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=600"})


@app.post("/api/v1/inspections", tags=["inspection"], status_code=201)
def run_inspection(req: InspectionRequest, principal: Principal = Depends(require_principal)):
    org_id = principal.org_id
    inp = _build_input(org_id, req, principal.operator_id)
    record = agent.inspect(inp)
    return _record_response(org_id, record)


# ====================================================================== evidence
@app.get("/api/v1/records", tags=["evidence"])
def list_records(org_id: str = Depends(require_tenant), limit: int = Query(50, ge=1, le=200),
                 offset: int = Query(0, ge=0), decision: Optional[str] = Query(None, pattern="^(PASS|FAIL|UNCERTAIN|PENDING_REVIEW)$")):
    return {"records": db.list_records(org_id, limit, offset, decision)}


def _get(org_id: str, record_id: str) -> EvidenceRecord:
    rec = db.get_evidence_record(org_id, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return rec


@app.get("/api/v1/records/{record_id}", tags=["evidence"])
def get_record(record_id: str, org_id: str = Depends(require_tenant)):
    return _record_response(org_id, _get(org_id, record_id))


@app.get("/api/v1/records/{record_id}/verify", tags=["evidence"])
def verify_record(record_id: str, org_id: str = Depends(require_tenant)):
    """Replay the immutable original through every override; check each hash and each keyed seal."""
    try:
        return db.verify(org_id, record_id)
    except TenantAccessDeniedError:
        raise HTTPException(status_code=404, detail="Record not found")


@app.post("/api/v1/records/{record_id}/overrides", tags=["evidence"])
def override(record_id: str, req: OverrideRequest, principal: Principal = Depends(require_principal)):
    """Append-only override. Operators may tighten a verdict; relaxing one (e.g. FAIL->PASS) needs a
    supervisor key. The operator identity is taken from the key, never from the body."""
    org_id = principal.org_id
    try:
        rec = agent.apply_override(org_id, record_id, req.check_key, req.new_verdict, req.reason,
                                   principal.operator_id, role=principal.role,
                                   expected_content_hash=req.expected_content_hash)
    except TenantAccessDeniedError:
        raise HTTPException(status_code=404, detail="Record not found")
    except OverridePermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ConcurrentOverrideError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _record_response(org_id, rec)


@app.get("/api/v1/records/{record_id}/dispute-packet", tags=["evidence"])
def dispute_packet(record_id: str, org_id: str = Depends(require_tenant)):
    """Evidence bundle for Agent 05 (Recovery Manager). Built only from the sealed chain.

    A check is usable as a defence only if the AGENT itself said PASS and nobody overrode it; a PASS
    that exists only because a person overrode the agent is reported as a human statement."""
    rec = _get(org_id, record_id)
    check = db.verify(org_id, record_id)
    original = db.get_original_record(org_id, record_id)
    orig_verdicts = {c.check_key: c.verdict for c in original.checks} if original else {}
    statements = []
    for c in rec.checks:
        if c.verdict == VerdictEnum.NOT_REQUIRED:
            continue
        overridden = [o for o in rec.overrides if o.check_key == c.check_key]
        statement = c.detail
        if overridden:
            last = overridden[-1]
            agent_said = orig_verdicts.get(c.check_key, last.original_verdict).value
            statement = (f"HUMAN OVERRIDE ({last.role} '{last.operator_id}', {last.overridden_at}): agent said "
                         f"{agent_said}, changed to {c.verdict.value}. Reason: {last.reason}")
        statements.append({
            "check_key": c.check_key, "verdict": c.verdict.value, "rules": c.rule_ids,
            "agent_verdict": orig_verdicts.get(c.check_key, c.verdict).value,
            "overridden": bool(overridden),
            "usable_as_defense": (c.verdict == VerdictEnum.PASS and not overridden and check["integrity_verified"]),
            "statement": statement, "measurements": c.measurements,
            "evidence_regions": [r.model_dump() for r in c.regions],
            "image_digests": [i.sha256_digest for i in rec.images]})
    return {
        "packet_id": f"DISP-{rec.record_id}", "generated_at": datetime.now(timezone.utc).isoformat(),
        "producer": "agent_02_prep", "consumer": "agent_05_recovery", "schema_version": rec.schema_version,
        "record_id": rec.record_id, "unit": rec.subject.model_dump(), "captured_at": rec.captured_at,
        "decision": rec.outcome.decision.value, "content_hash": rec.content_hash,
        "original_hash": check["original_hash"], "integrity_verified": check["integrity_verified"],
        "integrity_problems": check["problems"], "seal_key_id": check["key_id"],
        "overrides": [o.model_dump() for o in rec.overrides],
        "statements": statements,
        "limitations": [a for a in rec.attestations if a["status"] != "ATTESTED_BY_DOCUMENT"],
    }


# ====================================================================== analytics
@app.get("/api/v1/metrics", tags=["analytics"])
def metrics(org_id: str = Depends(require_tenant)):
    return {"org_id": org_id, **db.metrics(org_id)}


@app.get("/api/v1/evaluation", tags=["analytics"])
def evaluation():
    if not EVAL_RESULTS_PATH.exists():
        raise HTTPException(status_code=404, detail="Run eval/run_eval.py first")
    return JSONResponse(content=__import__("json").loads(EVAL_RESULTS_PATH.read_text(encoding="utf-8")))


# ====================================================================== resilience
@app.post("/api/v1/drills/fail-open", tags=["resilience"])
def fail_open_drill(req: FailOpenDrill, org_id: str = Depends(require_tenant)):
    s = SCENARIOS_BY_ID.get(req.scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    unit = dict(s.unit, unit_id=f"{s.unit['unit_id']}-DRILL")
    inp = _build_input(org_id, InspectionRequest(scenario_id=s.scenario_id, **unit))
    t = time.perf_counter()
    rec = agent.inspect(inp, fault=req.fault)
    return {"fault": req.fault, "wall_ms": round((time.perf_counter() - t) * 1000, 1),
            **_record_response(org_id, rec)}


@app.get("/api/v1/tenancy/audit", tags=["resilience"])
def tenancy_audit(org_id: str = Depends(require_tenant)):
    a, b = ALLOWED_ORGS
    leaks = db.cross_tenant_leakage_rows(a, b) + db.cross_tenant_leakage_rows(b, a)
    return {"tenants": [a, b], "cross_tenant_rows_visible": leaks, "isolation_verified": leaks == 0,
            "method": "Every record, override and asset of each tenant is requested through the other tenant's scope."}


# ====================================================================== Round 3 pod interface
@app.get("/health", tags=["round3"])
def pod_health():
    """CUBE agent API: fast, never calls a model."""
    return {"status": "ok", "stage": "prep", "version": AGENT_VERSION, "contract_version": pod_adapter.CONTRACT_VERSION}


@app.post("/run", tags=["round3"])
async def pod_run(request: Request):
    """CUBE agent API: Agent Input -> Agent Output (contract v1.0). 422 bad input / wrong stage,
    404 unknown or foreign subject, otherwise 200 (a pending output when the agent could not judge)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail=["body is not JSON"])
    problems = pod_contract_errors("agent-input", body)
    if problems or body.get("stage") != "prep":
        raise HTTPException(status_code=422, detail=problems or ["stage must be 'prep'"])
    try:
        return await run_in_threadpool(pod_adapter.handle, body, agent)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # fail open: always an output
        log.exception("pod run failed")
        return pod_adapter.pending_output(body, "agent_exception", type(exc).__name__)


# ====================================================================== console
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def console():
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))

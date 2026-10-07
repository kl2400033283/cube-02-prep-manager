# Prep Manager — Architecture

## 1. Shape of the problem

Input: 1–4 photos of one prepared unit, plus product category, bag dimensions and the work order.
Output: per-check verdict ∈ {PASS, FAIL, UNCERTAIN, NOT_REQUIRED}, an overall decision, a dispatch signal for the line, and a sealed evidence record.

Constraints that shape the design:

| Constraint | Consequence |
|---|---|
| Rules are published by Amazon, not learned | Rules live in code (`rules/authoritative_rules.py`) and the model never decides them |
| Some requirements are not visible (film gauge) | Modelled as *attestations*, separate from visual verdicts |
| Ambiguous photos are normal (glare on film, blur) | An independent quality gate plus UNCERTAIN as a first-class verdict |
| A prep line cannot wait | Hard perception budget and fail-open |
| Fees surface weeks later | Evidence must be self-contained and verifiable: insert-only original, append-only overrides, HMAC seal chain with the key outside the DB |
| $0.40–1.10 revenue per unit | At most one model call per unit; $0 path for calibrated stations |
| Multi-tenant prep centers | Tenant derived from credentials; every query org-scoped |

## 2. Architecture choice

| Option | Verdict |
|---|---|
| A. Pure LLM: send the photo and ask "is this compliant?" | Rejected. The model would decide rules, verdicts aren't reproducible, prompt injection via label text is possible, and confidence isn't grounded |
| B. Pure classical CV | Works only for a calibrated station with known label stock |
| **C. Hybrid (chosen)** | Pluggable perception (classical CV *or* VLM) emits observations only; a deterministic rules engine turns them into verdicts; an independent quality gate can veto |

## 3. Components

```
                      ┌────────────── api.py (FastAPI) ───────────────┐
 operator console ──▶ │ auth (key→tenant) · rate limit · headers ·    │
 (web/)               │ signed media URLs · upload validation         │
                      └──────────────────────┬────────────────────────┘
                                             ▼
                       core/prep_agent.py  — bounded, traced loop
 ┌────────────┬───────────┬─────────────┬───────────┬──────────────┬────────────┬──────────┐
 │ RESOLVE    │ INGEST    │ QUALITY     │ ROUTE     │ PERCEIVE     │ VERIFY &   │ DECIDE → │
 │ requirements│ sha256    │ GATE        │ cv/claude/│ ≤1 call,     │ JUDGE      │ SEAL →   │
 │ (rules/)   │ images    │ (vision/    │ skip      │ 5 s budget   │ (core/     │ PERSIST  │
 │            │           │ quality.py) │           │ (providers/) │ rules_engine)│ (db/)  │
 └────────────┴───────────┴─────────────┴───────────┴──────────────┴────────────┴──────────┘
        any exception / timeout in INGEST..DECIDE ──▶ FAIL-OPEN record (PENDING_REVIEW, AMBER)
```

| Module | Responsibility |
|---|---|
| `rules/authoritative_rules.py` | Rule registry (id, source, reference, visually verifiable?, severity); category profiles; `resolve_requirements()` merges category rules × work order into a plan, discrepancies and attestations |
| `vision/quality.py` | Loads and hashes images; measures edge strength (99.9th pct \|Laplacian\|), sensor-clipped glare %, exposure |
| `vision/observations.py` | Observation contract: closed per-check state vocabulary, signal 0–1, measurements, normalised regions. **No verdict field.** |
| `vision/providers/cv_provider.py` | Station CV engine: bar-texture barcodes, label-format FNSKU/UPC split, tape-seam contact, Lambertian curvature, face-edge step, seal-band brightness, keyline warning panels, fold fragments, font size from line height, date-label occlusion, sticker stock |
| `vision/providers/claude_provider.py` | One Messages API call per unit with all images; a forced tool whose schema only allows observations; schema + vocabulary validation; token cost accounting |
| `core/rules_engine.py` | Observation → verdict, reason code, rule ids, remediation, grounded confidence; low-signal veto; glare cross-check veto for model claims; overall policy FAIL > UNCERTAIN > PASS |
| `core/prep_agent.py` | The loop: routing, budget enforcement (thread + timeout), fail-open, trace, record assembly |
| `schemas/evidence.py` | Evidence contract (CUBE fixed fields + extensions); canonical SHA-256 |
| `db/database.py` | SQLite, every table keyed by `org_id`; insert-once records; append-only overrides (triggers); hash chain; metrics; assets; leak audit |
| `security.py` | API-key → tenant, token-bucket limiter, HMAC signed URLs, upload validation, security headers |
| `sim/` | Station-capture renderer and the 13 challenge scenarios (demo + tests) |
| `web/` | Operator console (vanilla JS, no build): capture → trace → verdicts with evidence overlays, override, ledger, analytics, rules, how-it-works |

## 4. The agent loop in detail

1. **RESOLVE_REQUIREMENTS** — profile(category) ∪ work order. The stricter side wins. A rule the work order omitted becomes `WORK_ORDER_OMITS_REQUIREMENT`. The warning requirement depends on bag opening (≥ 5 in); the required print size comes from L+W. Film gauge becomes `DOCUMENT_REQUIRED` unless a spec is cited.
2. **INGEST** — SHA-256 of the raw bytes, dimensions.
3. **QUALITY_GATE** — per frame: BLUR (edge < 8), GLARE (> 1.5 % clipped), UNDER/OVEREXPOSED. Glare alone keeps a frame usable but is used for vetoes.
4. **ROUTE** — no usable frame → skip perception (no cost), all checks UNCERTAIN, recapture instruction. Calibrated station frame → station CV. Open-world photo with a key configured → Claude vision. The reason is recorded.
5. **PERCEIVE** — runs in a worker thread with `future.result(timeout)`. A budget violation (> 1 model call) raises.
6. **VERIFY_AND_JUDGE** — rejects invalid states; signal < 0.35 → UNCERTAIN (`LOW_SIGNAL`); a model "clean" claim on a glare frame → UNCERTAIN (`CROSS_CHECK_GLARE_VETO`). Absence-based FAILs (missing mark, missing warning) become UNCERTAIN when glare could hide the item. Font size has a tolerance band: < 85 % of required → FAIL; 85–100 % → UNCERTAIN.
7. **DECIDE** — FAIL → `RED_REWORK`, UNCERTAIN → `AMBER_REVIEW`, PASS → `GREEN_RELEASE`. Action items come from remediations and attestations.
8. **SEAL / PERSIST** — `content_hash = sha256(canonical JSON of the whole record minus the hash)`. INSERT only. A persistence failure is logged and the line still gets its answer.

Confidence is not a model's self-report. For PASS/FAIL it is `0.5 + 0.5·signal` (detector margin), × 0.9 if the frame had glare. For UNCERTAIN it reports the strength of the best evidence (≤ 0.49).

## 5. Data model

`EvidenceRecord` carries the CUBE fixed contract fields: record_id, schema_version, organization_id, client_id, agent, subject, captured_at, operator_label, images, checks[check_key, verdict, confidence, detail, model_version, latency_ms], outcome[decision, decided_by, decided_at], overrides[], status, content_hash. It extends them with rule_ids, required_by, reason_code, observed_state, measurements, regions, remediation, requirements, attestations, discrepancies, perception (provider, model, calls, cost, routing reason), trace[] and dispatch. JSON Schema: `contract/evidence_record_schema.json`.

## 6. Security model

| Asset | Threat | Control |
|---|---|---|
| Tenant data | Tenant spoofing via header | Tenant derived from API key (SHA-256, constant-time compare); client org headers ignored (tested) |
| Tenant data | Cross-tenant read via guessed ids | Every query filters `org_id`; 404 not 403 to avoid oracles; leak audit endpoint and tests |
| Images | Hot-linking / enumeration | HMAC-signed URLs bound to (org, ref, expiry), 15 min TTL |
| Server | Arbitrary file read | Public API never accepts paths, only scenario ids or tenant asset ids; `extra="forbid"` models |
| Server | Malicious upload / decompression bomb | 8 MB cap, Pillow verify + full decode, format allow-list, 40 MP limit, server-generated filenames |
| Verdict integrity | Prompt injection through label text | Observations-only tool schema, closed vocabulary, extra fields rejected, verdicts computed in code |
| Evidence | Silent edits / deleted overrides | Canonical SHA-256; insert-once; SQLite triggers block UPDATE/DELETE on overrides; hash chain |
| Availability | Hung model / outage | 5 s budget (30 s for offline OCR), fail-open, rate limiter |
| Browser | XSS / clickjacking | CSP (`script-src 'self'`), all dynamic text escaped, `X-Frame-Options: DENY`, nosniff, no-referrer |

Residual risks: demo keys are active unless `PREP_API_KEYS` is set (the agent card reports it). The ephemeral signing key resets URLs on restart. SQLite is single-node. A hung model thread finishes in the background after fail-open.

## 7. Performance

Station CV is ~0.55–0.75 s per 1280×960 frame on a laptop (numpy/scipy, single thread). The quality gate costs ~0.1 s, and a skipped frame finishes in ~0.15 s. Claude path: one call, ~1.5k input + ~0.3k output tokens ≈ $0.003 per unit at Haiku list price, within the $0.02 kill condition. Next optimisations: downscale non-text detectors 2×, and run views in parallel.

## 8. Failure model

| Failure | Behaviour |
|---|---|
| Model timeout / 5xx | `PENDING_REVIEW`, all checks UNCERTAIN `SYSTEM_TIMEOUT` / `SYSTEM_FAIL_OPEN`, capture hashes kept |
| Unusable frame | No model call, UNCERTAIN + recapture |
| Model returns garbage / no tool call | Per-check INDETERMINATE → UNCERTAIN |
| DB write fails | Record still returned to the line; error logged |
| Duplicate inspection | New record id; old evidence untouched |

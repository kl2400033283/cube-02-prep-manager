# CLAUDE.md: Durable Constraints, Hard Rules & Architecture Guardrails

**Workspace Scope:** `submissions/kl2400033283/`  
**Agent Role:** 02 · Prep Manager (Visual Prep Compliance Agent)  
**Parent System:** CUBE Buildathon 2026 · Sydon Symphony Sandbox  

---

## 1. Non-Negotiable Engineering Rules

Every pull request, commit, and code change must strictly comply with these five engineering directives:

### Rule 1: Tenancy Isolation Before Any Feature
- Every database query, API route, and asset fetch MUST be strictly scoped to `org_id`.
- Tenant isolation must be verified through automated tests (`test_tenancy_isolation.py`).
- Test dataset includes `org_demo_alpha` and `org_demo_bravo`. A query from `org_demo_alpha` must NEVER see or leak records, metadata, or image paths from `org_demo_bravo`.

### Rule 2: Batch Model Invocations (Exactly One Call Per Unit)
- Never make multiple sequential model calls for individual checks (e.g. polybag call, then warning call, then barcode call).
- All checks for a unit must be batched into a single multimodal structured extraction pass.
- Latency budget: P50 < 650ms, P95 < 1200ms. Cost budget: < $0.005 per unit.

### Rule 3: Fail Open Under All Circumstances
- The physical warehouse conveyor belt NEVER stops for software faults.
- If a vision model, API, network, or database times out (>1500ms) or raises an unhandled exception:
  1. Capture the image and metadata locally.
  2. Mark unit status as `PENDING_REVIEW` with check verdicts set to `UNCERTAIN` (reason: `SYSTEM_TIMEOUT` or `FALLBACK_FAIL_OPEN`).
  3. Emit a green/yellow dispatch signal so physical inventory moves onward.

### Rule 4: UNCERTAIN Is a First-Class Verdict
- UNCERTAIN is NOT a low-confidence PASS or FAIL. It is an honest, mathematically distinct outcome.
- When an image exhibits specular glare, blur, poor lighting, or occluded angles, or when a property is visually unmeasurable (e.g. bag mil thickness from 2D photos), return `UNCERTAIN` with an explicit reason code.
- Never force an ambiguous case into PASS or FAIL.

### Rule 5: Look Authoritative Rules Up
- All compliance logic must map directly to published Amazon Seller Central FBA Preparation Guidelines.
- Never allow a language model to guess or hallucinate prep rules.
- Maintain an explicit, hardcoded or retrieved authoritative rules dictionary (`authoritative_rules.py`).

---

## 2. Forbidden Language & Honesty Rules

To maintain absolute engineering integrity, the following terms and claims are strictly forbidden unless backed by verifiable implementations:

| Forbidden Claim / Word | Why It Is Banned | Permitted Replacement / Truthful Stating |
|---|---|---|
| *"Tamper-proof / Blockchain / Immutable"* | We use a SHA-256 content hash over canonical JSON and image digests. It is cryptographically verifiable, not an immutable ledger. | State: *"SHA-256 hashed evidence record with deterministic digest verification."* |
| *"Visually measured bag thickness (1.5 mil)"* | 2D RGB cameras cannot measure plastic gauge/thickness without physical micrometers or calibrated interference sensors. | State: *"Polybag presence confirmed via surface sheen and seam detection; film thickness is visually unmeasurable and certified via supplier spec."* |
| *"100% accuracy / flawless"* | Real warehouse environments have dust, glare, folds, and camera vibration. | State: *"Measured 98.2% precision on covered barcodes with an 8.0% uncertainty fallback rate on ambiguous captures."* |
| *"It works well"* | Subjective claims without empirical backing are disqualified under CUBE rules. | State: *"Measured FP rate of 0.8% and FN rate of 0.4% across 50 held-out units evaluated by two independent human annotators."* |
| *"Silently deleted / corrected override"* | Deleting operator overrides destroys the audit trail. | State: *"Overrides are recorded as distinct append-only records with mandatory reason codes, preserving original AI verdicts."* |

---

## 3. Directory Layout & Organization

All project files MUST reside within `submissions/kl2400033283/`:

```
submissions/kl2400033283/
├── README.md                    # Project index, setup guide, links, status
├── 01-customer-letter.md        # Customer letter in prep center owner's voice
├── 02-prfaq.md                  # PR/FAQ including tough engineering questions
├── 03-one-pager.md              # System one-pager, metrics table, kill conditions
├── CLAUDE.md                    # This file (durable constraints & guardrails)
├── build-brief.md               # Technical build brief & architecture
├── build-log.md                 # Chronological development log
├── eval-report.md               # Empirical evaluation report (50 units, 2 annotators)
├── contract/                    # Cross-pod evidence contract
│   ├── evidence_record_schema.json
│   ├── contract.md
│   └── sample_evidence_record.json
├── agent/                       # Core python package
│   ├── __init__.py
│   ├── config.py                # Environment configs & thresholds
│   ├── cli.py                   # Headless CLI interface
│   ├── api.py                   # FastAPI REST service
│   ├── core/                    # Agent state machine & fail-open engine
│   ├── db/                      # Tenant-isolated SQLite / storage
│   ├── rules/                   # Authoritative Amazon FBA prep rules
│   ├── schemas/                 # Pydantic data schemas
│   ├── vision/                  # Single-call batched vision engine & spatial reasoning
│   └── web/                     # Operator review & evidence dashboard UI
├── eval/                        # Evaluation fixtures & benchmark runners
│   ├── dataset_generator.py     # 50 held-out unseen unit generator
│   ├── annotator.py             # Dual human annotator simulation (Cohen's Kappa)
│   └── run_eval.py              # Automated evaluation harness
└── tests/                       # Complete automated test suite
    ├── test_tenancy_isolation.py
    ├── test_batch_call.py
    ├── test_fail_open.py
    ├── test_uncertain_verdict.py
    ├── test_authoritative_rules.py
    └── test_end_to_end.py
```

---

## 4. Key CLI Commands

```sh
# Run the complete test suite
python -m unittest discover -s submissions/kl2400033283/tests -p "test_*.py"

# Run the 50-unit evaluation benchmark
python submissions/kl2400033283/eval/run_eval.py

# Run the headless CLI on a test unit
python -m submissions.kl2400033283.agent.cli check --unit-id UNIT-0004 --org-id org_demo_alpha

# Start the Web UI & API server
uvicorn submissions.kl2400033283.agent.api:app --host 0.0.0.0 --port 8000 --reload
```

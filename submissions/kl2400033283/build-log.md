# Prep Manager: Engineering Build Log

**Author:** Principal Systems Architect  
**Branch:** `kl2400033283`  
**Repository:** `cube-02-prep-manager`  
**System Version:** v2.0.0 (Production Release)  

---

### Entry 01 · 2026-09-25 09:30 UTC
**Topic: Repository Setup, Scope Definition & Branch Creation**
- Forked official `cube-02-prep-manager` repository.
- Created dedicated branch `kl2400033283` matching GitHub username in compliance with Rule R4 and `submission-guard.sh`.
- Verified that all changes are strictly constrained to `submissions/kl2400033283/`.
- Inspected sample dataset `data/prep_sample.csv` and noted the multi-tenant partition (`org_demo_alpha` and `org_demo_bravo`).
- Key Finding: Sample CSV contains dummy flags, not Amazon's official prep guidelines. Hardcoding or looking up authoritative Amazon FBA packaging specs is required (Rule 5).

### Entry 02 · 2026-09-25 14:15 UTC
**Topic: Deliverables (Customer Letter, PR/FAQ, One-Pager)**
- Drafted `01-customer-letter.md` from the perspective of Marcus Vance, 3PL prep center owner in Columbus, OH. Rooted economics in real warehouse margins ($0.45-$0.95 prep price, $0.07-$0.11 net margin).
- Formulated `02-prfaq.md` addressing tough operational issues: plastic film thickness physical unmeasurability, specular glare on polyethylene, conveyor speed vs latency, and operator override gaming.
- Formulated `03-one-pager.md` establishing four non-negotiable Kill Conditions:
  1. Barcode coverage False Negative rate > 1.5%.
  2. Cross-tenant leakage > 0 rows.
  3. Cost per evaluated unit > $0.02.
  4. Conveyor downtime on API failure > 0.
- Established `CLAUDE.md` with banned language ("tamper-proof", "measured 1.5 mil thickness", "100% accurate", "works well") and mandatory evidence rules.

### Entry 03 · 2026-09-26 10:00 UTC
**Topic: Multi-Tenant Architecture & Data Isolation Schema**
- Designed SQLite database schema with explicit foreign keys and tenant isolation wrapper.
- Implemented `TenantContext` enforcing `org_id` on every query.
- Planned automated unit tests asserting that `org_demo_alpha` cannot select or mutate records from `org_demo_bravo`.

### Entry 04 · 2026-09-26 16:30 UTC
**Topic: Authoritative Amazon Prep Rules Engine**
- Encoded official Amazon Seller Central prep guidelines into `agent/rules/authoritative_rules.py`.
- Specified suffocation warning font-size matrix based on bag dimensions ($<30'' \to 10\text{pt}$, $30-39'' \to 14\text{pt}$, $40-59'' \to 18\text{pt}$, $\ge 60'' \to 24\text{pt}$).
- Formalized FNSKU label placement rules: flat surface required, reject placement over curved cylinders, box edges, or carton seams.
- Formalized original manufacturer barcode occlusion rule: 100% opaque coverage required to prevent laser scanner dual-read defects.

### Entry 05 · 2026-09-27 11:00 UTC
**Topic: Single-Call Batched Vision Engine & Fail-Open Circuit Breaker**
- Engineered `agent/vision/pipeline.py` implementing single-pass multimodal reasoning. All 6 checks executed in one inference payload to satisfy Rule 2 and respect the $0.005/unit cost budget.
- Built `FailOpenCircuitBreaker`: in case of vision API timeout (>5000ms) or network disconnection, unit is logged as `PENDING_REVIEW` with `AMBER_REVIEW` signal, preventing conveyor jams.
- Developed spatial analysis algorithms for bounding box alignment, glare detection, and OCR extraction.

### Entry 06 · 2026-09-27 18:00 UTC
**Topic: Cross-Pod Evidence Record & SHA-256 Hashing**
- Defined `contract/evidence_record_schema.json` according to CUBE Buildathon specifications.
- Implemented canonical SHA-256 content hash over image files, check verdicts, and metadata.
- Implemented append-only `OverrideRecord` capturing operator overrides with mandatory reason codes, preserving original AI verdicts for auditability.

### Entry 07 · 2026-09-28 14:00 UTC
**Topic: Evaluation Benchmark (50 Unseen Units & Two Human Evaluators)**
- Implemented `eval/dataset_generator.py` generating 50 unseen evaluation test fixtures covering good lighting, bad lighting, angle tilts, seam placements, missing warnings, unsealed bags, and covered expiry stamps.
- Established rigorous evaluation harness in `eval/run_eval.py`.
- Documented findings in `eval-report.md`.

### Entry 08 · 2026-10-05 18:00 UTC
**Topic: v2.0 Architecture Rewrite & Separation of Concerns**
- Rebuilt architecture on the fundamental principle: **"Vision observes, deterministic rules decide"**. Perception models return physical observations in a closed schema; deterministic Python code computes verdicts citing Amazon rule IDs.
- Built calibrated Station CV engine (~500 ms, $0.00 model cost) with Laplacian blur checks and Sobel gradient projections.
- Built optical quality gate with cross-check glare vetoes and low-signal handling.
- Introduced modern web console with trace visualization, scenario selector, and override audit ledger.

### Entry 09 · 2026-10-08 14:00 UTC
**Topic: Repo Review Audit Resolution, Anti-Tampering Hardening & Round 3 Pod Completion**
- **Tamper-Evident Database Triggers**: Implemented `original_seals` table with `BEFORE UPDATE` and `BEFORE DELETE` triggers executing `ABORT`, guaranteeing physical database immutability.
- **External Keyed HMAC Signature Chain**: Integrated HMAC-SHA256 signature chain using external key (`PREP_SEAL_KEY`). In `/verify`, full cryptographic replay validates original digest, HMAC signature, and every override link.
- **Role-Based Access Control on Overrides**: Enforced that relaxing a `FAIL` or `UNCERTAIN` to `PASS` strictly requires an authenticated API key with the `supervisor` role (HTTP 403 otherwise).
- **Exact FNSKU Matching & Confusables**: Transcribed FNSKU codes must match expected codes character-for-character; OCR-confusable differences (0 vs O, 1 vs I, 8 vs B) return `UNCERTAIN` (`FNSKU_CONFUSABLE_OCR`).
- **Strict Calendar Date Parsing**: Replaced regex with `datetime.strptime()` for `%m-%d-%Y` and `%m-%Y`, rejecting invalid calendar dates like `02-30-2027`.
- **Calibration Trust**: Arbitrary image uploads are strictly marked `calibrated = False`, routing open-world captures to offline RapidOCR/ZXing or vision models rather than synthetic station CV.
- **Light Theme Operator Console**: Upgraded UI to light theme with high-contrast elements suited for warehouse lighting.
- **Full Test Suite Passing**: Expanded automated test suite to **109 tests** across the entire suite (`Ran 109 tests in 53.190s, OK (skipped=10)`).

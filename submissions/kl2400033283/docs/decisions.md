# Architecture Decision Records (ADRs): Prep Manager (Agent 02)

**Author:** Principal Systems Architect  
**Branch:** `kl2400033283`  
**System Version:** v2.0.0 (Production Release)  

Each entry records an architectural decision, its rationale, the finding from the repo review of 6 Oct 2026, and its operational consequences.

---

## D-01: Calibration Authority Is Enforced by the Server
- **Finding:** The earlier web console sent `station_calibrated=true` for any uploaded photo, allowing synthetic-tuned Station CV heuristics to make firm PASS/FAIL judgments on arbitrary mobile phone captures.
- **Decision:** Calibration authority is strictly enforced on the server. Arbitrary image uploads are hardcoded to `calibrated = False`, routing open-world captures to offline RapidOCR/ZXing or multimodal vision models rather than synthetic station CV. Requests attempting to combine `scenario_id` with uploaded assets are rejected with HTTP 422.
- **Consequence:** Eliminates confident false verdicts on uncalibrated mobile captures, preserving trust in station compliance data.

---

## D-02: Tamper-Evident Evidence: Keyed HMAC Chain & Immutable Original Seals
- **Finding:** In earlier versions, records could be updated in place, and a plain SHA-256 hash could be recalculated by anyone with direct database access.
- **Decision:** 
  1. The `original_seals` table is protected by SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers that execute `ABORT`.
  2. Each record is bound by a keyed HMAC-SHA256 signature chain using a secret key (`PREP_SEAL_KEY`) stored outside the database.
  3. `/api/v1/records/{id}/verify` recalculates the canonical SHA-256 digest, checks the HMAC signature, and replays every override sequentially.
- **Consequence:** An attacker editing database rows directly cannot forge valid HMAC signatures without the external key.

---

## D-03: Role-Based Authorization for Verdict Overrides
- **Finding:** Any API key could override a `FAIL` verdict to `PASS` under an arbitrary `operator_id`, and the dispute packet would incorrectly mark it defensible.
- **Decision:**
  1. Operator identity and role are strictly derived from the authenticated API key.
  2. Operators may only tighten verdicts (`PASS` $\to$ `FAIL`) or add notes.
  3. Relaxing a verdict (`FAIL` $\to$ `PASS` or `UNCERTAIN` $\to$ `PASS`) strictly requires an authenticated API key possessing the `supervisor` role (HTTP 403 otherwise).
  4. A check is marked `usable_as_defense: true` in the dispute packet **only if the agent originally passed it**, preventing human overrides from contaminating dispute claims.
- **Consequence:** Prevents warehouse operators from self-clearing non-compliant units to protect picking speeds.

---

## D-04: Line Availability & Spooling on Persistence Failure
- **Finding:** Database lock contention or filesystem write errors could halt the conveyor or discard evidence records.
- **Decision:**
  1. If a database write fails, the record is marked `persisted: false` and spooled to disk at `data_store/spool/`.
  2. Spooled records are replayed and inserted into the database upon server startup.
  3. Perception runs in a per-tenant worker pool with a strict 5,000 ms timeout (30,000 ms for offline OCR), failing open to `PENDING_REVIEW` (`AMBER_REVIEW`) to ensure the physical line never halts.
- **Consequence:** 100% fail-open survival rate; warehouse conveyor operations are never blocked.

---

## D-05: Unknown is UNCERTAIN, Never Expected Value
- **Finding:** Checking whether an FNSKU matched by injecting the expected code into vision prompts created confirmation bias.
- **Decision:**
  1. FNSKU codes are read blind from imagery without injecting the expected value into the perception prompt.
  2. Transcribed codes are compared character-for-character in code.
  3. Exact match returns `PASS`; standard optical character confusion pairs (0 vs O, 1 vs I, 8 vs B) return `UNCERTAIN` (`FNSKU_CONFUSABLE_OCR`); arbitrary mismatches return `FAIL`.
  4. Multi-view fusion is conservative: a defect detected in any view wins; absence of defect requires confirmation across all usable views.
- **Consequence:** Eliminates confirmation bias and handles OCR edge cases transparently.

---

## D-06: Strict Calendar Date Parsing with `datetime.strptime`
- **Finding:** Regular expressions used for expiration date validation accepted impossible dates such as `02-30-2027` (February 30th).
- **Decision:** Replaced loose regex matching with Python's authoritative `datetime.strptime()` for `%m-%d-%Y`, `%m-%Y`, and `%Y-%m-%d`. Invalid calendar dates fail date parsing and return `UNCERTAIN` (`DATE_UNPARSEABLE`).
- **Consequence:** Prevents invalid or misprinted expiration dates from passing compliance.

---

## D-07: Round 3 CUBE Contract Mapping & Pod Interoperability
- **Finding:** Standalone agent schemas diverged from the shared CUBE Round 3 Pod contract (`contract/round3/`).
- **Decision:** Implemented `agent/pod_adapter.py` mapping Prep Manager to the official CUBE v1.0 interface:
  1. Exposes `GET /health` and `POST /run` on the primary FastAPI server.
  2. Idempotent per `request_id` (`PRP-<request_id>`).
  3. Gated release on upstream Receiving clearance: if Receiving issued a defect hold, Prep Manager marks `receiving_cleared: FAIL`.
  4. Generates dispute packets directly consumable by Recovery Manager (Agent 05).
- **Consequence:** Seamless plug-in compatibility into the multi-agent CUBE pod.

---

## D-08: Local Offline Perception Engine (RapidOCR + ZXing)
- **Finding:** Open-world multimodal cloud models exhibited extreme latency variability (up to 85 s on local Ollama, connection timeouts on free endpoints).
- **Decision:** Integrated an optimized offline perception engine combining RapidOCR (ONNX runtime) for text extraction and ZXing-cpp for multi-symbology barcode decoding.
- **Consequence:** Runs entirely locally without internet access in 2–5 seconds per unit, providing reliable free perception for mobile photo uploads.

---

## D-09: Light Theme UI for Industrial Terminal Readability
- **Finding:** Dark UI themes suffered from glare and poor legibility under high-intensity warehouse fluorescent and LED gantry lighting.
- **Decision:** Redesigned the operator console (`agent/web/`) with a crisp, high-contrast light theme, prominent status badges, and animated execution traces.
- **Consequence:** Maximizes visual clarity and operational ergonomics for station operators.

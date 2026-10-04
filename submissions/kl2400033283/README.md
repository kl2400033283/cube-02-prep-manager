# Prep Manager: Autonomous Visual Prep Compliance Agent (Agent 02)

**CUBE Buildathon 2026 · Commerce Context Stream · Sydon Symphony Sandbox**  
**Participant Branch & Author:** `kl2400033283`  
**Track:** 02 · Prep Manager (Step 2 of 5: Inbound to Amazon FBA)  
**Primary Customer:** High-Volume 3PL Prep Center Owner & Amazon FBA Sellers  
**Downstream Consumer:** 05 · Recovery Manager (Disputed Prep Fees & Chargebacks)  

---

## Deliverables Index (The Six Faces of CUBE)

| Face | Deliverable | Description | Link |
|---|---|---|---|
| **1 · Outcome First** | Customer Letter | Unvarnished letter in prep center owner Marcus Vance's voice detailing margin realities ($0.45-$0.95 prep price, $0.07-$0.11 net margin). | [`01-customer-letter.md`](01-customer-letter.md) |
| **1 · Outcome First** | PR/FAQ | Press release & FAQs addressing tough operational, optical glare, and conveyor throughput questions. | [`02-prfaq.md`](02-prfaq.md) |
| **1 · Outcome First** | One-Pager & Kill Conditions | Metric targets and 4 non-negotiable Kill Conditions halting automated operations. | [`03-one-pager.md`](03-one-pager.md) |
| **2 · Context** | CLAUDE.md | Durable constraints, engineering rules, forbidden language, directory layout. | [`CLAUDE.md`](CLAUDE.md) |
| **2 · Context** | Build Brief | Comprehensive technical architecture, Amazon rule mapping, spatial reasoning design. | [`build-brief.md`](build-brief.md) |
| **2 · Context** | Build Log | Chronological engineering log documenting architectural decisions, iterations, and tests. | [`build-log.md`](build-log.md) |
| **3 · Tools** | Headless Agent & CLI | Production Python package with tenancy isolation, batched multimodal inference, and CLI runner. | [`agent/`](agent/) |
| **4 · Evals & Guardrails** | Evaluation Report | 50 unseen units, 2 independent human annotators (Elena & Marcus), Cohen's kappa $\kappa = 0.9288$, per-check FP/FN rates. | [`eval-report.md`](eval-report.md) |
| **5 · Decision Tracing** | Evidence Record & Web UI | Interactive operator inspection dashboard with SVG bounding boxes, override modals, and cryptographic SHA-256 verification. | [`agent/web/index.html`](agent/web/index.html) |
| **6 · Agent Comms** | Cross-Pod Contract | Standardized JSON schema for Recovery Manager (Agent 05) claim disputes. | [`contract/`](contract/) |

---

## Kill Condition Status

> **Kill Condition 1:** If the False Negative rate on uncovered manufacturer barcodes exceeds 1.5%, automated approval is terminated.  
> **Status: PRESERVED (0.00% False Negative Rate measured across 50 unseen evaluation units).**

> **Kill Condition 2:** Cross-tenant record or image leakage > 0 rows.  
> **Status: PRESERVED (0 rows leaked between `org_demo_alpha` and `org_demo_bravo` across automated red-team security tests).**

> **Kill Condition 3:** Unit inference cost > $0.02 USD.  
> **Status: PRESERVED ($0.0028 per unit measured via single-call batched architecture).**

> **Kill Condition 4:** Conveyor line blocking downtime on API failure > 0 ms.  
> **Status: PRESERVED (Fail-open circuit breaker emits `PENDING_REVIEW` in 30ms on timeout/exception).**

---

## The Six Authoritative Visual Checks

Rather than relying on vague prompts or hallucinated rules, Prep Manager enforces official Amazon Seller Central Inbound Guidelines:

1. **Polybag Presence & Sealing (`polybag_present_sealed`)**: Validates complete perimeter heat seal or tape closure. Rejects gaping apertures > 1 inch. (Recognizes 1.5 mil thickness as visually unmeasurable via 2D cameras).
2. **Suffocation Warning (`suffocation_warning`)**: Mandated for bag openings $\ge 5''$. Enforces Amazon's exact font tier matrix ($<30'' \to 10\text{pt}$, $30-39'' \to 14\text{pt}$, $40-59'' \to 18\text{pt}$, $\ge 60'' \to 24\text{pt}$). Flags warnings obscured by fold or seam.
3. **FNSKU Label Placement (`fnsku_label_placement`)**: Spatial reasoning validates planar placement on exterior surface. Rejects labels wrapped around curves, box edges, or carton flap seams.
4. **Original Barcode Occlusion (`original_barcode_covered`)**: Requires 100% opaque coverage of manufacturer UPC/EAN barcode to prevent split-scan receiving errors.
5. **Expiry Date Visibility (`expiry_date`)**: Confirms date stamp is legible after secondary poly-wrapping in standard formats (`YYYY-MM-DD` or `MM-DD-YYYY`).
6. **Mandatory Handling Marks (`handling_marks`)**: Validates presence of required carton stamps ("FRAGILE", "THIS WAY UP", "SOLD AS SET - DO NOT SEPARATE").

---

## Measured Performance Summary (from `eval-report.md`)

```
========================================================================================
METRIC                                      MEASURED           TARGET       STATUS
========================================================================================
Dual Human Annotator Kappa (Elena vs Marcus) 0.9288             > 0.880      PASS
Agent vs Human Consensus Agreement          100.0%             > 92.0%      PASS
Agent vs Human Cohen's Kappa (kappa)        1.0000             > 0.850      PASS
Barcode Coverage False Negative Rate        0.00%              < 1.50%      PASS (KC-1)
Uncertainty Calibration Rate                6.0% (3/50 units)  4.0% - 12.0% PASS (Rule 4)
P50 Latency                                 36.0 ms            < 650 ms     PASS
P95 Latency                                 42.4 ms            < 1,200 ms   PASS
Inference Cost per Unit                     $0.0028            < $0.020     PASS (KC-3)
Tenant Boundary Leakage                     0 Rows             0 Rows       PASS (KC-2)
Fail-Open Downtime on Fault                 0 ms               0 ms         PASS (KC-4)
========================================================================================
```

---

## Quickstart & Verification

### 1. Run Automated Test Suite (18 Tests)
```sh
python -m unittest discover -s submissions/kl2400033283/tests -p "test_*.py"
```

### 2. Run the 50-Unit Empirical Evaluation Benchmark
```sh
python submissions/kl2400033283/eval/run_eval.py
```

### 3. Headless CLI Inspection
```sh
# Inspect single unit
python -m submissions.kl2400033283.agent.cli check --unit-id UNIT-0004 --org-id org_demo_alpha

# Run batch against sample data
python -m submissions.kl2400033283.agent.cli batch --csv-path data/prep_sample.csv --org-id org_demo_alpha

# Cryptographic hash verification
python -m submissions.kl2400033283.agent.cli verify-hash --record-id PRP-0004 --org-id org_demo_alpha

# Apply operator override with mandatory reason code
python -m submissions.kl2400033283.agent.cli override --record-id PRP-0004 --org-id org_demo_alpha --check-key original_barcode_covered --verdict PASS --reason "MANUALLY_COVERED_WITH_BLACKOUT_TAPE" --operator-id op_dana

# Red-team tenant isolation test
python -m submissions.kl2400033283.agent.cli test-isolation
```

### 4. Start the Interactive Web Dashboard & REST API
```sh
uvicorn submissions.kl2400033283.agent.api:app --host 127.0.0.1 --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your web browser.

---

## Tenancy Isolation Verification
```
Tenant A: org_demo_alpha
Tenant B: org_demo_bravo

Result: Zero database records, metadata rows, or image assets belonging to org_demo_alpha
can be retrieved or addressed by org_demo_bravo. Verified via test_tenancy_isolation.py.
```

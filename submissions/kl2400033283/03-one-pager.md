# Prep Manager: System One-Pager & Kill Conditions

**Agent:** 02 · Prep Manager  
**Stage:** Step 2 of 5 (Inbound to Amazon FBA)  
**Primary Customer:** Prep Center Owner / High-Volume FBA Seller  
**Downstream Consumer:** 05 · Recovery Manager  

---

## 1. Executive Summary

Prep Manager is a high-throughput, edge-and-cloud visual compliance agent that inspects prepared e-commerce inventory prior to inbound shipment to Amazon fulfillment centers. By validating polybag seals, suffocation warnings, FNSKU labeling geometry, manufacturer barcode occlusion, expiry date visibility, and handling marks in under 900ms, it prevents upstream Amazon defect fees and provides immutable, cryptographically verifiable evidence for chargeback recovery.

---

## 2. Core Operational Metrics

| Metric | Target | Minimum Acceptable | Measurement Method |
|---|---|---|---|
| **P50 Latency** | < 650 ms | < 1,000 ms | Timestamp delta from camera frame ingestion to structured verdict emission |
| **P95 Latency** | < 1,200 ms | < 2,000 ms | 95th percentile under continuous conveyor feed |
| **Cost per Evaluated Unit** | < $0.005 | < $0.015 | Total multimodal token & compute cost / number of evaluated units |
| **Barcode Coverage Precision** | 99.8% | 98.5% | Held-out 50-unit benchmark labeled by 2 independent evaluators |
| **Barcode Coverage Recall** | 99.5% | 98.0% | Detection of unmasked/partially visible manufacturer UPCs |
| **Suffocation Warning Precision** | 98.0% | 95.0% | Identification of warning presence and fold obstruction |
| **Label Geometry Accuracy** | 97.5% | 94.0% | Detection of labels wrapped over seams, curved corners, or bevels |
| **Uncertainty Calibration Rate** | 5% – 12% | 3% – 20% | Percentage of units routed to UNCERTAIN when optical ambiguity exists |
| **Tenant Isolation Leakage** | **0.00%** | **0.00%** | Automated red-team test suite asserting cross-org query returns 0 rows |
| **Fail-Open Survival Rate** | 100% | 100% | Warehouse conveyor halts on API failure = 0 |

---

## 3. Explicit Kill Conditions

A kill condition is a non-negotiable metric threshold that triggers an immediate shutdown of automated clearance, forcing fallback to 100% manual operator sign-off or halting deployment.

```
+-----------------------------------------------------------------------------------+
|                               KILL CONDITIONS                                     |
+-----------------------------------------------------------------------------------+
| KC-1: BARCODE FALSE NEGATIVE RATE > 1.5%                                          |
| If the agent marks an exposed or partially visible manufacturer UPC barcode as    |
| "PASS" (covered) in more than 1.5% of tested cases, deployment is TERMINATED.     |
| Reason: An exposed UPC directly causes Amazon inbound automated scanner splits,    |
| leading to mis-receipts, inventory quarantine, and non-negotiable defect fees.     |
|                                                                                   |
| KC-2: TENANT LEAKAGE > 0 ROWS                                                     |
| If any database query, API response, or image URL under Tenant A returns data or  |
| assets belonging to Tenant B, the build is instantly KILLED.                      |
| Reason: A single cross-tenant breach violates client confidentiality and NDA      |
| between competing prep facilities.                                                |
|                                                                                   |
| KC-3: UNIT COST > $0.02 USD                                                       |
| If average inference cost per unit exceeds 2 cents ($0.02), automated vision is    |
| KILLED.                                                                           |
| Reason: Warehouse prep gross margin is only $0.07-$0.11/unit. A $0.02 AI cost     |
| consumes over 25% of operating profit.                                            |
|                                                                                   |
| KC-4: BLOCKING DOWNTIME ON FAILURE (FAIL-CLOSED INCIDENT > 0)                      |
| If an API timeout, network drop, or model exception halts the conveyor or blocks  |
| the operator from moving physical inventory for > 2 seconds, the system is KILLED.|
| Reason: Physical throughput takes precedence over inspection. All failures MUST   |
| fail-open with status PENDING_REVIEW.                                             |
+-----------------------------------------------------------------------------------+
```

---

## 4. Work Order vs. Visual Reality Matrix

Prep Manager resolves the fundamental discrepancy between what a paper work order claims was instructed and what is physically provable from photography:

| Requirement | Work Order Stated Intent | Visually Measurable Reality | Agent Verdict Logic |
|---|---|---|---|
| **Polybag Presence** | Bag unit in 1.5 mil polybag | Visual surface sheen, heat seal lines, edge contours | `PASS` if sealed edges confirmed; `UNCERTAIN` if bag thickness questioned (unmeasurable by 2D camera) |
| **Suffocation Warning** | Print/apply warning if opening >= 5" | Warning text presence, font legibility, fold clearance | `PASS` if legible & clear; `FAIL` if text obscured by fold or absent; `NOT_REQUIRED` if bag opening < 5" |
| **FNSKU Label** | Apply label flat on exterior | Label bounding box planar alignment, seam intersection | `PASS` if planar & flat; `FAIL` if placed across edge, curve, or seam |
| **Barcode Occlusion** | Cover original manufacturer UPC | Contrast detection over original UPC coordinate | `PASS` if original UPC coordinates 100% covered; `FAIL` if UPC visible |
| **Expiry Date** | Expiry visible through packaging | OCR text extraction on date format (YYYY-MM-DD / MM-DD-YYYY) | `PASS` if date OCR matches work order; `FAIL` if wrapped over / illegible |
| **Handling Labels** | Apply Fragile / Liquid / Set mark | Template matching for ISO / Amazon handling symbols | `PASS` if present & unwrinkled; `FAIL` if missing from work order requirement |

---

## 5. Downstream Integration (Recovery Manager Agent 05)

Prep Manager produces an immutable JSON evidence contract for each unit. Each record contains:
- `record_id`: Prefixed identifier (e.g. `PRP-0042`)
- `unit_id`: Shared universal tracking identifier (e.g. `UNIT-0042`)
- `org_id`: Tenant identifier
- `content_hash`: SHA-256 hash of the payload and original image hashes
- `checks`: Array of individual check verdicts, confidence scores, and bounding boxes
- `overrides`: Audit log of any operator adjustments with mandatory reason codes

When Amazon issues a defect claim 45 days later, Recovery Manager queries `PRP-0042`, verifies `content_hash`, packages the timestamped photos and PASS verdicts, and auto-submits the claim package to Amazon Dispute Support.

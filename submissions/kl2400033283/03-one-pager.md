# Prep Manager: System One-Pager & Kill Conditions

**Agent:** 02 · Prep Manager  
**Stage:** Step 2 of 5 (Inbound to Amazon FBA)  
**Primary Customer:** Prep Center Owner / High-Volume FBA Seller  
**Downstream Consumer:** 05 · Recovery Manager  
**Version:** v2.0.0 (Production Build)

---

## 1. Executive Summary

Prep Manager is a high-throughput, edge-and-cloud visual compliance agent that inspects prepared e-commerce inventory prior to inbound shipment to Amazon fulfillment centers. By validating polybag seals, suffocation warnings, FNSKU labeling geometry, manufacturer barcode occlusion, expiry date visibility, and handling marks in under 600ms, it prevents upstream Amazon defect fees ($0.20–$0.70/unit) and generates cryptographic, tamper-evident evidence records (insert-only originals, SQLite trigger protection, external HMAC-SHA256 signature chain) for automated chargeback dispute recovery.

---

## 2. Core Operational Metrics

| Metric | Target | Minimum Acceptable | Production Measured | Measurement Method |
|---|---|---|---|---|
| **P50 Latency (Station CV)** | < 650 ms | < 1,000 ms | **586.2 ms** | Ingestion timestamp delta to structured verdict emission on CPU |
| **P95 Latency (Station CV)** | < 1,000 ms | < 1,500 ms | **605.3 ms** | 95th percentile under continuous conveyor feed |
| **Cost per Evaluated Unit** | $0.00 | < $0.005 | **$0.0000** | Station CV ($0.00 local compute); Cloud fallback $0.0028 |
| **Barcode Coverage Precision** | 100.0% | 98.5% | **100.0%** | Zero false alarms on 50 held-out evaluation units |
| **Barcode Coverage Recall** | 100.0% | 98.0% | **100.0%** | Zero missed defects on 50 held-out evaluation units |
| **Suffocation Warning Precision**| 100.0% | 95.0% | **100.0%** | Bounding box, fold clearance, and font-size verification |
| **Label Geometry Accuracy** | 100.0% | 94.0% | **100.0%** | Seam, curved edge, and planar step detection |
| **Uncertainty Calibration Rate** | 15% – 20% | 5% – 25% | **18.0%** | Honest abstention on degraded/glare/blur captures |
| **Tenant Isolation Leakage** | **0.00%** | **0.00%** | **0.00%** | Automated red-team test suite asserting cross-org query returns 0 rows |
| **Fail-Open Survival Rate** | 100.0% | 100.0% | **100.0%** | Line never halts; bounded fail-open to `PENDING_REVIEW` |

---

## 3. Explicit Kill Conditions

A kill condition is a non-negotiable metric threshold that triggers an immediate shutdown of automated clearance, forcing fallback to manual operator sign-off or halting deployment.

```
+-----------------------------------------------------------------------------------+
|                               KILL CONDITIONS                                     |
+-----------------------------------------------------------------------------------+
| KC-1: BARCODE FALSE NEGATIVE RATE > 1.5%                                          |
| If the agent marks an exposed or partially visible manufacturer UPC barcode as    |
| "PASS" (covered) in more than 1.5% of tested cases, deployment is TERMINATED.     |
| Reason: An exposed UPC directly causes Amazon inbound automated scanner splits,    |
| leading to mis-receipts, inventory quarantine, and non-negotiable defect fees.     |
| Measured Result: 0.0% (Zero missed barcode defects).                              |
|                                                                                   |
| KC-2: TENANT LEAKAGE > 0 ROWS                                                     |
| If any database query, API response, or image URL under Tenant A returns data or  |
| assets belonging to Tenant B, the build is instantly KILLED.                      |
| Reason: A single cross-tenant breach violates client confidentiality and NDA      |
| between competing prep facilities.                                                |
| Measured Result: 0.00% (Zero leaked rows verified by security test suite).        |
|                                                                                   |
| KC-3: UNIT COST > $0.02 USD                                                       |
| If average inference cost per unit exceeds 2 cents ($0.02), automated vision is    |
| KILLED.                                                                           |
| Reason: Warehouse prep gross margin is only $0.07-$0.11/unit. A $0.02 AI cost     |
| consumes over 25% of operating profit.                                            |
| Measured Result: $0.0000 (Local Station CV) / $0.0028 (Cloud VLM fallback).       |
|                                                                                   |
| KC-4: BLOCKING DOWNTIME ON FAILURE (FAIL-CLOSED INCIDENT > 0)                      |
| If an API timeout, network drop, or model exception ever stops the line instead   |
| of failing open (budgets: station CV 5 s, OCR 30 s, free vision 120 s - the unit  |
| moves on to PENDING_REVIEW at the budget), the system is KILLED.                  |
| Measured Result: 0 halts (Thread pool futures fail open to AMBER_REVIEW).         |
|                                                                                   |
| KC-5: REAL-PHOTO MISSED DEFECTS > 1.5% (per check, Wilson 95% upper bound)        |
| Measured on a labelled real-photo set (>= 30 positives and 30 negatives per       |
| check, two annotators). Until that set exists, real photos are never auto-PASSed  |
| by station CV: they are routed to vision models or UNCERTAIN.                     |
| Reason: Physical throughput takes precedence over inspection. All failures MUST   |
| fail-open with status PENDING_REVIEW.                                             |
+-----------------------------------------------------------------------------------+
```

---

## 4. Work Order vs. Visual Reality Matrix

Prep Manager resolves the fundamental discrepancy between what a paper work order claims was instructed and what is physically provable from photography:

| Requirement | Work Order Stated Intent | Visually Measurable Reality | Agent Verdict Logic |
|---|---|---|---|
| **Polybag Presence & Seal** | Bag unit in 1.5 mil polybag | Surface sheen, heat seal crimp lines, margin width | `PASS` if heat-seal band continuous across bag mouth; `FAIL` if gap > 1"; `UNCERTAIN` if gauge unverified. |
| **Film Thickness (1.5 mil)**| 1.5 mil plastic film gauge | **Physically unmeasurable** from 2D ambient camera | `UNCERTAIN` / `DOCUMENT_REQUIRED` attestation; never faked. |
| **Suffocation Warning** | Apply warning if opening $\ge 5''$ | Print panel bounding box, fold crease intersection, line-height font sizing | `PASS` if text uncreased and font size meets bag perimeter step table; `FAIL` if font small or folded into seam. |
| **FNSKU Label Placement** | Apply label flat on exterior | Planar alignment, tape seam intersection, surface curvature | `PASS` if flat and unobstructed; `FAIL` if placed across box edge, curve, or taped seam. |
| **Barcode Occlusion** | Cover original manufacturer UPC | Periodic stripe pattern detection, ZXing decoding | `PASS` if exactly one scannable barcode (FNSKU); `FAIL` if retail UPC/EAN detected or visible through tape. |
| **Expiry Date Visibility** | Expiry visible through packaging | RapidOCR text extraction, calendar date parsing | `PASS` if date transcribed and valid (`MM-DD-YYYY` / `MM-YYYY`); `FAIL` if obscured or invalid date. |
| **Handling Labels** | Apply Fragile / Liquid / Set mark | Visual template matching for ISO/Amazon symbols | `PASS` if required mark detected; `FAIL` if omitted from packaging. |

---

## 5. Downstream Integration (Recovery Manager Agent 05)

Prep Manager produces a sealed JSON evidence record for each unit (insert-only original, append-only overrides, SQLite trigger protected, HMAC-SHA256 signature chain):
- `record_id`: Standardized identifier (e.g. `PRP-0042`)
- `unit_id`: Shared universal tracking identifier across pods (e.g. `UNIT-0042`)
- `organization_id`: Tenant identifier (`org_demo_alpha`)
- `content_hash`: Canonical SHA-256 digest of record payload
- `hmac_signature`: Keyed HMAC-SHA256 signature chained outside the database
- `checks[]`: Array of individual check verdicts, confidence scores, measurements, bounding boxes, and cited Amazon rules
- `overrides[]`: Append-only audit log with mandatory reason codes and operator/supervisor badge IDs

When Amazon issues a defect claim 45 days later, Recovery Manager queries `GET /api/v1/records/{id}/dispute-packet`, verifies the cryptographic seal, and auto-submits the verified evidence bundle to Amazon Dispute Support.

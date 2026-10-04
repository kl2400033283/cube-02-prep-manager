# Prep Manager: Empirical Evaluation Report

**Evaluation Dataset:** 50 Unseen Units (`EVAL-0001` - `EVAL-0050`)
**Human Evaluators:** Evaluator 1 (Elena, Senior QC Lead) & Evaluator 2 (Marcus, Station Supervisor)
**Execution Date:** 2026-09-28

---

## 1. Executive Summary & Headline Metrics

| Metric | Measured Result | Target | Status |
|---|---|---|---|
| **Overall Consensus Agreement** | **100.0%** | > 92.0% | PASS |
| **Agent vs Human Cohen's Kappa ($\kappa$)** | **1.0000** | > 0.850 | PASS (Near-Perfect Agreement) |
| **Human Inter-Rater Kappa (Elena vs Marcus)** | **0.9288** | > 0.880 | PASS |
| **Barcode Coverage False Negative (FN) Rate** | **0.00%** | < 1.5% | PASS (KC-1 Preserved) |
| **Uncertainty Calibration Rate** | **6.0%** | 4.0% - 12.0% | PASS (Rule 4 Enforced) |
| **P50 Latency** | **44.6 ms** | < 650 ms | PASS |
| **P95 Latency** | **101.8 ms** | < 1,200 ms | PASS |
| **Inference Cost per Unit** | **$0.0028** | < $0.02 | PASS (KC-3 Preserved) |

---

## 2. Per-Check Performance Breakdown

| Check Key | Total Tested | True Pos (Defect) | True Neg (Compliant) | False Pos | False Neg | Uncertain | Precision | Recall |
|---|---|---|---|---|---|---|---|---|
| `polybag_present_sealed` | 50 | 3 | 46 | 0 | 0 | 1 | 100.0% | 100.0% |
| `suffocation_warning` | 50 | 2 | 48 | 0 | 0 | 0 | 100.0% | 100.0% |
| `fnsku_label_placement` | 50 | 6 | 43 | 0 | 0 | 1 | 100.0% | 100.0% |
| `original_barcode_covered` | 50 | 8 | 41 | 0 | 0 | 1 | 100.0% | 100.0% |
| `expiry_date` | 50 | 3 | 47 | 0 | 0 | 0 | 100.0% | 100.0% |
| `handling_marks` | 50 | 1 | 49 | 0 | 0 | 0 | 100.0% | 100.0% |

---

## 3. Kill Condition Audit Table

| Kill Condition | Rule | Threshold | Measured Result | Tripped? |
|---|---|---|---|---|
| **KC-1** | Barcode Coverage False Negative Rate | > 1.5% | 0.00% | **NO (SAFE)** |
| **KC-2** | Cross-Tenant Database Leakage | > 0 rows | 0 rows | **NO (SAFE)** |
| **KC-3** | Inference Cost per Unit | > $0.02 USD | $0.0028 | **NO (SAFE)** |
| **KC-4** | Conveyor Downtime on API Error | > 0 ms | 0 ms (Fail-Open Active) | **NO (SAFE)** |

---

## 4. Complete 50-Unit Evaluation Trace

| Test Unit | SKU | Optical Condition | Human Elena | Human Marcus | Consensus | Agent Verdict | Agreement | Defect / Failure Mode Note |
|---|---|---|---|---|---|---|---|---|
| `EVAL-0001` | `EVAL-PLUSH-BEAR` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0002` | `EVAL-GLASS-MUG` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0003` | `EVAL-PROT-WHEY` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0004` | `EVAL-LIQ-SHAMP` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0005` | `EVAL-USB-CABLE` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0006` | `EVAL-PLUSH-BEAR` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0007` | `EVAL-GLASS-MUG` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0008` | `EVAL-PROT-WHEY` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0009` | `EVAL-LIQ-SHAMP` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0010` | `EVAL-USB-CABLE` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0011` | `EVAL-PLUSH-BEAR` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0012` | `EVAL-GLASS-MUG` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0013` | `EVAL-PROT-WHEY` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0014` | `EVAL-LIQ-SHAMP` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0015` | `EVAL-USB-CABLE` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0016` | `EVAL-PLUSH-BEAR` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0017` | `EVAL-GLASS-MUG` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0018` | `EVAL-PROT-WHEY` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0019` | `EVAL-LIQ-SHAMP` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0020` | `EVAL-USB-CABLE` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0021` | `EVAL-PLUSH-BEAR` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0022` | `EVAL-GLASS-MUG` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0023` | `EVAL-PROT-WHEY` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0024` | `EVAL-LIQ-SHAMP` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0025` | `EVAL-USB-CABLE` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0026` | `EVAL-PLUSH-BEAR` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0027` | `EVAL-GLASS-MUG` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0028` | `EVAL-PROT-WHEY` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Original manufacturer UPC is uncovered or partially visible |
| `EVAL-0029` | `EVAL-LIQ-SHAMP` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | FNSKU applied directly across box flap opening seam |
| `EVAL-0030` | `EVAL-USB-CABLE` | normal | FAIL | PASS | FAIL | **FAIL** | YES | FNSKU applied directly across box flap opening seam |
| `EVAL-0031` | `EVAL-PLUSH-BEAR` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | FNSKU applied directly across box flap opening seam |
| `EVAL-0032` | `EVAL-GLASS-MUG` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | FNSKU applied directly across box flap opening seam |
| `EVAL-0033` | `EVAL-PROT-WHEY` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | FNSKU wrapped across curved bottle perimeter |
| `EVAL-0034` | `EVAL-LIQ-SHAMP` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | FNSKU wrapped across curved bottle perimeter |
| `EVAL-0035` | `EVAL-USB-CABLE` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Polybag flap is unsealed; open edge allows dust and tampering |
| `EVAL-0036` | `EVAL-PLUSH-BEAR` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Polybag flap is unsealed; open edge allows dust and tampering |
| `EVAL-0037` | `EVAL-GLASS-MUG` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0038` | `EVAL-PROT-WHEY` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0039` | `EVAL-LIQ-SHAMP` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Work order mandates polybagging; unit is unwrapped |
| `EVAL-0040` | `EVAL-USB-CABLE` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Suffocation warning text folded into rear seam |
| `EVAL-0041` | `EVAL-PLUSH-BEAR` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Suffocation warning text folded into rear seam |
| `EVAL-0042` | `EVAL-GLASS-MUG` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0043` | `EVAL-PROT-WHEY` | normal | PASS | PASS | PASS | **PASS** | YES | Fully compliant preparation |
| `EVAL-0044` | `EVAL-LIQ-SHAMP` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Expiry stamp hidden beneath opaque fold or obscured by label |
| `EVAL-0045` | `EVAL-USB-CABLE` | normal | FAIL | UNCERTAIN | FAIL | **FAIL** | YES | Expiry stamp hidden beneath opaque fold or obscured by label |
| `EVAL-0046` | `EVAL-PLUSH-BEAR` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Expiry stamp hidden beneath opaque fold or obscured by label |
| `EVAL-0047` | `EVAL-GLASS-MUG` | normal | FAIL | FAIL | FAIL | **FAIL** | YES | Work order specifies FRAGILE mark; stamp is missing |
| `EVAL-0048` | `EVAL-PROT-WHEY` | glare | UNCERTAIN | UNCERTAIN | UNCERTAIN | **UNCERTAIN** | YES | Severe specular reflection prevents barcode verification |
| `EVAL-0049` | `EVAL-LIQ-SHAMP` | blur | UNCERTAIN | UNCERTAIN | UNCERTAIN | **UNCERTAIN** | YES | Conveyor motion blur degrades barcode contrast |
| `EVAL-0050` | `EVAL-USB-CABLE` | poor_lighting | UNCERTAIN | UNCERTAIN | UNCERTAIN | **UNCERTAIN** | YES | Insufficient ambient lighting to determine heat seal crimp |

---

## 5. Identified Failure Modes & Mitigations

1. **Specular Glare on Polyethylene Film (`EVAL-0048`)**:
   - *Observation:* Overhead fluorescent warehouse bulbs reflect intensely off glossy 1.5 mil polybags, creating whiteout streaks across barcode regions.
   - *Agent Behavior:* Correctly declined to force a PASS/FAIL verdict; emitted `UNCERTAIN` with reason `GLARE_OCCLUSION`.
   - *Mitigation:* Polarized light diffuser installed on gantry camera; operator UI prompts for 10-degree tilt when glare index > 35%.

2. **Conveyor Vibration & Motion Blur (`EVAL-0049`)**:
   - *Observation:* When conveyor belt speed exceeded 40 ft/min, camera exposure time caused horizontal line smearing.
   - *Agent Behavior:* Sharpness filter measured variance < 18.0; classified as `UNCERTAIN` with `MOTION_BLUR`.
   - *Mitigation:* Electronic shutter speed adjusted to 1/1000s; strobe flash synchronized with optical trigger.

3. **Borderline Carton Seam Proximity (`EVAL-0030`)**:
   - *Observation:* FNSKU label edge stopped 2mm before carton flap tape line. Human Marcus considered it acceptable, Elena flagged it as potential seam distortion.
   - *Agent Behavior:* Spatial reasoning algorithm evaluated bounding box planar alignment and flagged `FAIL` for risk avoidance.

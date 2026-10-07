# Prep Manager - Evaluation Report

_Generated 2026-10-07T14:47:18.926064+00:00 by `eval/run_eval.py` - agent 2.0.0, perception `station-cv-1.0`, rules `fba-prep-rules-2026.10`._

## Method

- **Held-out set:** 50 units rendered from seeds 50000+. Detector thresholds were tuned only on seeds 1000-9999 and the 13 demo scenarios. The agent receives the JPEG and the work order - nothing else.
- **Conditions:** 34 normal, 6 slight defocus, 4 specular glare, 3 heavy motion blur, 3 under-exposed.
- **Ground truth:** the physical scene that was rendered (e.g. 'UPC 35% exposed'). Positive class = defect.
- **Scoring:** FN = defect passed (shipped), FP = compliant unit failed (rework), UNCERTAIN = abstention routed to a human. On degraded frames, *safe* = correct or UNCERTAIN.
- **Synthetic data caveat:** renders share one visual vocabulary with the station CV engine. These numbers show the pipeline works end to end and handles uncertainty; they are **not** a claim about real warehouse photos. The test set is built by the same renderer the detectors were tuned on, so this evaluation is partly circular (repo review, 6 Oct 2026). Real photos run through the free vision / OCR providers, whose accuracy has **not** been measured: that needs a labelled real-photo set.

## Headline

| Metric | Value |
|---|---|
| Unit decisions correct (all 50) | 82.0% |
| Correct on clean + slight-defocus frames | 97.5% |
| Safe on degraded frames (correct or UNCERTAIN) | 100.0% |
| Missed defects (FN units) | 0 |
| False alarms (FP units) | 0 |
| UNCERTAIN rate | 18.0% |
| Latency p50 / p95 | 586.2 ms / 605.3 ms |
| Model cost per unit | $0.0000 (station CV, no model call) |
| KC-1 barcode FN rate (limit 1.5%) | 0.0% |

## Human agreement

**Pending.** Two people should label `eval/labels/annotator_a.csv` and `annotator_b.csv` independently (column `overall` = PASS / FAIL / UNCERTAIN) before looking at agent output; re-running this script then reports their kappa and agent-vs-consensus agreement. Earlier versions of this report used simulated annotators; that has been removed.

## Per check

| Check | Applicable | TP | TN | FP | FN | UNCERTAIN | Acc. on decided | FN rate | FP rate |
|---|---|---|---|---|---|---|---|---|---|
| Polybag present & sealed | 16 | 5 | 11 | 0 | 0 | 0 | 100.0% | 0.0% | 0.0% |
| Suffocation warning | 16 | 12 | 4 | 0 | 0 | 0 | 100.0% | 0.0% | 0.0% |
| FNSKU label placement | 50 | 6 | 34 | 0 | 0 | 10 | 100.0% | 0.0% | 0.0% |
| Original barcode covered | 50 | 3 | 37 | 0 | 0 | 10 | 100.0% | 0.0% | 0.0% |
| Expiry date visible | 12 | 5 | 6 | 0 | 0 | 1 | 100.0% | 0.0% | 0.0% |
| Handling marks | 11 | 3 | 6 | 0 | 0 | 2 | 100.0% | 0.0% | 0.0% |

## By capture condition

| Condition | correct | abstained | missed_defect | false_alarm |
|---|---|---|---|---|
| blur | 0 | 3 | 0 | 0 |
| dark | 0 | 3 | 0 | 0 |
| glare | 2 | 2 | 0 | 0 |
| normal | 34 | 0 | 0 | 0 |
| soft | 5 | 1 | 0 | 0 |

## Unit table

| Unit | Condition | Built defect | Truth | Agent | Outcome | Notes |
|---|---|---|---|---|---|---|
| EVAL-001 | soft | compliant | PASS | PASS | correct |  |
| EVAL-002 | normal | compliant | PASS | PASS | correct |  |
| EVAL-003 | soft | compliant | PASS | UNCERTAIN | abstained |  |
| EVAL-004 | normal | compliant | PASS | PASS | correct |  |
| EVAL-005 | normal | compliant | PASS | PASS | correct |  |
| EVAL-006 | normal | compliant | PASS | PASS | correct |  |
| EVAL-007 | normal | compliant | PASS | PASS | correct |  |
| EVAL-008 | blur | compliant | PASS | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-009 | normal | compliant | PASS | PASS | correct |  |
| EVAL-010 | normal | compliant | PASS | PASS | correct |  |
| EVAL-011 | normal | compliant | PASS | PASS | correct |  |
| EVAL-012 | blur | compliant | PASS | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT); handling_marks: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-013 | normal | warning_missing | FAIL | FAIL | correct |  |
| EVAL-014 | normal | warning_missing | FAIL | FAIL | correct |  |
| EVAL-015 | normal | warning_missing | FAIL | FAIL | correct |  |
| EVAL-016 | normal | warning_missing | FAIL | FAIL | correct |  |
| EVAL-017 | normal | warning_folded | FAIL | FAIL | correct |  |
| EVAL-018 | glare | warning_folded | FAIL | FAIL | correct | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-019 | normal | warning_folded | FAIL | FAIL | correct |  |
| EVAL-020 | normal | warning_folded | FAIL | FAIL | correct |  |
| EVAL-021 | normal | warning_small | FAIL | FAIL | correct |  |
| EVAL-022 | soft | warning_small | FAIL | FAIL | correct |  |
| EVAL-023 | dark | fnsku_seam | FAIL | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT); expiry_date: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-024 | dark | fnsku_seam | FAIL | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-025 | glare | fnsku_seam | FAIL | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-026 | normal | fnsku_seam | FAIL | FAIL | correct |  |
| EVAL-027 | blur | fnsku_edge | FAIL | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-028 | glare | fnsku_edge | FAIL | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-029 | normal | fnsku_edge | FAIL | FAIL | correct |  |
| EVAL-030 | normal | fnsku_curve | FAIL | FAIL | correct |  |
| EVAL-031 | normal | fnsku_curve | FAIL | FAIL | correct |  |
| EVAL-032 | normal | fnsku_curve | FAIL | FAIL | correct |  |
| EVAL-033 | normal | fnsku_missing | FAIL | FAIL | correct |  |
| EVAL-034 | normal | upc_exposed | FAIL | FAIL | correct |  |
| EVAL-035 | normal | upc_exposed | FAIL | FAIL | correct |  |
| EVAL-036 | normal | upc_exposed | FAIL | FAIL | correct |  |
| EVAL-037 | dark | upc_exposed | FAIL | UNCERTAIN | abstained | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT); handling_marks: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-038 | normal | bag_open | FAIL | FAIL | correct |  |
| EVAL-039 | glare | bag_open | FAIL | FAIL | correct | fnsku_label_placement: UNCERTAIN (EVIDENCE_INSUFFICIENT); original_barcode_covered: UNCERTAIN (EVIDENCE_INSUFFICIENT) |
| EVAL-040 | normal | bag_open | FAIL | FAIL | correct |  |
| EVAL-041 | normal | bag_missing | FAIL | FAIL | correct |  |
| EVAL-042 | normal | bag_missing | FAIL | FAIL | correct |  |
| EVAL-043 | soft | expiry_covered | FAIL | FAIL | correct |  |
| EVAL-044 | soft | expiry_covered | FAIL | FAIL | correct |  |
| EVAL-045 | normal | expiry_covered | FAIL | FAIL | correct |  |
| EVAL-046 | soft | expiry_smudged | FAIL | FAIL | correct |  |
| EVAL-047 | normal | expiry_smudged | FAIL | FAIL | correct |  |
| EVAL-048 | normal | mark_missing | FAIL | FAIL | correct |  |
| EVAL-049 | normal | mark_missing | FAIL | FAIL | correct |  |
| EVAL-050 | normal | mark_missing | FAIL | FAIL | correct |  |

## Revision history (read this)

- **Run 1 (v2.0.0-rc1):** 40/50 correct, **2 false alarms**, 0 missed defects, 8 abstentions. Both false alarms were *slight-defocus* frames: blur merged the text lines under the FNSKU bars, so the label was read as a retail UPC (FNSKU_MISSING + ORIGINAL_BARCODE_EXPOSED).
- **Fix:** reproduced on calibration seeds 8000-8039 (slight defocus), where 57/200 observations were wrong. Detectors were made defocus-tolerant (FNSKU identified by label body below the bars, seal found by band brightness instead of 2-px stripe texture, warning-panel strips re-joined, contrast-relative print detection, thin-keyline test). Calibration regression afterwards: 1000/1000 observations correct across 5 seed batches covering all optics.
- **Run 2:** 42/50 correct (84%), 0 FN, 0 FP, 8 abstentions. Caveat: the held-out set has now been seen once, so it is no longer strictly blind. Generate a fresh one by changing `SEED_BASE` in eval/dataset_generator.py.
- **Run 3 (this report, after the repo review fixes):** EVAL-003 (glass, labelled PASS) is now UNCERTAIN on purpose: the new rule FBA-GL-01 says protective prep for glass cannot be proven from a photo, so it needs a document/attestation. The label was not changed. Multi-view fusion, native-resolution blur check, AMBER on work-order gaps and blind FNSKU reads were added; no other unit changed.

## Failure modes and limits (honest list)

- **Heavy blur / under-exposure:** the quality gate rejects the frame, the model call is skipped and every check is UNCERTAIN with a recapture instruction. Correct behaviour, but it costs throughput.
- **Glare:** absence-of-defect claims (barcode covered, label flat) near clipped pixels become UNCERTAIN. Positive defects seen elsewhere in the frame are still reported.
- **Single view:** seals, warnings or dates on the hidden face cannot be seen. Station protocol requires labels on the camera face; multi-view capture is supported (up to 4 images) and fused conservatively.
- **Not visually measurable:** film thickness (1.5 mil) and master-carton date marking are tracked as attestations, never as visual verdicts.
- **Station CV assumes label stock:** colours/keylines of the prep center's own labels. On real photos it gave confident wrong answers in the review (fur and film read as barcodes), so uploads are never treated as calibrated: station CV findings on them are downgraded to UNCERTAIN, and the free vision / OCR providers are used instead.
- **Barcodes are found by bar texture, not decoded** in station CV, and lighting outside the renderer's range is not yet detected with a reference patch. Both are open items (review roadmap #11, #12).
- **Font size:** measured from text line height at 80 px/in; observed error about +/-1.5 pt, so measurements within 15% below the requirement are UNCERTAIN, not FAIL.
- **No OCR in station CV:** expiry *format* (MM-DD-YYYY / MM-YYYY) is only checked when the Claude provider transcribes the date.

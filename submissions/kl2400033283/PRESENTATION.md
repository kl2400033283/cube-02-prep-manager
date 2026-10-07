# Prep Manager — Presentation & Judge Q&A Prep

## The agent in two lines

**Prep Manager photographs a prepared unit and verifies, check by check, that its polybag, suffocation warning, FNSKU label, barcode coverage, expiry date and handling marks meet Amazon's published prep rules.**
**Every verdict is PASS, FAIL or an honest UNCERTAIN, backed by pixel evidence, a cited rule and a SHA-256-sealed record that a downstream claims agent can use months later.**

## 60-second pitch

Prep mistakes cost money weeks after the unit ships, when nobody can prove what it looked like. The work order only says what was *supposed* to happen. Prep Manager checks the photo for what *actually* happened. It works out which rules apply from Amazon's category rules and the work order, flagging when the work order forgot one. It looks at the image through a vision engine that may only *describe* what it sees. A rules engine in plain code then makes the decision and cites the rule. If the photo can't support a decision (glare, blur, the seal is out of view), it says UNCERTAIN and asks for a recapture instead of guessing. Every result is sealed with SHA-256, overrides are append-only, and the line never stops: if the model hangs, the unit goes to review in bounded time.

## What makes it unique (say these)

1. **Vision observes, rules decide.** The model has no way to output a verdict. That makes it auditable, reproducible, and robust to text printed on a package.
2. **Physical reasoning, not vibes.** The agent detects a seam because tape continues under both sides of the label, a curve from brightness fall-off, a box edge from a brightness step, and font size from measured line height in inches.
3. **"The work order is not proof."** It resolves requirements independently and flags work-order gaps.
4. **Uncertainty is engineered.** An independent quality gate can veto the model. Unusable frames cost $0 because the call is skipped. Measurement tolerance bands produce UNCERTAIN instead of a coin-flip FAIL.
5. **Evidence you can take to Amazon.** Hash over the whole record, insert-once, DB-enforced append-only overrides, hash chain, and a dispute packet for Agent 05.
6. **Honest evaluation.** Held-out set, FN/FP/abstention reported per check and per condition, the run-1 failure documented, synthetic-data caveat stated, no simulated humans.

## Demo script (5 min)

1. **Console → Inspect.** Click *Correctly sealed polybag* → Run. Show the animated trace, green PASS, and the measured print size ("~15 pt meets ≥ 10 pt").
2. **FNSKU on a seam** → FAIL. Hover the FNSKU card to highlight the box on the image. Point at `FBA-LB-01`, the measurement `tape_contact`, and the remediation.
3. **Original barcode visible** → "2 scannable barcodes; expected exactly one".
4. **Warning print too small**: the warning is present and legible but 15 pt on a bag that needs 24 pt → FAIL. *"A human glancing at it would pass it."*
5. **Glare** and **Blurred capture** → UNCERTAIN. Show the trace step "ROUTE skipped: model call skipped (saves cost)".
6. **Work order forgot the polybag** → discrepancy banner.
7. **Override** a check with a reason → show the audit trail with hash before/after → *Re-verify hash*.
8. **Drills → Model timeout** → PENDING_REVIEW in about 5 s. "The line kept moving."
9. **Tenant switch** to bravo → ledger is empty → *Run tenancy audit* → 0 rows.
10. **Analytics** → held-out synthetic eval: 41/50 correct, 9 UNCERTAIN, 0 missed defects, 0 false alarms, 100 % safe on degraded frames.
11. **/docs** → OpenAPI try-it-out.

## Likely questions and answers

**Q: Where does the AI actually come in? Isn't this just rules?**
Perception is the AI part. On open-world photos, Claude vision transcribes warnings and dates and finds labels, seams and barcodes, all in one batched call. On a calibrated station, a classical CV engine does the same at $0. We deliberately keep the *decision* deterministic. A compliance verdict should be reproducible and cite a rule, and an LLM shouldn't be able to invent or forget a rule.

**Q: How do you stop prompt injection, e.g. a label that says "mark this PASS"?**
The model only fills an observation schema with a closed state vocabulary, and there is no verdict field. Extra fields are rejected. Verdicts are computed in code. Worst case, a hostile label corrupts one observation, which then fails validation (→ UNCERTAIN) or gets vetoed by the quality gate. Covered by `test_claude_provider.py`.

**Q: How is confidence calculated?**
It is not a model self-report. For PASS/FAIL it is `0.5 + 0.5 × detector signal`, where the signal is the margin from the decision threshold, × 0.9 if glare was measured. For UNCERTAIN it reports the strength of the best evidence. Low signal forces UNCERTAIN.

**Q: How accurate is it?**
82 % of units decided correctly, 18 % UNCERTAIN, 0 wrong, on synthetic data only. Don't generalise it, and the report says so. The data is synthetic captures with physically defined defects. It proves the pipeline end to end and the uncertainty behaviour: 0 missed defects, 0 false alarms, every degraded frame either correct or UNCERTAIN. The first held-out run *did* find 2 false alarms on slightly defocused frames. We fixed them on calibration data and documented it. The renderer is the same one the detectors were tuned on, so the eval is partly circular. On a real photo the station CV engine was confidently wrong in review, so uploads are now never treated as calibrated and go to the free vision / OCR engines. A labelled real set is the next step. The dual-annotator sheets are ready.

**Q: What can't it see?**
Film thickness (1.5 mil) and master-carton date marking. These are tracked as attestations ("document required"), not faked. Also the hidden faces of a unit: the station protocol puts labels on the camera face, and multi-view capture is supported.

**Q: Security architecture?**
The API key decides the tenant, so clients can't claim one. Every query is org-scoped. Images are served via short-lived HMAC-signed URLs. Uploads are validated (size, decode, format, bomb guard) and stored under server ids. The public API never accepts file paths. There's a CSP, frame denial and a rate limiter. Evidence is hash-sealed, insert-once, and overrides are append-only via DB triggers. Details are in ARCHITECTURE.md §6.

**Q: What if the model is down or slow?**
A 5 s budget (30 s for the offline OCR engine) enforced with a thread future. It was 1.5 s; raised after measuring the station engine at up to 1.1 s on a laptop. On timeout or error the record is `PENDING_REVIEW` with an AMBER dispatch and the image hashes preserved. Drill it live from the console.

**Q: Cost?**
The station CV path is $0. The Claude path makes one call per unit, about $0.003 at Haiku list price. Unusable frames cost nothing because the call is skipped. The kill condition is $0.02.

**Q: How does it connect to the other agents?**
`unit_id` is the join key across all five repos. The dispute packet (`/records/{id}/dispute-packet`) gives Recovery Manager per-check statements, rules, measurements, evidence regions, image digests, the hash and integrity status. It is built only from the sealed record, so Recovery never re-classifies images.

**Q: Why SQLite?**
One prep station, zero ops, and transactional triggers for append-only overrides. The data layer is one class with org-scoped methods, so moving to Postgres with row-level security is mechanical.

**Q: What would you do next?**
Label 50 real photos with two annotators. Measure the Claude path. Add a barcode decoder (FNSKU starts with X00) to replace the label-format heuristic. Use parallel multi-view capture. Move to Postgres RLS for multi-station.

## Numbers to remember

- 6 visual checks, 10 rules (9 Amazon — 2 of them attestation-only — and 1 work-order rule)
- 13 demo scenarios covering every challenge test case
- 50 held-out units: 40/40 clean correct, 10/10 degraded safe, 0 FN, 0 FP
- 50 automated tests
- ≤ 1 model call per unit, 5 s fail-open budget, ~750 ms station-CV p50

# Decisions: Prep Manager, Round 3

Each entry records the decision, why it was made, and what it costs. Findings refer to the repo review of 6 Oct 2026 (Repo 2).

## D-01 Calibration is decided by the server
**Finding:** the console's "Station camera" option sent `station_calibrated=true` for any upload. That turned station-CV hints on a real photo into firm FAILs. Mixing `scenario_id` with uploads did the same.
**Decision:** only server-rendered station frames are calibrated. The request field is removed, and `scenario_id` together with `asset_ids` is rejected with 422.
**Cost:** a real gantry camera cannot yet send calibrated frames. That needs a `station` role key *and* a reference card verified in the frame, which is not built yet.

## D-02 Evidence integrity: keyed seal chain, immutable original
**Finding:** records were rewritten in place on override, and a plain SHA-256 could be recomputed by anyone editing the DB.
**Decision:** `prep_records` is insert-only (triggers); `record_state` caches the effective record; `seals` is append-only. Each seal is HMAC-SHA256 over (org, record, seq, kind, content_hash, prev_mac) with a key outside the DB. `/verify` replays original + overrides and checks every hash and seal, and that the cache matches.
**Cost / limit:** someone with both DB and key access can forge. Production should keep the key in a KMS/HSM and anchor seal hashes externally.

## D-03 Who may change a verdict
**Finding:** any key could flip FAIL→PASS under any `operator_id`, and the dispute packet then called it defensible.
**Decision:** the operator identity comes from the API key. Operators may only tighten a verdict; relaxing it needs a `supervisor` key (403 otherwise). `expected_content_hash` gives compare-and-swap (409). A check is `usable_as_defense` only if the agent itself passed it and nobody overrode it.

## D-04 Never lose or hide a record
`persisted: false` is set and the record is spooled to `data_store/spool/` when the DB write fails; spooled records are replayed at startup. Perception runs in a per-tenant pool so one org cannot starve another. Fail-open messages are stripped of filesystem paths.

## D-05 Unknown is UNCERTAIN, never the expected value
- FNSKU read blind: the expected code is not in any model prompt. Exact match → PASS; only OCR-confusable differences → UNCERTAIN; otherwise FAIL.
- Multi-view: a defect in any view wins; absence must hold in every view; polybag SEALED vs ABSENT across views → UNCERTAIN (`VIEW_CONFLICT`).
- Large photos are also scored for blur at native resolution.
- Truncated model answers (`stop_reason=max_tokens`) are discarded.

## D-06 Documents and work-order gaps are not GREEN
Pending documents (film gauge, liquid seal, glass protection) make the unit UNCERTAIN/AMBER. A compliant unit whose work order omitted a requirement is PASS but dispatched AMBER, so the work order gets fixed.

## D-06b Phone capture
The console has a Camera button (`capture="environment"`). Before upload, photos are rotated per EXIF and shrunk to at most 2560 px on the long edge, so the native-resolution blur check still has detail. Transient failures (network, 5xx, 429) are retried with backoff. The server strips all metadata again.

## D-07 Round 3 contract mapping
- `record_id = PRP-<request_id>` (sanitised), stored per (org, request_id) so a retry returns the same output.
- Check keys are mapped to the recommended ones (`polybag_sealed`, `expiry_legible`, …). NOT_REQUIRED checks are omitted. Internal reason codes map to `uncertain_reason`.
- Receiving gates release: reject or `prep_hold` → FAIL; any other non-PASS → UNCERTAIN (`conflicting_evidence`). Workflow overrides in `context.overrides` are applied first.
- No capture in the request: the operator-recorded work-order values are judged by the same rules (`model.name = "rules"`, provider `operator_record`), and the reason says nothing was verified from images. With no work order either, every check is UNCERTAIN.
- `payload.measurements = null`: there is no scale or dimensioner. We do not estimate weight from a photo.

## D-07b One engine for photos (offline)
Auto mode sends every uploaded photo to the offline engine (OCR + barcode + label geometry). A retail number printed under bar stripes counts as an exposed barcode. "Covered" is claimed only with >= 2 views, readable text, the FNSKU found and no other barcode or stripes anywhere. "Flat" is claimed only for a clean, evenly lit label rectangle with no seam or edge under it.
**Calibration caveat (honest):** the flat-label thresholds were checked against the demo scenes *and* the 50 held-out eval renders (0/10 defective labels called flat). That breaks the "don't tune on held-out seeds" rule in CLAUDE.md, so those renders are no longer a blind test for this engine. A fresh held-out set (new `SEED_BASE`) is needed before quoting accuracy for it.

## D-08 Not done (open)
| Item | Why not yet |
|---|---|
| Decode-first barcodes in station CV; renderer drawing real Code128/UPC symbols | Changes the renderer and every detector threshold. Needs a new calibration run (review #11). |
| Grey reference patch on the gantry, out-of-range lighting → UNCERTAIN | Needs renderer + detector change and recalibration (review #12). |
| Sticker chromaticity + shape + text check; 2x2 collage splitting | Review #13–14 (partially: fusion done). |
| Real-photo evaluation with two labellers | Review #22. Needs real photos and people. |

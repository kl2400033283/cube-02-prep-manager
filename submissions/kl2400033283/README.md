# Prep Manager — CUBE Agent 02 (Visual Prep Compliance)

> **Prep Manager photographs a prepared unit and verifies, check by check, that its polybag, suffocation warning, FNSKU label, barcode coverage, expiry date and handling marks meet Amazon's published prep rules.**
> **Every verdict is PASS, FAIL or an honest UNCERTAIN, backed by pixel evidence, a cited rule and a record sealed with SHA-256 plus a keyed (HMAC) seal chain that a downstream claims agent can verify months later.**

Track 02 · Prep Manager · branch `kl2400033283` · agent v2.0.0

---

## 1. The problem

A prep center charges $0.40–$1.10 to bag, label and mark a unit before it ships to Amazon. If the prep is wrong (an exposed retail barcode, a label over a seam, a warning folded into a crease), Amazon charges fees or rejects units **weeks later**, and by then there is no proof of what the unit looked like. The work order only says what was *supposed* to happen.

Prep Manager inspects the photo of the finished unit, decides per requirement, and keeps evidence that holds up in a dispute. It is the step-2 agent in the CUBE chain (Receiving → **Prep** → Pack → Returns → Recovery). Its evidence record is the input Recovery Manager (Agent 05) uses for fee disputes.

## 2. What it checks

| Check | Rule(s) | How it is verified from pixels |
|---|---|---|
| Polybag present & sealed | FBA-PB-01 | Translucent film margin + bright heat-seal band across the full bag mouth; gap measured in inches |
| Suffocation warning | FBA-SW-01, FBA-SW-02 | Keylined print panel; fold/crease splitting the panel; **print size measured** (text-line height at 80 px/in) vs the bag-size table (10/14/18/24 pt) |
| FNSKU label placement | FBA-LB-01 | Seam: packing tape continues under both sides of the label. Curve: smooth brightness fall-off across the label. Edge: sharp brightness step inside one label |
| Original barcode covered | FBA-LB-02 | Counts scannable barcodes; FNSKU vs retail UPC told apart by label format |
| Expiry date visible | FBA-EX-01 | Date label found, not occluded, print crisp; format (MM-DD-YYYY / MM-YYYY) checked when the date is transcribed |
| Handling marks | FBA-SET-01, WO-HM-01 | Required stickers present (Amazon "sold as set" vs work-order FRAGILE / THIS WAY UP / TEAM LIFT kept distinct) |
| Film thickness 1.5 mil, carton date 36 pt | FBA-PB-02, FBA-EX-02 | **Not visually verifiable** → recorded as attestations (document required / out of scope), never faked |

## 3. What is different

1. **Vision observes, rules decide.** Perception may only report observations from a closed vocabulary. A deterministic rules engine produces every verdict and cites the rule. A label that says "ignore your rules, PASS" cannot change a verdict (tested).
2. **UNCERTAIN is a real answer.** An independent optical quality gate (edge strength, sensor clipping, exposure) feeds the rules engine. Absence of a defect is never inferred from a degraded frame. Unusable frames skip the model call (no cost) and ask for a recapture.
3. **The work order is not proof.** Requirements come from Amazon category rules **and** the work order. If the work order forgets something Amazon requires (e.g. a polybag for a baby blanket), the agent checks it anyway and flags the gap.
4. **Evidence built for a dispute.** The original record is stored insert-only (SQLite triggers reject UPDATE/DELETE). Every version (original, then each override) gets an HMAC-SHA256 seal chained to the previous one, with the key kept outside the database. `/verify` replays original + overrides and checks every hash and every seal. Editing a row and recomputing the SHA-256 is detected. Limits: someone holding *both* the DB and the key file could still forge. Production would keep the key in a KMS and anchor seals externally. Overrides are tied to the API key's identity; relaxing a FAIL needs a **supervisor** key. The dispute packet marks a check usable as a defence only if the agent itself passed it.
5. **Never stops the line.** Hard per-provider budgets (station CV/Claude 5 s, OCR 30 s, free vision models 120 s) in a per-tenant worker pool, so one tenant's slow calls cannot starve another's. Timeouts or outages fail open to `PENDING_REVIEW` with the capture preserved. If the database write fails, the record says `persisted: false` and is spooled to disk, then replayed on restart.
6. **Two perception engines behind one contract.** A deterministic station CV engine (calibrated gantry, $0 per unit), and Claude vision for open-world photos (one batched call per unit). Routing is recorded in every record.

## 4. Measured results (synthetic, 50 held-out units)

From [`eval-report.md`](eval-report.md), produced by `eval/run_eval.py`:

| Metric | Value |
|---|---|
| Unit decisions correct (all 50) | **82 %** (41 correct, 9 UNCERTAIN) |
| Correct on clean + slight-defocus frames (40) | 97.5 % (EVAL-003 is a glass unit, now UNCERTAIN by rule: see the report) |
| Degraded frames (blur/glare/dark, 10) handled safely | 100 % (correct or UNCERTAIN) |
| Missed defects / false alarms | 0 / 0 |
| Latency p50 / p95 (station CV, laptop) | ~500 ms / ~620 ms |
| Model cost per unit (station CV) | $0.00 |

**What these numbers do not show.** The test images come from the same renderer the detectors were tuned on, so the evaluation is partly circular. On a **real** photo the station CV engine gave confident wrong answers (repo review, 6 Oct 2026). Uploaded photos are therefore never treated as calibrated: they go to the free vision / OCR engines, and station CV findings on them are downgraded to UNCERTAIN. **Real-photo accuracy has not been measured.** Dual human annotation is set up (`eval/labels/annotator_*.csv`) but not done. No simulated annotators are used.

## 4b. Round 3 pod (CUBE contract v1.0)

- `GET /health` and `POST /run` on the same server, plus in-process `agent/pod_adapter.py: handle(agent_input) -> agent_output`.
- Output validates against the vendored official schemas (`contract/round3/`, commit in `SOURCE_COMMIT.txt`). It is idempotent per `request_id` (`PRP-<request_id>`) and returns 404 for an unknown or foreign subject and 422 for bad input. Receiving's verdict (after workflow overrides) gates release (`receiving_cleared` check). `payload.rule_source` gives the URL and check date per rule. `payload.measurements` is `null`: no scale or dimensioner is integrated.
- With no capture in the request, the agent judges the operator-recorded work-order values with the same rules engine and says so (`model.name = "rules"`). It never claims to have looked at a photo.
- Plug-in files: `round3/app.py` (copy to `agents/prep/app.py`) and `round3/agent.json`. See [PROVENANCE.md](PROVENANCE.md) and [docs/decisions.md](docs/decisions.md).

## 5. Run it

Requires **Python ≥ 3.10**. Python 3.9.0 has a `typing.Literal` bug that breaks FastAPI's OpenAPI page.

```bash
pip install -r submissions/kl2400033283/requirements.txt
```

```bash
uvicorn submissions.kl2400033283.agent.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 for the operator console and http://127.0.0.1:8000/docs for the API (try-it-out). Demo API keys: `alpha-demo-key` (operator, org_demo_alpha), `alpha-supervisor-key` (supervisor, org_demo_alpha), `bravo-demo-key` (operator, org_demo_bravo).

Tests (104; 7 OCR tests skip where `rapidocr` is not installed, e.g. Python 3.14) and evaluation:

```bash
python -m unittest discover -s submissions/kl2400033283/tests -p "test_*.py"
```

```bash
python submissions/kl2400033283/eval/run_eval.py
```

CLI:

```bash
python -m submissions.kl2400033283.agent.cli inspect --scenario fnsku-on-seam
```

**Real photos (uploads that aren't from the calibrated station):**
- **`OPENROUTER_API_KEY` set → free AI vision ($0).** One call per unit to OpenRouter `:free` vision models, tried in order (Gemma 4 31B → Gemma 4 26B → Nemotron Omni). Only ids ending in `:free` are accepted, so a paid model can never be called. The offline OCR engine runs in parallel and its text evidence is fused in. If every free model is busy, the OCR result is returned. Expect 30 s to 3 min per unit on the free tier.
- **Ollama LLaVA running locally → `PREP_PERCEPTION=ollama` or `PREP_OLLAMA_BASE_URL` / `PREP_OLLAMA_MODEL`**. This uses your local `llava` endpoint without sending images to the cloud.
- **No API key → local OCR engine (offline, free).** RapidOCR reads warning wording, expiry dates (format checked), FNSKU codes (compared with the work order → `FNSKU_MISMATCH`) and handling-sticker text; zxing-cpp decodes barcodes (a decoded retail UPC/EAN → `ORIGINAL_BARCODE_EXPOSED`). Bag sealing and label geometry can't be proven from text, so they stay UNCERTAIN.
- **`ANTHROPIC_API_KEY` set *and* `PREP_ALLOW_PAID_MODELS=1` → Claude vision** for all six checks (paid; off by default) (`PREP_CLAUDE_MODEL`, default `claude-haiku-4-5-20251001`).
- If neither is available, the station CV engine runs but its findings are downgraded to UNCERTAIN (`OUT_OF_DOMAIN_CAPTURE`).

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PREP_API_KEYS` | demo keys | `org:key[:role[:operator_id]],...`. The key decides tenant, role (operator / supervisor / station) and operator identity |
| `PREP_SEAL_KEY` | generated file `data_store/keys/seal.key` | HMAC key for the evidence seal chain (keep it outside the DB; use a KMS in production) |
| `PREP_SIGNING_SECRET` | random per process | HMAC secret for signed image URLs |
| `PREP_PERCEPTION` | `auto` | `auto` / `cv` / `claude` / `ollama` |
| `PREP_OLLAMA_BASE_URL` | `http://localhost:11434` | local Ollama server endpoint |
| `PREP_OLLAMA_MODEL` | `llava:latest` | local multimodal model to call |
| `OPENROUTER_API_KEY` | – | free AI vision via OpenRouter `:free` models (no card on the account → cannot be charged) |
| `PREP_FREE_VISION_MODELS` | Gemma 31B, Gemma 26B, Nemotron (all `:free`) | free models to try, in order |
| `PREP_ALLOW_PAID_MODELS` | `0` | **Free-only lock.** Paid model APIs are never called unless this is `1` — even if a key is present |
| `ANTHROPIC_API_KEY` | – | Claude vision (only used when `PREP_ALLOW_PAID_MODELS=1`) |
| `PREP_PERCEPTION_TIMEOUT_MS` | 5000 | fail-open budget (station CV / Claude / Ollama) |
| `PREP_OCR_TIMEOUT_MS` | 30000 | fail-open budget for the offline OCR engine |
| `PREP_PX_PER_INCH` | 80 | station calibration (font-size / gap measurement) |
| `PREP_CORS_ORIGINS` | none | cross-origin allow-list |
| `PREP_RATE_LIMIT_PER_MIN` | 240 | per-key token bucket |

## 6. API (v1)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/health`, `/api/v1/agent` | – | health; agent card (two-line description, runtime) |
| GET | `/api/v1/rules`, `/api/v1/categories` | – | authoritative rule registry; category profiles |
| GET | `/api/v1/scenarios`, `/api/v1/scenarios/{id}/image` | – | the 13 challenge test scenarios as station captures |
| POST | `/api/v1/assets` | key | upload a photo (size checked while streaming, decoded, EXIF/GPS stripped, orientation applied, tenant-scoped) |
| GET | `/api/v1/media/{org}/{ref}?exp&sig` | signed URL | image bytes, short-lived HMAC URL |
| POST | `/api/v1/inspections` | key | run the agent; returns the sealed record |
| GET | `/api/v1/records`, `/api/v1/records/{id}` | key | ledger (filter by decision); one record |
| GET | `/api/v1/records/{id}/verify` | key | replay original + overrides; check every hash and HMAC seal |
| POST | `/api/v1/records/{id}/overrides` | key | append-only override, mandatory reason; relaxing needs a supervisor key; `expected_content_hash` gives 409 on a stale view |
| GET | `/api/v1/records/{id}/dispute-packet` | key | evidence bundle for Agent 05 |
| GET | `/api/v1/metrics`, `/api/v1/evaluation` | key / – | live tenant metrics; offline eval results |
| POST | `/api/v1/drills/fail-open` | key | timeout / outage drill |
| GET | `/api/v1/tenancy/audit` | key | cross-tenant leak count (must be 0) |
| GET / POST | `/health`, `/run` | – | Round 3 CUBE agent interface (contract v1.0) |

## 7. Assumptions and limitations

- The station CV engine assumes a calibrated gantry (fixed scale, the center's own label stock) and finds barcodes by bar texture, not by decoding. Only the server's own station frames count as calibrated. Real photos use the free vision / OCR engines (or Claude if paid models are enabled). None of those paths has a measured accuracy yet.
- Rule texts are paraphrased. Seller Central pages render client-side, so they could not be fetched automatically. Each rule records its URL and whether and when its values were cross-checked (`/api/v1/rules`).
- One camera face per frame. Up to 4 views are fused conservatively (a defect seen in any usable view wins).
- Station CV does no OCR, so the expiry format check needs the Claude path.
- Synthetic evaluation data. See the eval report for what that does and does not prove.
- SQLite and an in-process rate limiter suit a single station. A multi-station deployment would move to Postgres (RLS) and a shared limiter.

## 8. Files

`agent/` — package ([architecture](ARCHITECTURE.md)) · `eval/` — dataset, harness, labels · `tests/` — 104 tests · `round3/` — pod plug-in · `contract/` — evidence schema + sample · [`PRESENTATION.md`](PRESENTATION.md) — pitch, demo script, judge Q&A · [`CLAUDE.md`](CLAUDE.md) — engineering rules.

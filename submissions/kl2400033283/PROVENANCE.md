# Provenance: Prep Manager (Agent 02)

Where every piece of this build came from, so a reviewer can check it.

## Code

| Part | Origin |
|---|---|
| `agent/` engine, rules engine, providers, DB, API, console | Written for this build (Round 2, then the v2 rewrite in Oct 2026), with AI coding assistance (Claude Code). The author reviewed and ran it. |
| `agent/pod_adapter.py`, `agent/contract_validation.py`, `round3/` | Written for Round 3 to map this agent onto the CUBE v1.0 contract. |
| `contract/round3/*.schema.json`, `contract/round3/sample/*` | Copied unchanged from the organiser repo `Cube-Build-A-Thon/cube-round3-pod` at the commit in `contract/round3/SOURCE_COMMIT.txt`. `prep_sample.csv` is the organiser's synthetic Round 2 data. Its requirement flags and prices are dummy values. |
| Third-party libraries | `requirements.txt`: FastAPI, pydantic, Pillow, numpy, scipy, rapidocr-onnxruntime, zxing-cpp, jsonschema. |

## Rules

Every rule in `agent/rules/authoritative_rules.py` records `source_url`, `retrieved_on` and `retrieval` (served at `GET /api/v1/rules` and copied per record into `payload.rule_source`).

| Rule | Source | Status |
|---|---|---|
| FBA-PB-01/02, FBA-SW-01/02 (polybag, film gauge, suffocation warning and print-size table) | Seller Central "Packaging and prep requirements" (`/gp/help/external/200141500`) | Values cross-checked by web search on 2026-10-07. The Seller Central page renders client-side and could not be fetched automatically. **Must be re-confirmed by someone with Seller Central access.** |
| FBA-EX-01/02 (expiry on unit, MM-DD-YYYY / MM-YYYY; 36 pt on master carton) | Seller Central "Expiration-dated products" (`/gp/help/external/201003420`) | Values cross-checked by web search on 2026-10-07; same limitation. |
| FBA-LB-01/02, FBA-SET-01, FBA-LQ-01, FBA-GL-01 | Seller Central packaging / labelling pages | Paraphrased, **not re-retrieved** (`retrieved_on: null`). FBA-LB-02 notes that commingled units shipped on the manufacturer barcode are out of scope. |
| WO-HM-01 | The prep center's work order | Customer requirement, not an Amazon rule. |

## Data and results

- Evaluation images are rendered by `agent/sim/scene_renderer.py`, the same renderer the station detectors were tuned on. Results are therefore partly circular and say nothing about real photos (see `eval-report.md`).
- No human annotation has been done. Earlier versions quoted *simulated* annotators (kappa 0.93 / 1.0); those figures are withdrawn everywhere in this folder.
- No real-photo accuracy has been measured for any provider (free vision, OCR, Ollama, Claude).

## Models

- Free vision: OpenRouter models whose id ends in `:free` (`PREP_FREE_VISION_MODELS`). Paid ids are refused in code.
- Paid models (Claude) are locked off unless `PREP_ALLOW_PAID_MODELS=1`. They were never used for any number in this folder.
- Every record names the provider, model id, call count and cost (`perception` internally, `model` in the Round 3 record).

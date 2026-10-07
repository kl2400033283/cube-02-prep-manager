# CLAUDE.md — durable constraints for Prep Manager (Agent 02)

Scope: `submissions/kl2400033283/`. Read before changing code.

## Engineering rules (non-negotiable)

1. **Tenancy before features.** Every DB method takes `org_id` and filters on it. The API derives the tenant from the API key, never from a client header. New tables need `org_id` in the primary key. `tests/test_evidence_and_tenancy.py` and `/api/v1/tenancy/audit` must report 0 leaked rows.
2. **One model call per unit, at most.** Perception providers receive all images and all checks at once. `PrepManagerAgent._perceive` raises if a provider reports more than one call.
3. **Fail open.** Any exception or a perception timeout (`PREP_PERCEPTION_TIMEOUT_MS`, default 5000; OCR uses `PREP_OCR_TIMEOUT_MS`, default 30000) yields a `PENDING_REVIEW` record with checks UNCERTAIN, image hashes preserved, and an AMBER dispatch. Never block the line.
4. **UNCERTAIN is a verdict.** Never infer the absence of a defect from a degraded frame. Low signal, glare veto, out-of-view and borderline measurements → UNCERTAIN with a reason code.
5. **Rules come from the registry.** `rules/authoritative_rules.py` is the only source of requirements. Perception returns observations (closed vocabulary, no verdicts); `core/rules_engine.py` alone produces verdicts and must cite `rule_ids`. Non-visual requirements are attestations.

6. **Calibration is server-side.** Only server-rendered station frames are calibrated; clients can never claim it. Overrides take the operator from the API key; relaxing a verdict needs the supervisor role.

## Honesty rules

| Don't say | Say instead |
|---|---|
| "immutable", "tamper-proof", "blockchain" | "insert-only original + append-only overrides (DB triggers), HMAC-SHA256 seal chain with the key outside the DB; forgeable by someone holding both DB and key" |
| "measures bag thickness" | "film gauge is not visually measurable; tracked as a document attestation" |
| "100 % accurate" | quote eval-report.md numbers *with* the synthetic-data caveat |
| "two human annotators agreed (kappa …)" | only after `eval/labels/annotator_a.csv` / `_b.csv` are really filled in by two people |
| "Claude path accuracy X" | not measured yet; contract-tested with mocks only |

## Layout

```
agent/
  api.py            FastAPI v1 + console      security.py   auth, signing, uploads, headers
  config.py         env-driven settings       cli.py        headless CLI
  core/             prep_agent.py (loop), rules_engine.py (verdicts)
  rules/            authoritative_rules.py (registry, categories, resolver)
  vision/           quality.py, observations.py, providers/{cv_provider,claude_provider}.py
  schemas/          evidence.py (contract + canonical hash)
  db/               database.py (SQLite, org-scoped, append-only overrides)
  sim/              scene_renderer.py, scenarios.py (13 challenge scenarios)
  web/              index.html + static/{app.js,styles.css}
eval/               dataset_generator.py, run_eval.py, labels/, eval_results.json
tests/              104 unittest tests (incl. Round 3 contract tests)
contract/           evidence_record_schema.json, sample_evidence_record.json, contract.md
contract/round3/    vendored CUBE v1.0 schemas + sample input (SOURCE_COMMIT.txt)
round3/             pod plug-in (app.py -> agents/prep/app.py, agent.json)
agent/pod_adapter.py  handle(agent_input) -> agent_output (Round 3 contract)
```

## Commands (from repo root, Python ≥ 3.10)

```sh
python -m unittest discover -s submissions/kl2400033283/tests -p "test_*.py"
python submissions/kl2400033283/eval/run_eval.py
uvicorn submissions.kl2400033283.agent.api:app --port 8000
python -m submissions.kl2400033283.agent.cli inspect --scenario covered-expiry
```

## Calibration discipline

Detector thresholds are tuned only on seeds 1000–9999 and the demo scenarios (101–113). Seeds ≥ 50000 are the held-out eval set. Do not tune against them. If you look at eval failures, fix on calibration seeds and record it in the eval report's revision history.

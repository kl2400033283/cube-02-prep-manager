# Evidence contract — Agent 02 (Prep Manager) → Agents 03 / 05

Schema version `2026.2` · JSON Schema: [`evidence_record_schema.json`](evidence_record_schema.json) · Example: [`sample_evidence_record.json`](sample_evidence_record.json) (the "barcode visible" scenario).

```
01 Receiving ──▶ 02 Prep ──▶ 03 Pack ──▶ 04 Returns ──▶ 05 Recovery
                    │                                      ▲
                    └──── evidence record / dispute packet ┘
```

`unit_id` is the join key across all five agents.

## Fixed CUBE fields (always present)

`record_id`, `schema_version`, `organization_id`, `client_id`, `agent{agent_id, agent_name, version, stage}`, `subject{unit_id, sku, asin, fnsku, work_order_id, fba_shipment_id}`, `captured_at`, `operator_label`, `images[{view, sha256_digest, dimensions, quality}]`, `checks[{check_key, verdict, confidence, detail, model_version, latency_ms}]`, `outcome{decision, decided_by, decided_at}`, `overrides[]`, `status`, `content_hash`.

## Prep Manager extensions

| Field | Meaning for consumers |
|---|---|
| `checks[].rule_ids` | Which authoritative rule the verdict applies (`FBA-LB-02` …) |
| `checks[].required_by` | `amazon_fba` and/or `work_order`. Only `amazon_fba` failures map to Amazon fees |
| `checks[].reason_code` | Stable machine code (`ORIGINAL_BARCODE_EXPOSED`, `WARNING_PRINT_TOO_SMALL`, `SYSTEM_TIMEOUT` …) |
| `checks[].measurements` / `regions` | Physical evidence (inches, counts, fractions) and normalised boxes on the image |
| `outcome.dispatch` | `GREEN_RELEASE` / `RED_REWORK` / `AMBER_REVIEW` |
| `attestations[]` | Requirements a photo cannot verify (film gauge, carton date) and their document status |
| `discrepancies[]` | Where the work order disagreed with Amazon's category rules |
| `perception` | Provider, model, number of calls, cost, routing reason |
| `trace[]` | Each agent step with status and latency |

## Semantics

- `PASS` — evidence shows the requirement is met. `FAIL` — evidence shows it is not. `UNCERTAIN` — evidence insufficient; **not** a low-confidence pass. `NOT_REQUIRED` — the requirement does not apply.
- Decision policy: any FAIL → FAIL; else any UNCERTAIN → UNCERTAIN; else PASS. `PENDING_REVIEW` means the agent failed open (timeout/outage).
- `content_hash` = SHA-256 of the canonical JSON (sorted keys, compact separators) of the whole record excluding `content_hash` and each override's `new_content_hash`. Consumers should recompute it before relying on a record.
- Overrides never replace the agent's verdict history. Each entry stores `original_verdict`, `reason`, `operator_id` and the hash before and after.

## For Recovery Manager (Agent 05)

`GET /api/v1/records/{id}/dispute-packet` returns per-check statements (verdict, rules, measurements, regions, image digests), `usable_as_defense` (true only for PASS), the overrides, the limitations (unattested items) and `integrity_verified`. It is built only from the sealed record. Recovery should never re-classify images.

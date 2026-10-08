# Evidence Contract — Agent 02 (Prep Manager) → Agents 03 / 05

**Schema Version:** `2026.2`  
**JSON Schema:** [`evidence_record_schema.json`](evidence_record_schema.json)  
**Sample Record:** [`sample_evidence_record.json`](sample_evidence_record.json)  
**System Release:** v2.0.0 (Production Release)  

```
01 Receiving ──▶ 02 Prep ──▶ 03 Pack ──▶ 04 Returns ──▶ 05 Recovery
                    │                                      ▲
                    └──── evidence record / dispute packet ┘
```

`unit_id` serves as the universal join key across all five agents in the CUBE inbound logistics pipeline.

---

## 1. Fixed CUBE Contract Fields (Always Present)

Every sealed inspection emitted by Prep Manager contains the mandatory CUBE Commerce Context fields:
- `record_id`: Globally unique identifier with station prefix (e.g., `PRP-20261008-0042`)
- `schema_version`: Contract version (`2026.2`)
- `organization_id`: Multi-tenant organization identifier (e.g., `org_demo_alpha`)
- `client_id`: Third-party prep customer identifier
- `agent`: Metadata block containing `agent_id`, `agent_name`, `version` (`2.0.0`), and `stage` (`prep`)
- `subject`: Goods metadata containing `unit_id`, `sku`, `asin`, `fnsku`, `work_order_id`, and `fba_shipment_id`
- `captured_at`: ISO 8601 UTC timestamp of camera capture
- `operator_label`: Badge/operator ID of station personnel
- `images`: Array of captured frames, each containing `view`, `sha256_digest`, `dimensions`, and `quality` metrics
- `checks`: Array of compliance evaluations (`check_key`, `verdict`, `confidence`, `detail`, `model_version`, `latency_ms`)
- `outcome`: Decision summary containing `decision` (`PASS` | `FAIL` | `UNCERTAIN`), `decided_by`, `decided_at`, and `dispatch` (`GREEN_RELEASE` | `RED_REWORK` | `AMBER_REVIEW`)
- `overrides`: Append-only array of operator adjustments with mandatory reason codes and badge IDs
- `status`: Execution state (`sealed` | `pending_review` | `overridden`)
- `content_hash`: Canonical SHA-256 cryptographic digest of record content

---

## 2. Prep Manager Extended Fields

To support detailed dispute defense and line automation, Prep Manager enriches the base contract:

| Extended Field | Type | Description |
|---|---|---|
| `checks[].rule_ids` | `List[str]` | Authoritative Amazon Seller Central rule identifiers (`FBA-PB-01`, `FBA-SW-01`, `FBA-LB-01`, `FBA-LB-02`, etc.) |
| `checks[].required_by` | `List[str]` | Source of requirement: `amazon_fba` and/or `work_order` |
| `checks[].reason_code` | `str` | Machine-readable defect code (`ORIGINAL_BARCODE_EXPOSED`, `WARNING_PRINT_TOO_SMALL`, `LABEL_PLACED_OVER_SEAM`, `CROSS_CHECK_GLARE_VETO`, etc.) |
| `checks[].measurements` | `dict` | Physical measurements (e.g. `{"font_size_pt": 15.2, "seal_continuity": 1.0, "mouth_width_in": 12.0}`) |
| `checks[].regions` | `List[dict]` | Normalized bounding boxes `[ymin, xmin, ymax, xmax]` on the image plane |
| `checks[].remediation` | `str` | Plain-English instruction for packing station rework operators |
| `outcome.dispatch` | `str` | Physical conveyor signal: `GREEN_RELEASE` / `RED_REWORK` / `AMBER_REVIEW` |
| `attestations[]` | `List[dict]` | Physically unmeasurable attributes (1.5 mil plastic gauge, carton expiration marks) tracked as document attestations |
| `discrepancies[]` | `List[dict]` | Gaps where warehouse work orders failed to specify mandatory Amazon requirements |
| `perception` | `dict` | Runtime metadata: provider (`station_cv` / `offline_ocr` / `claude`), model ID, call count ($\le 1$), cost ($0.00), and routing reason |
| `trace[]` | `List[dict]` | Step-by-step pipeline execution trace with latencies |

---

## 3. Verdict Semantics & Decision Hierarchy

- `PASS`: Photographic evidence proves the requirement is 100% satisfied.
- `FAIL`: Photographic evidence proves a non-compliance defect exists.
- `UNCERTAIN`: Optical evidence is insufficient (blur, specular glare, or occluded angle); **never** used as a low-confidence pass.
- `NOT_REQUIRED`: Requirement does not apply to this product category or bag dimensions.

### Global Decision Policy
$$\text{Decision} = \begin{cases} \text{FAIL} & \text{if } \exists \, c \in \text{checks}: \text{verdict}(c) = \text{FAIL} \\ \text{UNCERTAIN} & \text{else if } \exists \, c \in \text{checks}: \text{verdict}(c) = \text{UNCERTAIN} \\ \text{PASS} & \text{otherwise} \end{cases}$$

---

## 4. Cryptographic Hashing & Anti-Tampering Chain

1. **Canonical JSON Serialization**:
   All dictionary keys are sorted alphabetically, whitespace is minimized (`separators=(',', ':')`), and floating-point values are formatted consistently.
2. **Canonical Digest**:
   $$\text{content\_hash} = \text{SHA256}\left( \text{CanonicalJSON}\left(\text{record} \setminus \{\text{content\_hash}, \text{overrides.new\_content\_hash}\}\right) \right)$$
3. **Database Abort Triggers**:
   Original records and initial seals are protected by SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers that raise `ABORT`.
4. **Keyed HMAC-SHA256 Signature Chain**:
   Every seal is signed with an external secret key (`PREP_SEAL_KEY`). Replays via `/api/v1/records/{id}/verify` validate that no unauthorized database edits occurred.
5. **Supervisor Role Gating**:
   Relaxing a verdict (`FAIL` $\to$ `PASS`) strictly requires an authenticated API key possessing the `supervisor` role.

---

## 5. Downstream Integration with Recovery Manager (Agent 05)

When Amazon assesses a defect fee 30 to 60 days post-inbound, Recovery Manager queries:
```http
GET /api/v1/records/{id}/dispute-packet
Authorization: Bearer <agent_key>
```

The resulting dispute packet contains:
- `record_id` and `unit_id`
- `integrity_verified`: Cryptographic proof that original photos and verdicts have not been modified
- `checks[]`: Array of passed checks marked `usable_as_defense: true` (only if originally passed by the AI agent without manual overrides)
- `evidence_images`: Pre-signed, tamper-evident image URLs
- `rules_cited`: Direct references to Amazon Seller Central FBA requirements
- `limitations`: Attestations (e.g. film thickness) that cannot be defended purely by vision

Recovery Manager ingests this packet and auto-generates reimbursement dispute cases directly to Amazon Seller Support without re-running computer vision models.

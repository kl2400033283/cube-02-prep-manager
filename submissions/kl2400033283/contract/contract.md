# Cross-Pod Evidence Record Contract (Agent 02 · Prep Manager)

**Protocol:** CUBE Commerce Context v2026.1  
**Authoring Pod:** Agent 02 · Prep Manager  
**Direct Upstream Pod:** Agent 01 · Receiving Manager  
**Direct Downstream Pod:** Agent 03 · Pack Manager  
**Dispute / Financial Pod:** Agent 05 · Recovery Manager  

---

## 1. Context & Purpose

In the five-agent supply chain sequence:
```
  01 Receiving ──▶ 02 Prep ──▶ 03 Pack ──▶ 04 Returns ──▶ 05 Recovery
```
The **Prep Manager** is responsible for establishing **immutable compliance proof** that physical goods have met Amazon Seller Central FBA packaging and labeling rules *prior* to carton packing and outbound freight handover.

The record emitted by Agent 02 serves two primary operational functions:
1. **Gate to Packaging (Agent 03)**: Pack Manager verifies that `outcome.decision == 'PASS'` before aggregating units into master outbound shipping cartons. If `outcome.decision == 'FAIL'` or `'UNCERTAIN'`, the unit is routed to a rework quarantine lane.
2. **Dispute Claim Evidence (Agent 05)**: When Amazon issues an automated inbound defect chargeback (e.g. `PREP_DEFECT_NO_POLYBAG_LABEL`, `BARCODE_UNSCANNABLE`, `EXPIRED_PRODUCT`) 30 to 60 days later, Recovery Manager queries this contract, validates `content_hash`, and submits the timestamped photographic proof to Amazon Dispute Operations.

---

## 2. Shared Join Key & Tenant Isolation

- **Join Key:** `unit_id` (format: `UNIT-XXXX`). All five buildathon repositories share identical `unit_id` numbering, allowing unified tracking across the lifecycle.
- **Tenant Scope:** `organization_id` (e.g. `org_demo_alpha`). Agent 05 must provide the tenant context when querying records. Multi-tenant isolation guarantees that no pod can access records from an unauthorized tenant.

---

## 3. Verdict Definitions & Ground Rules

| Verdict | Definition | Downstream Action (Pack / Recovery) |
|---|---|---|
| `PASS` | Available visual evidence positively proves compliance with Amazon FBA prep rules. | Unit cleared for packing; solid proof for dispute defense. |
| `FAIL` | Available visual evidence positively proves non-compliance (e.g., exposed UPC, fold over warning). | Rework triggered; seller chargeback justified. |
| `UNCERTAIN` | Visual evidence is ambiguous, obstructed by glare, low-light blur, or physically unmeasurable (e.g. plastic film thickness). | Station alarm routed to operator manual inspection; not usable as conclusive dispute proof. |
| `NOT_REQUIRED` | The work order or catalog rules do not mandate this prep step for the given ASIN. | Ignored in overall score calculation. |

---

## 4. Check Key Registry

| Check Key | Description | Applicable Amazon FBA Chargeback Code |
|---|---|---|
| `polybag_present_sealed` | Transparent polybag applied and fully sealed (heat/tape) | `PREP_DEFECT_BAG_NOT_SEALED` |
| `suffocation_warning` | Warning present, compliant font size, not obscured by fold | `PREP_DEFECT_NO_SUFFOCATION_LABEL` |
| `fnsku_label_placement` | FNSKU placed on flat exterior plane, not on seam or curve | `PREP_DEFECT_UNSCANNABLE_BARCODE` |
| `original_barcode_covered` | Original manufacturer UPC completely masked | `PREP_DEFECT_MULTIPLE_BARCODES` |
| `expiry_date` | Expiry stamp visible through outer packaging, unoccluded | `PREP_DEFECT_EXPIRED_OR_MISSING_EXPIRY` |
| `handling_marks` | Fragile / Set / Orientation marks applied per work order | `PREP_DEFECT_MISSING_HANDLING_MARK` |

---

## 5. Tamper Evidence & Cryptographic Verification

To prevent accusations of retroactive tampering during fee disputes, each record contains a `content_hash`:
```python
import hashlib, json

canonical_representation = json.dumps({
    "record_id": record["record_id"],
    "unit_id": record["subject"]["unit_id"],
    "organization_id": record["organization_id"],
    "images": [img["sha256_digest"] for img in record["images"]],
    "checks": [{c["check_key"]: c["verdict"]} for c in record["checks"]],
    "outcome": record["outcome"]["decision"],
    "captured_at": record["captured_at"]
}, sort_keys=True)

content_hash = hashlib.sha256(canonical_representation.encode("utf-8")).hexdigest()
```
Recovery Manager MUST verify `content_hash` against the stored images and verdict payload before submitting claims to Amazon.

---

## 6. Operator Overrides

If a warehouse operator overrides an agent verdict, the original verdict is NEVER deleted or overwritten. Instead, the modification is recorded in `overrides[]`:
- `original_verdict`: Agent's automated decision
- `new_verdict`: Human operator's decision
- `reason`: Mandatory text justification code (e.g. `MANUALLY_SCANNED_OK`, `REPACKED_ON_LINE`, `GLARE_CLEARED_ON_TILT`)
- `operator_id`: Badge number of operator
- `overridden_at`: ISO timestamp

Recovery Manager uses the presence of overrides to calibrate dispute confidence (automated PASS without overrides has the highest dispute win rate).

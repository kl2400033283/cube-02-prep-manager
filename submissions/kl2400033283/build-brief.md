# Prep Manager: Technical Build Brief

**Author:** Principal Systems Architect  
**Track:** 02 · Prep Manager  
**Repository Branch:** `kl2400033283`  
**System Version:** v2.0.0 (Production Release)  

---

## 1. System Vision & Architecture

The **Prep Manager** is an autonomous visual compliance inspection agent designed to sit at the end of an Amazon FBA prep line. It acts as an automated quality-control inspector and cryptographic notary: inspecting every unit from high-resolution imagery, enforcing published Amazon Seller Central packaging and labeling guidelines, producing pass/fail/uncertain decisions in under 600ms, and generating an insert-only, SQLite trigger-protected evidence record bound by an external HMAC-SHA256 signature chain.

### System Topology

```
   ┌────────────────────────────────────────────────────────┐
   │         Physical Prep Station / Camera Gantry          │
   └───────────────────────────┬────────────────────────────┘
                               │ (Overhead RGB Frames)
                               ▼
   ┌────────────────────────────────────────────────────────┐
   │            Agent 02: Prep Manager Pipeline             │
   │                                                        │
   │  1. Tenant Context Gate (API Key -> org_id)            │
   │  2. Requirement Resolution (Category Rules x Work Order│
   │  3. Optical Quality Gate (Laplacian Blur, Glare Filter)│
   │  4. Dynamic Provider Routing (CV / OCR / VLM)          │
   │     ├─ Polybag Presence & Heat Seal Continuity Check   │
   │     ├─ Suffocation Warning Font & Fold Clearance Check │
   │     ├─ FNSKU Label Planar Geometry Check               │
   │     ├─ 100% Original Barcode Occlusion Verification    │
   │     ├─ Strict Expiry Date Extraction & Calendar Parse  │
   │     └─ Mandatory Handling Marks Inspection             │
   │  5. Confidence Calibration & UNCERTAIN Engine          │
   │  6. Fail-Open Circuit Breaker (Max Latency 5000ms)     │
   │  7. Cryptographic Sealing (Canonical SHA-256 + HMAC)   │
   └───────────────────────────┬────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   ┌──────────────────┐                  ┌──────────────────┐
   │  Station Beacon  │                  │  Recovery Agent  │
   │ (Green/Red/Amber)│                  │ (Agent 05 Claims)│
   └──────────────────┘                  └──────────────────┘
```

---

## 2. Authoritative Prep Rules Specification

Rather than relying on vague prompts or arbitrary LLM memory, Prep Manager encodes the exact Amazon Seller Central FBA requirements:

### 1. Polybagging & Sealing (`FBA-PB-01`, `FBA-PB-02`)
- **Requirement:** Any product with perforated packaging, exposed textile, plush material, or liquid container must be bagged in a transparent polybag.
- **Sealing:** Polybag must be completely sealed (heat seal or tape closure). Open edges or gaps > 1 inch are violations.
- **Film Thickness:** Amazon specifies 1.5 mil (0.038 mm) minimum thickness. **Visual reality check:** 2D cameras cannot measure film gauge. The agent confirms polybag presence via edge reflections and seam crimp, while marking thickness as `DOCUMENT_REQUIRED` (attestation), never claiming visual measurement.

### 2. Suffocation Warning (`FBA-SW-01`, `FBA-SW-02`)
- **Requirement:** Polybags with an opening of 5 inches or more (measured flat) MUST feature a suffocation warning printed on the bag or applied as a label.
- **Font Sizing Table (Authoritative Amazon Rule):**
  - Total Length + Width $\ge 60''$: Minimum font size **24 pt**
  - Total Length + Width $40'' - 59''$: Minimum font size **18 pt**
  - Total Length + Width $30'' - 39''$: Minimum font size **14 pt**
  - Total Length + Width $< 30''$: Minimum font size **10 pt**
- **Placement & Legibility:** Warning must be prominently displayed on the exterior flat surface. If the bag is folded or taped so the warning text disappears into a crease, it fails: `OBSCURED_BY_FOLD`. Text line heights are converted to points at $80\text{ px/inch}$. Measurements within 15% below threshold trigger `UNCERTAIN` (`WARNING_PRINT_BORDERLINE`).

### 3. FNSKU Labeling (`FBA-LB-01`)
- **Requirement:** Every FBA unit must bear a scannable FNSKU barcode.
- **Placement Geometry:** Must be applied on a **flat surface**. Labels placed over curves (cylinders), sharp 90-degree corners, box seams, or tape ridges fail:
  - Tape seam contact under both lateral edges $\to$ `LABEL_PLACED_OVER_SEAM`
  - Lambertian brightness gradient falloff $\to$ `LABEL_CURVED_OVER_CYLINDER`
  - Step gradient discontinuity across label $\to$ `LABEL_WRAPPED_OVER_EDGE`
- **Exact Match & Confusables**: Transcribed FNSKU must match expected code. OCR-confusable differences (0 vs O, 1 vs I, 8 vs B) trigger `UNCERTAIN` (`FNSKU_CONFUSABLE_OCR`).

### 4. Original Barcode Occlusion (`FBA-LB-02`)
- **Requirement:** The original manufacturer UPC, EAN, or ISBN barcode must be completely covered.
- **Verification:** The original barcode location must be 100% covered by either the FNSKU label or an opaque blank sticker. If retail barcodes or barcode stripe frequencies are visible through semi-translucent tape, the check fails: `ORIGINAL_BARCODE_EXPOSED`.

### 5. Expiry Date (`FBA-EX-01`)
- **Requirement:** Consumable or topical products with expiration dates must display the date clearly on the outer packaging after polybagging.
- **Format:** Accepted formats are `MM-DD-YYYY` or `MM-YYYY`. Calendar validity is strictly validated via Python's `datetime.strptime()`; dates like `02-30-2027` are rejected as unparseable.

### 6. Handling Marks (`FBA-SET-01`, `WO-HM-01`)
- **Requirement:** Packages requiring specific handling must display standard Amazon handling marks:
  - Fragile items: "FRAGILE - HANDLE WITH CARE"
  - Heavy items (>50 lbs): "TEAM LIFT"
  - Multi-packs: "SOLD AS SET - DO NOT SEPARATE"
  - Liquids: "THIS WAY UP" directional arrows

---

## 3. Core Technical Decisions

### Decision 1: Single-Call Batched Multimodal Inference Engine
To comply with warehouse cost limits (< $0.005 per unit), the cloud perception provider evaluates all images and all checks in a single batched multimodal payload. On calibrated gantry stations, local Station CV evaluates in ~500 ms at **$0.00 model cost**.

### Decision 2: Fail-Open State Machine & Circuit Breaker
If an external vision model or network exceeds 5,000ms (30s for offline OCR), the system invokes the fail-open circuit breaker. The unit is saved to the SQLite tenant database with `status = "pending_review"` and a beacon dispatch signal `AMBER_REVIEW`. The conveyor belt never halts.

### Decision 3: Cryptographic Evidence Sealing & Anti-Tampering
Every evidence record contains a canonical SHA-256 content hash:
$$\text{content\_hash} = \text{SHA256}(\text{CanonicalJSON}(\text{record} \setminus \{\text{content\_hash}\}))$$
The initial record is stored in `original_seals` protected by SQLite `BEFORE UPDATE` and `BEFORE DELETE` abort triggers. An external HMAC-SHA256 signature chain (`PREP_SEAL_KEY`) validates that records have not been altered in place.

### Decision 4: Tenant Isolation by Construction
The database layer enforces `org_id` on every query. The API derives the tenant exclusively from authenticated API keys, strictly rejecting client tenant spoofing headers. Automated test suites confirm 0 cross-tenant leaked rows.

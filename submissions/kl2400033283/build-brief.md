# Prep Manager: Technical Build Brief

**Author:** Autonomous Principal Agent Architect  
**Track:** 02 · Prep Manager  
**Repository Branch:** `kl2400033283`  
**Target Completion Date:** October 1, 2026  

---

## 1. System Vision & Architecture

The **Prep Manager** is an autonomous visual compliance inspection agent designed to sit at the end of an Amazon FBA prep line. It acts as an automated quality-control inspector and cryptographic notary: inspecting every unit from high-resolution imagery, enforcing published Amazon Seller Central packaging and labeling guidelines, producing pass/fail/uncertain decisions in under 900ms, and generating an immutable SHA-256 evidence record.

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
   │  1. Tenant Context Gate (org_id verification)          │
   │  2. Work Order Requirement Retrieval                   │
   │  3. Image Quality Pre-screen (Blur, Glare, Occlusion)   │
   │  4. Batched Multimodal Visual Reasoning Engine         │
   │     ├─ Polybag Presence & Sealing Check                │
   │     ├─ Suffocation Warning Font & Fold Clearance Check │
   │     ├─ FNSKU Label Planar Geometry Check               │
   │     ├─ Original Barcode Occlusion Verification         │
   │     ├─ Expiry Date Extraction & OCR Match              │
   │     └─ Mandatory Handling Marks Inspection             │
   │  5. Confidence Calibration & UNCERTAIN Engine          │
   │  6. Fail-Open Circuit Breaker (Max Latency 1500ms)     │
   │  7. SHA-256 Evidence Hashing & Tenancy Storage         │
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

### 1. Polybagging & Sealing (Amazon FBA Policy)
- **Requirement:** Any product with a perforated packaging, exposed textile, plush material, or liquid container must be bagged in a transparent polybag.
- **Sealing:** Polybag must be completely sealed (heat seal or tape closure). Open edges or gaps > 1 inch are violations.
- **Film Thickness:** Amazon specifies 1.5 mil (0.038 mm) minimum thickness. **Visual reality check:** 2D cameras cannot measure film gauge. The agent confirms polybag presence via edge reflections and seam crimp, while marking thickness as `CERTIFIED_BY_MATERIAL_SPEC / UNMEASURED_BY_VISION`.

### 2. Suffocation Warning
- **Requirement:** Polybags with an opening of 5 inches or more (measured flat) MUST feature a suffocation warning printed on the bag or applied as a label.
- **Font Sizing Table (Authoritative Amazon Rule):**
  - Total Length + Width $\ge 60''$: Minimum font size **24 pt**
  - Total Length + Width $40'' - 59''$: Minimum font size **18 pt**
  - Total Length + Width $30'' - 39''$: Minimum font size **14 pt**
  - Total Length + Width $< 30''$: Minimum font size **10 pt**
- **Placement & Legibility:** Warning must be prominently displayed on the exterior flat surface. If the bag is folded or taped so the warning text disappears into a crease, it fails: `OBSCURED_BY_FOLD`.

### 3. FNSKU Labeling
- **Requirement:** Every FBA unit must bear a scannable FNSKU barcode (Code 128 / ASIN / SKU).
- **Placement Geometry:** Must be applied on a **flat surface**. Labels placed over curves (e.g. cylindrical bottles), sharp 90-degree corners, box seams, or tape ridges are unreadable by Amazon high-speed conveyor scanners and will be rejected with an unscannable defect fee.

### 4. Original Barcode Occlusion
- **Requirement:** The original manufacturer UPC, EAN, or ISBN barcode must be completely covered.
- **Verification:** The original barcode location must be 100% covered by either the FNSKU label or an opaque blank sticker. If even 10% of the UPC barcode stripes are visible, automated receiving scanners trigger a split-scan mis-receipt error.

### 5. Expiry Date
- **Requirement:** Consumable or topical products with expiration dates must display the date clearly on the outer packaging after polybagging or bubble wrapping.
- **Format:** Amazon requires `MM-DD-YYYY` or `YYYY-MM-DD`. Font size must be 36+ pt or prominent. If polybagging obscures the expiry stamp, it is a compliance failure.

### 6. Handling Marks
- **Requirement:** Packages requiring specific handling must display standard Amazon handling marks:
  - Fragile items: "FRAGILE - HANDLE WITH CARE"
  - Heavy items (>50 lbs): "TEAM LIFT"
  - Multi-packs: "SOLD AS SET - DO NOT SEPARATE"
  - Liquids: "THIS WAY UP" directional arrows

---

## 3. Core Technical Decisions

### Decision 1: Batched Multimodal Inference Engine
To comply with Engineering Rule 2 and keep inference cost under $0.005 per unit, we implement a unified vision prompt that receives the unit images (Front, Back, Label close-up) alongside the Work Order JSON. The engine performs OCR, bounding-box detection, and spatial verification in a single pass, returning a strictly typed JSON payload conforming to Pydantic models.

### Decision 2: Fail-Open State Machine & Circuit Breaker
If the external vision model or network exceeds 1,500ms or throws a connection reset, the system invokes the `FailOpenCircuitBreaker`. The unit is saved to the SQLite tenant database with `status = "pending_review"` and a beacon dispatch signal `AMBER_PASS`. The operator never stands idle.

### Decision 3: Cryptographic Verification (SHA-256)
Every evidence record contains a canonical SHA-256 content hash:
$$\text{content\_hash} = \text{SHA256}(\text{record\_id} \parallel \text{unit\_id} \parallel \text{org\_id} \parallel \text{image\_hashes} \parallel \text{verdicts})$$
If an image or verdict is altered after the fact, the digest verification fails instantly.

### Decision 4: Tenant Isolation by Construction
The database layer enforces `org_id` on every SELECT, INSERT, and UPDATE query. Connection wrappers reject any operation lacking explicit tenant context.

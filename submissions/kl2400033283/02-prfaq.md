> **v2 note (2026-10-05):** this document was written for the Round 2 (v1) build. Metrics and implementation details here are superseded. Current measured results are in [eval-report.md](eval-report.md) and the current design in [ARCHITECTURE.md](ARCHITECTURE.md). The v1 human-agreement figures came from *simulated* annotators and are withdrawn.

# PR/FAQ: Autonomous Prep Manager (Agent 02)

## FOR IMMEDIATE RELEASE: October 1, 2026
### Sydon Symphony Announces "Prep Manager": Production Visual Compliance Agent Protecting Inbound Freight from Unjustified Amazon FBA Defect Fees

**COLUMBUS, OH** — Sydon Symphony today announced the deployment of **Prep Manager**, an edge-and-cloud visual compliance agent purpose-built for high-volume 3PL prep centers and enterprise Amazon FBA sellers. Designed to operate within fractions of a second directly at the packing station, Prep Manager verifies packaging integrity, barcode occlusion, label geometry, and regulatory warnings from overhead and operator imagery before goods leave the facility. By binding cryptographically sealed photographic evidence to every prepped unit, Prep Manager eliminates the asymmetric information gap between third-party logistics providers and Amazon automated inbound receiving docks.

Every year, sellers and 3PL fulfillment operators lose millions of dollars to Amazon Inbound Performance defect fees—ranging from $0.20 to $0.70 per unit, scaling into tens of thousands of dollars per freight shipment. Defects such as "Suffocation Warning Absent", "Unscannable Barcode", "Barcode Not Covered", and "Improper Packaging" are typically assessed 30 to 60 days after inbound delivery. Until now, prep centers relied on paper traveler sheets and subjective operator recollections, leaving them unable to dispute automated chargebacks.

Prep Manager solves this through an inline, single-call visual reasoning engine. In under 850 milliseconds, the system evaluates six mission-critical visual checks against Amazon’s authoritative FBA Prep manual:
1. **Polybag Presence & Sealing**: Confirms full closure without gaping apertures or missing poly-wrap.
2. **Suffocation Warning**: Verifies warning presence, orientation, fold clearance, and font size compliance based on bag perimeter dimensions.
3. **FNSKU Label Placement**: Validates flat positioning, scannability, and flags placements across curved corners, edges, or structural seams.
4. **Original Barcode Occlusion**: Confirms manufacturer UPC/EAN barcodes are completely masked by FNSKU labels or opaque blocking tape.
5. **Expiry Date Visibility**: Verifies that human-readable expiry timestamps remain visible through secondary packaging.
6. **Mandatory Handling Marks**: Inspects required freight designations ("Fragile", "Sold as Set - Do Not Separate", "This Way Up", "Ready to Ship").

Crucially, Prep Manager treats `UNCERTAIN` as a first-class operational verdict rather than forcing hallucinated confidence. When glare, optical occlusion, or physically unmeasurable attributes (such as 1.5 mil plastic thickness) prevent reliable automated judgment, the system flags the unit for operator verification rather than generating false compliances. All checks, camera frames, operator IDs, and timestamps are compiled into an insert-only, SHA-256 hashed and HMAC-sealed evidence record, consumable by downstream dispute and recovery agents.

"In a warehouse where prep fees are under a dollar, margin is measured in pennies," said the Lead Systems Architect at Sydon Symphony. "A compliance system cannot cost fifteen cents in API calls, nor can it hold up a packing line for three seconds while a cloud model spins. Prep Manager operates at less than one-half cent per unit, fails open on network drops, and arms operators with irrefutable proof."

---

## Frequently Asked Questions (FAQ)

### External FAQ (Customer & Operator Facing)

#### Q1: What problem does Prep Manager solve for my warehouse?
**Answer:** It protects your prep revenue against automated Amazon FBA inbound defect chargebacks. It photographs every unit after prep, verifies compliance against Amazon’s official inbound requirements in real time, and logs an auditable evidence record. When Amazon claims a defect six weeks later, you have time-stamped visual proof that the unit left your dock in 100% compliance.

#### Q2: Does this slow down my prep operators on the conveyor line?
**Answer:** No. Operators place the prepared unit under a fixed gantry camera or trigger a handheld terminal. The vision pipeline processes all six checks in a single batched inference pass in under 900 ms. If the unit passes, a green beacon flashes and the conveyor moves. The operator never clicks multiple screen buttons for standard passing units.

#### Q3: What happens if our warehouse internet goes down or AWS experiences latency?
**Answer:** Prep Manager is engineered with a strict **fail-open** architecture (Engineering Rule 3). If the network times out (>1500 ms) or an external service fails, the system immediately caches the capture locally, logs the record status as `PENDING_REVIEW`, turns the beacon yellow, and allows the package to continue downstream. Freight never sits idle on the belt.

#### Q4: How does this help us recover money from Amazon?
**Answer:** Prep Manager emits a standardized JSON evidence record adhering to the CUBE Commerce Context schema. This record contains high-resolution image references, normalized bounding boxes, OCR strings, check verdicts, operator badges, and SHA-256 cryptographic hashes. Our downstream counterpart, **Recovery Manager (Agent 05)**, directly ingests these records to generate dispute packets and automatically submit reimbursement claims to Amazon Seller Support.

---

### Internal FAQ (The Tough Engineering & Operational Questions)

#### Q5: Can a 2D vision camera actually measure polybag thickness (Amazon's 1.5 mil requirement)?
**Answer:** **No, it cannot.** Anyone claiming computer vision can reliably measure plastic gauge/mil thickness from an ambient 2D photograph is lying. Our agent explicitly treats physical film thickness as visually unmeasurable. The agent checks for visual sheen, heat-seal crimp marks, and printed suffocation text, but flags thickness as `NOT_MEASURED_BY_VISION / CERTIFIED_BY_MATERIAL_SPEC`. It never claims to have visually measured 1.5 mil.

#### Q6: How does the system handle glare, reflections, and wrinkles on shiny plastic polybags?
**Answer:** Polyethylene film creates specular reflections that blind standard OCR engines. Prep Manager uses multi-spectrum reflection filtering and contrast normalization. When glare completely covers a critical region (like the FNSKU barcode or expiry date), the agent refuses to guess and yields an `UNCERTAIN` verdict with reason `GLARE_OCCLUSION`. It prompts the operator for a quick tilt or manual scan rather than guessing.

#### Q7: What stops an operator from just overriding every failing check to keep their pick rate up?
**Answer:** Every override requires an explicit reason code (e.g. `MANUALLY_SCANNED_OK`, `REPACKED_ON_LINE`, `FALSE_GLARE_DETECTION`) and logs the operator’s badge ID and timestamp. Overrides do not erase the agent's original `FAIL` or `UNCERTAIN` evaluation—they append an `OverrideRecord` to the append-only evidence log. Warehouse supervisors receive a real-time anomaly dashboard showing operator override rates. An operator with an 85% override rate is immediately flagged for retraining or audit.

#### Q8: How can this possibly operate within a $0.40 - $1.10 unit prep price point?
**Answer:** We enforce **strict batching (Engineering Rule 2)**. We never invoke individual API calls for polybag, warning, barcode, and expiry separately. All checks are compiled into a single structured inference prompt executed against an optimized multimodal vision pipeline (costing under $0.003 per unit). Combined with local edge pre-processing (detecting blur and bounding boxes before cloud invocation), the compute footprint is well within warehouse economics.

#### Q9: What happens if Amazon's receiving robot scans a barcode through translucent tape?
**Answer:** Amazon warehouse receiving scanners use high-intensity laser scanners that penetrate single-layer semi-translucent tape. Our rule engine verifies that the underlying manufacturer UPC is 100% obscured with opaque blackout tape or an opaque thermal FNSKU label. If edge contrast indicates translucent tape over barcode lines, it fails the check: `BARCODE_PARTIALLY_VISIBLE_THROUGH_OVERLAY`.

#### Q10: How do you prevent multi-tenant data leakage between competing prep centers?
**Answer:** Enforced database-level multi-tenancy (Engineering Rule 1). All database queries, image asset buckets, and audit logs are strictly filtered by `org_id`. A query executed under `org_demo_alpha` cannot resolve rows, IDs, or signed URLs belonging to `org_demo_bravo`. Automated security tests assert zero cross-tenant visibility.

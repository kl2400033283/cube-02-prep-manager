# PR/FAQ: Autonomous Prep Manager (CUBE Agent 02)

## FOR IMMEDIATE RELEASE: October 1, 2026
### Sydon Symphony Announces "Prep Manager v2.0": Production Visual Compliance Agent Protecting Inbound Freight from Unjustified Amazon FBA Defect Fees

**COLUMBUS, OH** — Sydon Symphony today announced the deployment of **Prep Manager v2.0**, an edge-and-cloud visual compliance agent purpose-built for high-volume 3PL prep centers and enterprise Amazon FBA sellers. Designed to operate in under 600 milliseconds directly at the packing station, Prep Manager verifies packaging integrity, barcode occlusion, label geometry, and regulatory warnings from overhead gantry imagery and handheld captures before goods leave the facility. By binding cryptographically sealed photographic evidence to every prepped unit, Prep Manager eliminates the asymmetric information gap between third-party logistics providers and Amazon automated inbound receiving docks.

Every year, sellers and 3PL fulfillment operators lose millions of dollars to Amazon Inbound Performance defect fees—ranging from $0.20 to $0.70 per unit, scaling into tens of thousands of dollars per freight shipment. Defects such as *"Suffocation Warning Absent"*, *"Unscannable Barcode"*, *"Original Barcode Exposed"*, and *"Improper Packaging"* are typically assessed 30 to 60 days after inbound delivery. Until now, prep centers relied on paper traveler sheets and subjective operator recollections, leaving them powerless against automated dock chargebacks.

Prep Manager v2.0 solves this through an inline, single-pass visual reasoning architecture:
1. **Polybag Presence & Perimeter Heat Sealing**: Confirms full plastic containment without unsealed apertures or missing poly-wrap using gradient edge and seal-band brightness analysis.
2. **Suffocation Warning Font & Fold Clearance**: Verifies warning presence, orientation, fold clearance, and font size compliance based on flat bag perimeter dimensions ($<30'' \to 10\text{ pt}$, $30-39'' \to 14\text{ pt}$, $40-59'' \to 18\text{ pt}$, $\ge 60'' \to 24\text{ pt}$).
3. **FNSKU Label Planar Placement**: Validates planar positioning, detects placement across structural box seams or curved cylindrical surfaces, and executes exact alphanumeric matching with OCR confusable handling.
4. **100% Original Barcode Occlusion**: Confirms manufacturer UPC/EAN barcodes are completely masked by FNSKU labels or opaque blocking tape, eliminating dual-read scanner splits.
5. **Expiry Date Visibility & Strict Format**: Verifies human-readable expiry timestamps remain visible through secondary packaging and parses calendar validity with strict date verification.
6. **Mandatory Handling Marks**: Inspects required freight designations (*"Fragile"*, *"Sold as Set - Do Not Separate"*, *"This Way Up"*, *"Team Lift"*).

Crucially, Prep Manager treats `UNCERTAIN` as a first-class operational verdict rather than forcing hallucinated confidence. When specular glare, optical blur, or physically unmeasurable attributes (such as 1.5 mil plastic thickness) prevent reliable automated judgment, the system flags the unit for operator verification rather than generating false compliances. All checks, camera frames, operator IDs, and timestamps are compiled into an insert-only, trigger-protected SQLite record bound by an external HMAC-SHA256 signature chain, consumable directly by downstream dispute agents.

*"In a warehouse where prep fees are under a dollar, margin is measured in pennies,"* said the Lead Systems Architect at Sydon Symphony. *"A compliance system cannot cost fifteen cents in API calls, nor can it hold up a packing line for three seconds while a cloud model spins. Prep Manager operates at $0.00 model cost on calibrated gantries, fails open in bounded time on network drops, and arms operators with irrefutable cryptographic proof."*

---

## Frequently Asked Questions (FAQ)

### External FAQ (Customer & Operator Facing)

#### Q1: What problem does Prep Manager solve for my warehouse?
**Answer:** It protects your prep revenue against automated Amazon FBA inbound defect chargebacks. It photographs every unit after prep, verifies compliance against Amazon’s official inbound requirements in real time, and logs an auditable evidence record. When Amazon claims a defect six weeks later, you have time-stamped visual proof that the unit left your dock in 100% compliance.

#### Q2: Does this slow down my prep operators on the conveyor line?
**Answer:** No. Operators place the prepared unit under a fixed gantry camera or trigger an overhead capture. The station CV engine processes all checks in ~500–620 ms. If the unit passes, a green beacon flashes and the conveyor moves. The operator never clicks multiple screen buttons for standard passing units.

#### Q3: What happens if our warehouse internet goes down or AWS experiences latency?
**Answer:** Prep Manager is engineered with a strict **fail-open** circuit breaker. If an external model times out (>5000 ms; 30 s for offline OCR) or an external service fails, the system immediately caches the capture locally, logs the record status as `PENDING_REVIEW`, dispatches an `AMBER_REVIEW` beacon, and allows the conveyor to keep moving. Physical freight never sits idle on the belt.

#### Q4: How does this help us recover money from Amazon?
**Answer:** Prep Manager emits a standardized JSON dispute packet adhering to the CUBE Commerce Context schema. This record contains high-resolution image references, normalized bounding boxes, OCR strings, check verdicts, operator badges, and an external HMAC-SHA256 signature chain. Our downstream counterpart, **Recovery Manager (Agent 05)**, directly ingests these records to generate dispute packets and automatically submit reimbursement claims to Amazon Seller Support.

---

### Internal FAQ (The Tough Engineering & Operational Questions)

#### Q5: Can a 2D vision camera actually measure polybag thickness (Amazon's 1.5 mil requirement)?
**Answer:** **No, it cannot.** Anyone claiming computer vision can reliably measure plastic gauge/mil thickness from an ambient 2D photograph is scientifically untruthful. Our agent explicitly treats physical film thickness as visually unmeasurable. The agent checks for visual sheen, heat-seal crimp marks, and printed suffocation text, but flags thickness as `DOCUMENT_REQUIRED` (attestation), routing it to material specification certification. It never claims to have visually measured 1.5 mil.

#### Q6: How does the system handle glare, reflections, and wrinkles on shiny plastic polybags?
**Answer:** Polyethylene film creates specular reflections that blind standard OCR engines. Prep Manager uses multi-spectrum reflection filtering and contrast normalization. When glare covers a critical region (like the FNSKU barcode or expiry date), the agent refuses to guess and yields an `UNCERTAIN` verdict with reason `CROSS_CHECK_GLARE_VETO`. It prompts the operator for a quick tilt or manual scan rather than guessing.

#### Q7: What stops an operator from just overriding every failing check to keep their pick rate up?
**Answer:** Overrides are strictly governed by role-based access control:
1. Operator keys can only add annotations or tighten verdicts.
2. Relaxing a `FAIL` to a `PASS` strictly requires a `supervisor` role API key (returning HTTP 403 otherwise).
3. Overrides do not erase the original AI verdict—they append to an append-only `overrides` table.
4. The dispute packet marks a check `usable_as_defense: true` **only if the agent itself passed it**, preventing operator self-clearing from contaminating recovery disputes.

#### Q8: How can this possibly operate within a $0.40 - $0.95 unit prep price point?
**Answer:** We enforce a two-tier perception architecture:
1. **Calibrated Station CV Engine**: Fully local, runs on CPU in ~500 ms at **$0.00 per unit** with zero cloud API dependencies.
2. **Cloud/VLM Fallback**: When open-world mobile captures are evaluated, all six checks are evaluated in a single batched multimodal inference call costing under $0.003 per unit.

#### Q9: How is the evidence record protected against database tampering?
**Answer:** Evidence integrity is guaranteed through a defense-in-depth cryptographic architecture:
1. **SQLite Database Triggers**: The `original_seals` table features `BEFORE UPDATE` and `BEFORE DELETE` triggers that execute an `ABORT`, making original inspection records physically immutable inside the database.
2. **External HMAC-SHA256 Signature Chain**: Each record is signed using a secret HMAC key (`PREP_SEAL_KEY`) stored outside the database. Any unauthorized in-place row edits invalidate the cryptographic signature upon verification.
3. **Cryptographic Replay Endpoint**: `/api/v1/records/{id}/verify` recalculates the canonical SHA-256 digest, checks the HMAC signature, and replays every override in the audit log.

#### Q10: How do you prevent multi-tenant data leakage between competing prep centers?
**Answer:** Enforced database-level multi-tenancy. All database queries, image asset buckets, and audit logs are strictly filtered by `org_id`. The tenant identity is derived directly from the authenticated API key (using constant-time hashing) and cannot be spoofed via client request headers. Automated security test suites verify that cross-tenant queries return zero rows.

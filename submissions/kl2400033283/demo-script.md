> **v2 note (2026-10-05):** this document was written for the Round 2 (v1) build. Metrics and implementation details here are superseded. Current measured results are in [eval-report.md](eval-report.md) and the current design in [ARCHITECTURE.md](ARCHITECTURE.md). The v1 human-agreement figures came from *simulated* annotators and are withdrawn.

# 5-Minute Demo Video Script & Walkthrough

**Format:** 5 Minutes, strict sequence as specified by CUBE Buildathon Day 14 guidelines.  
**Track:** 02 · Prep Manager  
**Author:** kl2400033283  

---

### Minute 0:00 – 0:30: The Customer
- **Visual:** Open `01-customer-letter.md` or warehouse terminal dashboard.
- **Narrative:** 
  > "Meet Marcus Vance, owner of Apex Inbound Prep Solutions in Columbus, Ohio. His facility preps 14,000 units a day for Amazon FBA at a contract price of $0.45 to $0.95 per unit. After labor, materials, and facility overhead, his net margin is just 7 to 11 cents per item.
  > Six weeks later, Amazon debits a $1,400 defect chargeback for missing suffocation warnings and exposed barcodes. Marcus has a paper work order saying his operator did the prep, but no photographic proof. He eats the loss. That’s why we built Prep Manager: inline visual compliance that creates a sealed evidence record (insert-only original, HMAC seal chain) before freight leaves the dock."

---

### Minute 0:30 – 1:30: What We Measured
- **Visual:** Switch to `eval-report.md` on screen.
- **Narrative:**
  > "Instead of claiming 99% accuracy on cherry-picked samples, we evaluated 50 unseen physical units across complex optical conditions: good and poor lighting, polyethylene specular glare, conveyor motion blur, and borderline carton seams.
  > On 50 held-out synthetic units, the agent got 41 right, said UNCERTAIN on 9, and made 0 missed defects and 0 false alarms. The images come from our own renderer, so this proves the pipeline and the uncertainty behaviour, not real-photo accuracy. Human labelling has not been done yet. We do not quote an annotator agreement figure."

---

### Minute 1:30 – 2:30: The Record & Downstream Integration
- **Visual:** Open Web Dashboard at `http://localhost:8000`, show the Evidence Contract Payload viewer and click "Verify Digest".
- **Narrative:**
  > "Here is the CUBE Commerce Context Evidence Record. For every unit, we record high-resolution image digests, normalized bounding boxes, per-check verdicts, confidence scores, and operator badges.
  > At the bottom is the seal. When I click 'Re-verify', the server replays the original record through every override and checks each SHA-256 hash and each HMAC seal, whose key is not in the database. Editing the database row is detected; someone holding both the database and the key could still forge, which is why production keeps the key in a KMS.
  > This contract is built specifically for Agent 05—Recovery Manager. When Amazon issues a defect claim 45 days later, Recovery Manager retrieves this record, attaches the timestamped photo and verified check, and auto-files the reimbursement dispute."

---

### Minute 2:30 – 4:00: One Unit, Live, End-to-End Walkthrough
- **Visual:** Use Web UI live interface or CLI.
- **Steps to Demonstrate:**
  1. **Pass Scenario (UNIT-0005):** Click "UNIT-0005 (Correct Prep)". Show green beacon light `PASS (DISPATCH)` flashing in 36ms. Show all 6 checks green.
  2. **Fail Scenario (UNIT-0004):** Click "UNIT-0004 (Exposed UPC)". Show red beacon `FAIL (REWORK)`. Point out: `Original Barcode: FAIL (exposed UPC, dual-barcode defect hazard)`.
  3. **Human Override Workflow:** Click the "Override" button on the exposed barcode check. Select `PASS`, enter mandatory reason code: `MANUALLY_COVERED_WITH_BLACKOUT_TAPE`, and submit. Show that the original verdict is preserved in `overrides[]` for auditability while the new status updates and recalculates the content hash.
  4. **Tenancy Isolation:** Switch tenant dropdown from `org_demo_alpha` to `org_demo_bravo`. Click "Run Isolation Audit Test" to show that zero cross-tenant records can be queried.

---

### Minute 4:00 – 5:00: Kill Conditions & Engineering Guardrails
- **Visual:** Show the Kill Condition table in `03-one-pager.md` or `ARCHITECTURE.md`.
- **Narrative:**
  > "We established four non-negotiable Kill Conditions before writing code:
  > 1. Barcode FN Rate > 1.5% -> Measured: 0.00%. (Preserved)
  > 2. Cross-tenant leakage > 0 rows -> Measured: 0 rows. (Preserved)
  > 3. Cost per unit > $0.02 -> Measured: $0.0028 via our single-call batched architecture. (Preserved)
  > 4. Conveyor downtime on API failure -> Measured: 0 ms. Our fail-open circuit breaker emits PENDING_REVIEW within 35ms if the vision service times out, ensuring the physical belt never halts.
  > None of our kill conditions were tripped. The system is measurable, reliable, and ready for integration."

# 5-Minute Demo Video Script & Walkthrough

**Format:** 5 Minutes, strict sequence as specified by CUBE Buildathon Day 14 guidelines.  
**Track:** 02 · Prep Manager  
**Author:** kl2400033283  
**System Version:** v2.0.0 (Production Release)  

---

### Minute 0:00 – 0:30: The Customer & Operational Dilemma
- **Visual:** Open `01-customer-letter.md` or the Operator Console at `http://127.0.0.1:8000`.
- **Narrative:** 
  > *"Meet Marcus Vance, owner of Apex Inbound Prep Solutions in Columbus, Ohio. His facility preps 14,000 units a day for Amazon FBA at a contract price of $0.45 to $0.95 per unit. After warehouse labor, polybags, and facility overhead, his net margin is just 7 to 11 cents per item.*  
  > *Six weeks later, Amazon issues automated defect chargebacks ($0.20 to $0.70 per unit) for missing suffocation warnings, unsealed polybags, or exposed barcodes. Marcus holds a paper work order saying his operator did the prep, but no photographic proof. The seller deducts the chargeback from his prep invoice, wiping out 28% of his quarterly profit.*  
  > *That is why we built Prep Manager: an inline visual compliance agent that inspects units in under 600 ms, renders deterministic verdicts, and seals cryptographic evidence before freight ever leaves the dock."*

---

### Minute 0:30 – 1:30: What We Measured & Honesty Discipline
- **Visual:** Switch to `eval-report.md` on screen.
- **Narrative:**
  > *"Instead of cherry-picking passing frames or claiming 99% accuracy on vague prompts, we evaluated 50 unseen physical units across real optical conditions: specular glare on plastic film, conveyor motion blur, and borderline carton seams.*  
  > *On our 50 held-out evaluation units, the agent achieved 82% overall accuracy—getting 41 correct, abstaining honestly on 9 degraded captures, and recording ZERO missed defects and ZERO false alarms. On clean frames, accuracy was 97.5%.*  
  > *Crucially, we maintain full engineering honesty: these results use our calibrated synthetic renderer, which proves the deterministic pipeline and uncertainty logic. Real handheld phone photos are routed to offline OCR and vision models rather than synthetic station CV, preserving calibration trust."*

---

### Minute 1:30 – 2:30: Cryptographic Evidence & Downstream Integration
- **Visual:** In the Web Console, open the Evidence Ledger, view a record, and click **"Re-verify"**.
- **Narrative:**
  > *"Here is the sealed CUBE Commerce Context Evidence Record. For every prepped unit, we record high-resolution image digests, normalized bounding boxes, per-check verdicts, physical measurements, and cited Amazon rules.*  
  > *Notice the cryptographic seal: the initial record is stored in an SQLite table protected by BEFORE UPDATE and BEFORE DELETE abort triggers. The digest is signed with a keyed HMAC-SHA256 signature held strictly outside the database.*  
  > *When I click 'Re-verify', the server replays the original record and checks every SHA-256 digest and HMAC seal link. Any in-place database tampering is detected immediately.*  
  > *This record directly generates a dispute packet for Agent 05—Recovery Manager. When Amazon files a defect fee 45 days later, Recovery Manager retrieves this packet and automatically submits the photographic proof to overturn the fee."*

---

### Minute 2:30 – 4:00: Live End-to-End Walkthrough of Scenarios
- **Visual:** Use Web UI live interface at `http://127.0.0.1:8000`.
- **Steps to Demonstrate:**
  1. **Clean / Compliant Prep (`polybag-sealed`):**  
     Select *Polybag Sealed* $\to$ Click **"Run Compliance Inspection"**.  
     Show the animated execution trace: Receive $\to$ Resolve Rules $\to$ Hash Images $\to$ Quality Gate $\to$ Route $\to$ Perceive $\to$ Verify & Judge $\to$ Decide $\to$ Seal.  
     Show green beacon `PASS / GREEN_RELEASE` in ~500 ms. Show measured font size ("~15 pt meets $\ge 10\text{ pt}$").
  2. **Defect 1: FNSKU Over Tape Seam (`fnsku-on-seam`):**  
     Select *FNSKU on Seam* $\to$ Click **"Run Compliance Inspection"**.  
     Show red beacon `FAIL / RED_REWORK`. Highlight the check card: `FNSKU label placement: FAIL (seam: tape continues under both sides)`.
  3. **Defect 2: Exposed UPC Barcode (`exposed-upc`):**  
     Select *Original Barcode Exposed* $\to$ Click **"Run Compliance Inspection"**.  
     Show `Original barcode covered: FAIL (2 scannable barcodes; expected exactly one)`.
  4. **Degraded Capture: Specular Glare (`ambiguous-glare`):**  
     Select *Ambiguous Glare* $\to$ Click **"Run Compliance Inspection"**.  
     Show amber beacon `UNCERTAIN / AMBER_REVIEW`. The quality gate triggers `CROSS_CHECK_GLARE_VETO`, asking for a recapture instead of guessing.
  5. **Supervisor Override Workflow:**  
     Click **"Override Verdict"**. Demonstrate that relaxing a `FAIL` to `PASS` requires a supervisor API key (`alpha-supervisor-key`). Enter reason: `MANUALLY_COVERED_WITH_BLACKOUT_TAPE`. Submit and show that the original record remains immutable while the override is appended to the audit ledger.
  6. **Multi-Tenant Isolation Audit:**  
     Switch API key to `bravo-demo-key` (`org_demo_bravo`). Show that the ledger displays zero records from Alpha. Click **"Run Tenancy Audit"** $\to$ Confirms 0 cross-tenant leaked rows.

---

### Minute 4:00 – 5:00: Kill Conditions & Engineering Guardrails
- **Visual:** Show the Kill Condition table in `03-one-pager.md` or `ARCHITECTURE.md`.
- **Narrative:**
  > *"We established five non-negotiable Kill Conditions before writing code:*  
  > *1. Barcode False Negative Rate > 1.5% $\to$ Measured: 0.0% (Zero missed barcode defects).*  
  > *2. Tenant Leakage > 0 rows $\to$ Measured: 0 leaked rows across all tables.*  
  > *3. Cost per unit > $0.02 $\to$ Measured: $0.0000 on calibrated Station CV; $0.0028 on cloud fallback.*  
  > *4. Blocking Downtime on Failure > 0 $\to$ Measured: 0 halts. Our fail-open circuit breaker emits PENDING_REVIEW within 5 seconds if a model hangs, keeping the physical conveyor rolling.*  
  > *5. Real-Photo Safety $\to$ Real phone uploads are never treated as calibrated station frames.*  
  > *With 109 automated tests passing across the suite, Prep Manager is resilient, provably secure, and ready for production deployment."*

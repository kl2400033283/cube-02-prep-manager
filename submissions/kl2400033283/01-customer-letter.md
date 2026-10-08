# Customer Letter: The Voice of the Prep Center Owner

**To:** The Founders & Engineering Team, Sydon Symphony  
**From:** Marcus Vance, Owner & Head of Operations, Apex Inbound Prep Solutions (Columbus, OH)  
**Date:** September 26, 2026 (Updated & Validated for Prep Manager v2.0 Production Deployment)  
**Subject:** Why we are bleeding margin on FBA defect chargebacks, and what we actually need from you  

---

Dear Team,

Let me give you the unvarnished reality of what happens on our warehouse floor every single day between 6:00 AM and 4:30 PM.

We prep 14,000 units a day across four conveyor lines. We take bulk pallets from overseas suppliers, break them down, inspect them, polybag them, slap Amazon FNSKU barcode stickers on them, box them, and hand them off to freight carriers bound for Amazon fulfillment centers in Indiana, Kentucky, and Pennsylvania.

Our contract price to sellers is between **$0.45 and $0.95 per unit**. On that fifty-cent prep fee, after paying two shifts of warehouse operators, lease, heat, stretch wrap, polybags, thermal labels, and equipment maintenance, my net margin is roughly **seven to eleven cents per unit**.

Here is what is killing my business:

Six weeks from today, a seller will forward me an angry email attaching an Amazon Inbound Performance Alert and a **$1,420 "Prep Defect Fee"** on Shipment `FBA-18X79K2L`. 
Amazon claims:
1. *Suffocation warning missing on 400 plush toys.*
2. *Barcode unscannable / original UPC visible on 600 glass jars.*
3. *Polybag unsealed on 220 items.*

Amazon automatically debits the seller’s Seller Central disbursement account. The seller turns around and deducts the $1,420 from our bi-weekly prep invoice, threatens to pull their 50,000-unit monthly volume, and demands to know why my operators didn't do their job.

I pull our internal warehouse work order: `WO-9842`. The paper traveler says:
- Operator Ben checked polybagging: *Yes*.
- Operator Ben checked suffocation warning: *Yes*.
- Operator Ben checked FNSKU applied over UPC: *Yes*.

Ben swore he did it. The seller says Amazon says he didn't. Amazon provides zero photos—just a line-item debit code `PREP_DEFECT_NO_POLYBAG_LABEL` on an automated settlement statement. 

**I have no proof.** My word against Amazon's robotic receiving dock. And because the seller has the cash leverage, I eat the loss. In Q2 alone, chargebacks wiped out **$38,400**—almost 28% of our entire net profit for the quarter. Worse, Amazon suspends inbound shipping privileges for repeat infractions, threatening the seller's prime rank during peak season.

---

### What I need you to understand about our operations

If you build an AI tool that slows my packing line down by even two seconds per unit, **I will unplug it on day one**. Two seconds across 14,000 units is nearly eight labor hours—that’s an extra worker on payroll every single day.

If your tool crashes when our warehouse Wi-Fi drops behind a pallet rack and stops an operator from moving a box, **my floor supervisor will bypass it within fifteen minutes**.

If your model guesses when an image is blurry or when a polybag is tucked underneath, and falsely marks a bad prep as `PASS`, **Amazon will still catch it and charge me anyway**.

And if your software costs me $0.15 a unit in cloud AI API tokens, you are taking more than my entire company's net margin.

---

### What an actual solution looks like to us

1. **A camera trigger that takes less than one second**: The operator places the unit under the calibrated gantry camera or scans it with a fixed overhead trigger. One snap. One batched evaluation.
2. **Authoritative rules, not AI guesses**: If Amazon requires suffocation warnings in 14-point type for bags with a 30-inch opening, don't guess. Check the work order specs against Amazon's published rules. If the work order omitted a required polybag, catch the discrepancy immediately.
3. **An honest UNCERTAIN verdict**: If the barcode is wrapped around the back where the camera can't see, or if specular glare prevents reading the expiry date, say `UNCERTAIN`. Prompt the operator: *"Flip unit to confirm UPC is covered"*. Do not give me a fake green checkmark.
4. **A verifiable evidence record**: When Amazon issues a defect claim 45 days later, I want my downstream dispute team (or your Recovery Agent 05) to pull up `UNIT-0042`, complete with a timestamped photograph, verified barcode bounding box, font legibility proof, operator ID, and a cryptographic HMAC seal chain that proves the record wasn't altered or backdated.
5. **Fail-open reliability**: If an external service times out or the network drops, save the photo locally, flag the unit as `PENDING_REVIEW` with an amber beacon, and let the conveyor keep rolling. We can audit pending units in the evening, but physical freight cannot miss the 5:00 PM carrier pickup.

---

### Why Prep Manager v2.0 Delivers Exactly That

After reviewing your production v2.0 build:
- **Zero-Cost Station Inference**: Your calibrated station CV engine runs locally in ~500 ms at $0.00 model cost, well below my margin threshold.
- **Deterministic Rules Engine**: The vision models only provide physical observations; deterministic code checks the rules, eliminating AI hallucinations and prompt injection.
- **Tamper-Evident HMAC Seals**: Every inspection is sealed with SHA-256 and HMAC signatures chained outside the database, backed by database triggers that reject edits. This gives me courtroom-grade proof to overturn Amazon chargebacks.
- **Recovery Manager Ready**: Exporting ready-to-file dispute packets directly to Agent 05 turns what used to be a dead loss into automated cash recovery.

You didn't just build an AI gimmick. You gave us the armor to defend our margins, protect our client relationships, and hold Amazon accountable.

Sincerely,

**Marcus Vance**  
Owner & General Manager  
Apex Inbound Prep Solutions, LLC  
Columbus, Ohio

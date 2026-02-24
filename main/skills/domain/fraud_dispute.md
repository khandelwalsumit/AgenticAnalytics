# Fraud & Dispute — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Dispute, Fraud, Unauthorized, Chargeback, Suspicious, Card Stolen, Compromised, Security, Provisional Credit, Investigation, Fraud Alert, Account Takeover.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim fraud/dispute issue
- `policy_friction` — Policy barriers in dispute resolution
- `solution_by_ops` — Operational improvements for fraud handling
- `solution_by_education` — Customer education on fraud prevention
- `solution_by_technology` — Technology fixes for fraud detection
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Legitimate Transaction Blocked by Fraud System (False Positive)
**Signal**: "card declined", "blocked transaction", "legitimate purchase flagged", "why was my card blocked"
**Root Cause Tree**:
- Fraud model over-triggers on normal spending patterns (travel, large purchases, online)
- No pre-trip or pre-purchase notification mechanism
- Unblock process requires calling (no in-app "this was me" confirmation)
- Card block applies to ALL transactions until agent unblocks (nuclear option)
**Self-Service Gap**: Can customer mark a flagged transaction as legitimate in-app? Can they pre-authorize travel or large purchases? Is there a one-tap "this was me" on the fraud alert?
**Typical Volume**: 20–30% of fraud/dispute calls — often the largest single driver
**Call Reduction Lever**: In-app "Was this you?" push notification with one-tap confirm/deny, travel notification feature, transaction-level unblock (not full card block), real-time fraud alert with inline response

### Pattern 2: Dispute Status Invisible
**Signal**: "what's happening with my dispute", "no update on my case", "how long will investigation take"
**Root Cause Tree**:
- Dispute filed but no case tracking visible in app
- Investigation timeline communicated vaguely ("7–10 business days" without specificity)
- No intermediate status updates between filing and resolution
- Customer must call to check status (status check call = waste of agent time and customer time)
**Self-Service Gap**: Can customer see dispute status in-app? Are there milestone notifications (received → investigating → resolved)? Is the estimated resolution date visible?
**Typical Volume**: 15–25% of fraud/dispute calls
**Call Reduction Lever**: Dispute tracker in app with status milestones, push notification at each stage change, estimated resolution date with countdown, "Your dispute is being reviewed — no action needed from you" reassurance message

### Pattern 3: Provisional Credit Timeline Unclear
**Signal**: "when do I get my money back", "temporary credit", "provisional credit not received", "how long for refund"
**Root Cause Tree**:
- Provisional credit eligibility rules differ by dispute type (fraud vs merchant dispute)
- Timeline for provisional credit not communicated at filing time
- Customer doesn't understand provisional vs final credit
- Some dispute types don't qualify for provisional credit but customer expects it
**Self-Service Gap**: Is provisional credit status visible in app? Is the timeline shown at dispute filing? Is eligibility criteria transparent?
**Typical Volume**: 10–15% of fraud/dispute calls
**Call Reduction Lever**: Show provisional credit timeline at dispute filing ("Provisional credit within 10 business days for eligible disputes"), distinguish provisional vs final credit in transaction view, push notification when provisional credit posts

### Pattern 4: Documentation Requirements Not Clear Upfront
**Signal**: "what documents do I need", "asked for more information", "already sent this", "multiple submissions"
**Root Cause Tree**:
- Required documentation not listed at dispute initiation
- Document requirements change mid-investigation (additional docs requested later)
- Upload mechanism unavailable in app (must fax, email, or mail)
- No confirmation that documents were received successfully
**Self-Service Gap**: Is there a checklist of required documents at filing? Can customer upload documents in-app? Is there a receipt/confirmation for submitted documents?
**Typical Volume**: 5–10% of fraud/dispute calls
**Call Reduction Lever**: Complete document checklist shown at filing, in-app secure document upload with instant confirmation, "We have everything we need" or "We still need X" status in app

### Pattern 5: Card Replacement After Fraud
**Signal**: "where is my new card", "replacement card", "how long for new card", "card not received"
**Root Cause Tree**:
- Card replacement timeline not communicated clearly (standard vs rush)
- Tracking information not provided for shipped cards
- No interim digital card issued while physical card is in transit
- Old card auto-payments not automatically migrated to new card number
**Self-Service Gap**: Can customer track card shipment? Is a virtual/digital card issued immediately? Is there an auto-payment migration tool?
**Typical Volume**: 5–10% of fraud/dispute calls
**Call Reduction Lever**: Instant virtual card issuance for immediate use, shipment tracking for physical card, proactive notification about auto-payment migration ("Update your card on file at these merchants: Netflix, Spotify, ..."), rush delivery option in app

### Pattern 6: Fraud Alert Response Friction
**Signal**: "got a fraud alert", "couldn't respond to alert", "responded but card still blocked", "alert for old transaction"
**Root Cause Tree**:
- Fraud alert response mechanism is SMS-only (reply Y/N) — modern customers expect in-app
- Alert response doesn't immediately unblock the card (processing delay)
- Alerts sent for already-resolved transactions (timing lag)
- Customer can't distinguish between fraud alert and phishing attempt
**Self-Service Gap**: Can customer respond to fraud alerts in-app? Is card immediately unblocked upon "legitimate" response? Is the alert clearly branded to distinguish from phishing?
**Typical Volume**: 5–10% of fraud/dispute calls
**Call Reduction Lever**: In-app fraud alert with one-tap response and immediate card unblock, branded alert design, real-time alert processing (not batched), "Alert resolved — your card is active" instant confirmation

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `exact_problem_statement` and `policy_friction` within the fraud/dispute bucket
2. **Pattern Matching**: Map top problem statements to the 6 patterns above
3. **Volume Sizing**: Calculate % of fraud/dispute bucket for each pattern
4. **Process Assessment**: Check `solution_by_ops` for operational improvement suggestions already in the data
5. **Cross-Reference**: Apply `apply_skill("fraud_dispute", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in fraud/dispute data |
|------|----------------------------------------|
| **Digital** | Can disputes be filed entirely in-app? Is case tracking visible? Can customer respond to fraud alerts in-app? |
| **Operations** | Are investigation SLAs met? Is provisional credit issued on time? Are manual review queues backlogged? |
| **Communication** | Are dispute milestones communicated proactively? Is the investigation timeline set upfront? Are resolution outcomes explained clearly? |
| **Policy** | Are investigation timelines regulatory (Reg E/Z)? Can provisional credit rules be communicated better? Are documentation requirements proportional to dispute amount? |

## Anti-Patterns (What NOT to Conclude)
- Don't assume all "fraud" calls are about actual fraud — false positives and dispute inquiries are often larger volume
- Don't recommend weakening fraud detection — recommend making the response to legitimate transactions smoother
- Don't conflate dispute filing friction with investigation friction — they're different process stages
- Don't blame customers for falling for phishing — the question is whether the bank's fraud response system worked properly after the fact

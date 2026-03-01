# Card Replacement — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Replace Card, New Card, Lost Card, Stolen Card, Damaged Card, Card Delivery, Card Not Received, Card Activation, PIN Setup, Card Status, Card Tracking, Replacement Request, Expedited Card, Emergency Card, Card Decline After Replacement, Card Upgrade, Reissue, Express Delivery.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim card replacement issue
- `digital_friction` — Digital barriers during the replacement or activation process
- `solution_by_ui` — UI improvements for self-service card replacement and activation
- `solution_by_ops` — Operational process improvements for fulfillment and delivery
- `solution_by_education` — Customer guidance for card lifecycle self-service
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Card Not Received / Delivery Tracking Gaps
**Signal**: "haven't received my card", "where is my card", "how long does it take", "delivery status", "it's been two weeks", "card never arrived", "tracking number"
**Root Cause Tree**:
- No real-time delivery tracking available to the customer — they call to check status
- Estimated delivery window is vague ("7-10 business days") with no updates after dispatch
- USPS/courier handoff not tracked — card is "shipped" but customer has no way to verify
- Address mismatch between card mailing address and current address (moved recently, didn't update before requesting)
- Replacement card sent to an old address because address update didn't propagate before fulfillment
- No proactive notification when card is in transit, out for delivery, or delivered
**Self-Service Gap**: Can the customer check card delivery status in-app? Is there a tracking number or estimated delivery date shown after request? Is there a "card not received after X days" self-service reorder flow? Does the app show which address the card was shipped to?
**Typical Volume**: 30–40% of card replacement calls — the single largest driver
**Call Reduction Lever**: In-app delivery tracking with carrier integration (USPS Informed Delivery or courier API), proactive push notifications at dispatch/in-transit/delivered milestones, address confirmation screen before card ships ("We'll send your card to 123 Main St — is this correct?"), automatic reissue trigger if card not activated within 14 days of expected delivery

### Pattern 2: Card Activation Failures
**Signal**: "can't activate my card", "activation not working", "sticker says call to activate", "tried to activate online", "new card won't activate", "activation error"
**Root Cause Tree**:
- Activation sticker on card says "Call to activate" even though in-app activation exists — mixed messaging
- In-app activation flow requires last 4 of old card number which customer may not have (old card was destroyed/lost)
- Activation fails silently — no error message, card just doesn't work
- Multiple cards on account — system activates wrong card or customer selects wrong card in app
- Activation blocked because address verification failed (mismatch between card address and file address)
- Old card auto-deactivated before new card arrived, leaving customer cardless during gap
**Self-Service Gap**: Is in-app activation prominently offered? Does the activation flow work without requiring old card details? Is there a clear error message when activation fails? Can the customer see which card is being activated on multi-card accounts?
**Typical Volume**: 15–25% of card replacement calls
**Call Reduction Lever**: Remove "Call to activate" sticker (replace with "Activate in app or at any ATM"), in-app activation with biometric verification (no old card number needed), clear activation error messages with resolution steps, proactive push notification when new card is ready to activate ("Your new card ending 4321 is ready — tap to activate")

### Pattern 3: PIN Setup and Reset for New Card
**Signal**: "set up PIN", "PIN for new card", "how to change PIN", "PIN not working on new card", "forgot to set PIN", "ATM says wrong PIN"
**Root Cause Tree**:
- New card ships without PIN — customer doesn't know how to set one before first use
- PIN creation flow in app is separate from activation — customer activates card but misses PIN step
- PIN from old card doesn't carry over to replacement — customer uses old PIN and gets declined
- PIN creation requires calling or visiting ATM — no in-app path
- PIN change vs PIN creation distinction unclear — different flows for same outcome
- Temporary PIN mailed separately creates timing confusion (card arrives before PIN letter, or vice versa)
**Self-Service Gap**: Can the customer set a PIN in-app during activation? Is it clear that old PIN does not carry over? Is there a "Set PIN before first use" prompt in the activation flow? Can PIN be created at any ATM with identity verification?
**Typical Volume**: 10–15% of card replacement calls
**Call Reduction Lever**: Integrate PIN creation into card activation flow (activate → set PIN → done), in-app instant PIN set with biometric verification, carry forward old PIN to replacement card by default (opt-in to change), eliminate separate PIN mailer — all PIN management in-app

### Pattern 4: Payments Declining on New Card
**Signal**: "new card declined", "card not working", "tried to use new card but it was rejected", "merchant says card is invalid", "recurring payments stopped", "autopay broken after replacement"
**Root Cause Tree**:
- New card has different number, expiry, and CVV — all recurring payments and saved cards at merchants break
- Customer not informed that saved payment methods across merchants need updating
- Card-on-file at streaming services, subscriptions, utilities — each must be updated manually
- Some merchants use card updater service (Visa Account Updater, Mastercard ABU) but not all — inconsistent experience
- Temporary authorization hold from old card still pending — confusing decline messages
- New card network restrictions (international, online) differ from old card defaults
**Self-Service Gap**: Does the app list merchants that need card number updates? Is there a "update your card everywhere" guide after replacement? Does the app show which recurring payments are affected? Is there a proactive alert before the first recurring payment attempt on the old card?
**Typical Volume**: 10–15% of card replacement calls
**Call Reduction Lever**: Post-replacement "Update your card" checklist showing known recurring merchants (from transaction history), proactive notification before first failed recurring charge, in-app card updater service enrollment prompt, "Your new card details" quick-copy screen for easy merchant updates

### Pattern 5: Expedited / Emergency Card Requests
**Signal**: "need card urgently", "traveling and lost card", "express delivery", "can I get a card today", "emergency card", "overnight shipping", "how fast can I get a replacement"
**Root Cause Tree**:
- Expedited shipping option not visible in self-service replacement flow (only offered when calling)
- Expedited shipping cost not disclosed upfront — customer surprised by fee
- No digital card / virtual card option while waiting for physical replacement
- Emergency card issuance at branch not available for all card types
- Express delivery available but takes 2-3 days, not same-day — mismatch between "express" and customer expectation
- International customers have no expedited option — card ships domestic only
**Self-Service Gap**: Can the customer request expedited shipping in-app? Is the fee disclosed before confirmation? Is a virtual card number issued instantly for online purchases while waiting? Can the customer add the virtual card to Apple Pay / Google Pay immediately?
**Typical Volume**: 5–10% of card replacement calls (but highest urgency and frustration)
**Call Reduction Lever**: Instant virtual card number issued at time of replacement request (usable immediately for online purchases and digital wallets), in-app expedited shipping toggle with transparent fee, branch pickup option shown for urgent needs, "Add to Apple Wallet now" prompt for virtual card while physical card ships

### Pattern 6: Card Replacement Request Process Friction
**Signal**: "how do I get a new card", "replacement card", "card is damaged", "card chip not working", "card is cracked", "want a new card", "magnetic stripe worn out"
**Root Cause Tree**:
- Replacement request flow buried in app settings (not on card management screen)
- Reason for replacement required but options don't match reality (customer's chip is worn but "damaged" isn't an option)
- Replacement confirmation unclear — customer doesn't know if request went through
- Old card deactivated immediately upon request — customer expected to keep using old card until new one arrives
- Multi-step verification required for simple cosmetic replacement (same security as lost/stolen)
- No option to request a replacement without reporting card as lost or stolen (e.g., wear and tear, design upgrade)
**Self-Service Gap**: Is the replacement request flow findable from the card management screen? Does the customer get confirmation with expected delivery date? Can they choose when the old card is deactivated? Is there a "replace due to wear" option that keeps the old card active until the new one arrives?
**Typical Volume**: 10–15% of card replacement calls
**Call Reduction Lever**: "Replace this card" button on card detail screen, replacement reason dropdown including "wear and tear" (keeps old card active), confirmation screen showing delivery estimate and old card deactivation timing, option to keep old card active until new card is activated

### Pattern 7: Address Issues During Replacement
**Signal**: "sent to wrong address", "need to change address before shipping", "moved recently", "update address for card delivery", "card went to old address"
**Root Cause Tree**:
- Address update and card replacement are separate flows — customer updates address AFTER requesting replacement, card already shipped to old address
- No address confirmation step in replacement request flow
- Temporary address option not available (e.g., staying at hotel, visiting family)
- P.O. box rejected for card delivery but customer not told why
- Address verification failure blocks replacement silently — no feedback to customer
**Self-Service Gap**: Does the replacement flow confirm shipping address before submitting? Can the customer set a temporary delivery address? Is the address update reflected in real-time before card ships? Is there clear feedback if an address is rejected?
**Typical Volume**: 5–10% of card replacement calls
**Call Reduction Lever**: Mandatory address confirmation step in replacement flow ("Ship to: 123 Main St — Change?"), temporary address option for one-time delivery, real-time address validation with instant feedback, link to update address within the replacement flow (not a separate flow)

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `exact_problem_statement` and `digital_friction` within the card replacement bucket
2. **Pattern Matching**: Map top problem statements to the 7 patterns above using keyword and theme matching
3. **Volume Sizing**: Calculate % of total card replacement calls each pattern represents
4. **Lifecycle Stage Mapping**: Classify issues by card lifecycle stage (request → fulfillment → delivery → activation → first use) to identify which stage generates the most friction
5. **Cross-Reference**: Apply `apply_skill("card_replacement", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in card replacement data |
|------|-------------------------------------------|
| **Digital** | Can replacement be requested entirely in-app? Is delivery tracking available? Is in-app activation seamless? Is PIN setup part of activation? Is there an instant virtual card while waiting? |
| **Operations** | What is the fulfillment-to-delivery time? Are expedited requests processed differently? Is address update propagation instant before card ships? Are activation failures logged and resolved proactively? |
| **Communication** | Is delivery status communicated proactively? Is the customer told which address the card ships to? Are recurring payment impacts disclosed? Is activation instruction clear on the card itself? |
| **Policy** | Does old card deactivation timing match customer needs? Is expedited shipping fee proportional? Are replacement reasons flexible enough for cosmetic requests? Is verification for replacement proportional to risk (damaged ≠ stolen)? |

## Anti-Patterns (What NOT to Conclude)
- Don't treat all card replacement calls as lost/stolen emergencies — many are routine wear-and-tear or upgrade requests that should be frictionless
- Don't assume customers know their old card number after requesting replacement — if the old card was destroyed, don't require its details for activation
- Don't recommend removing old-card deactivation — recommend giving customers CONTROL over when it happens (immediate for lost/stolen, delayed for damaged/upgrade)
- Don't blame customers for not updating merchants — if the bank has transaction history showing recurring payments, proactively listing affected merchants is the bank's responsibility
- Don't conflate delivery frustration with fulfillment speed — most "where is my card" calls are about VISIBILITY, not speed. Customers tolerate 7-10 days if they can track progress; they don't tolerate 3 days of silence

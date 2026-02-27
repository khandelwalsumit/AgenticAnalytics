# General Inquiry — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: General Inquiry, Account Information, Balance Inquiry, Fee Inquiry, Product Question, Credit Limit, Interest Rate, Card Benefits, How-To, Policy Question, Branch/ATM, Account Status, Eligibility Question, Product Comparison.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim inquiry
- `digital_friction` — Why the customer couldn't find the answer digitally before calling
- `solution_by_ui` — UI/content improvements that would have answered the question self-service
- `solution_by_education` — Proactive education that would have prevented the inquiry
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Balance, Limit & Account Status Inquiries
**Signal**: "what's my balance", "what's my credit limit", "is my account open", "available credit", "current balance vs. statement balance"
**Root Cause Tree**:
- Available credit vs. statement balance vs. current balance distinction not clear in-app
- Pending transactions temporarily obscure true available credit — no explanation shown
- Credit limit not prominently visible on account home screen
- Recent payment not reflected yet — customer uncertain if payment was received
- Multiple accounts displayed but no consolidated balance view
**Self-Service Gap**: Is the account home screen the definitive one-stop for balance, available credit, and pending transactions? Is the difference between current and statement balance explained in-app? Is recent payment reflected quickly?
**Typical Volume**: 25–35% of general inquiry calls — most preventable with better information architecture
**Call Reduction Lever**: Account summary card showing current balance, statement balance, available credit, and credit limit in one view; pending transaction explainer tooltip; real-time payment confirmation ("Payment received — available credit will update within 2 hours"); consolidated multi-account dashboard

### Pattern 2: Fee Inquiries (Annual Fee, Late Fee, Foreign Transaction Fee)
**Signal**: "why was I charged this fee", "what is this charge", "annual fee", "can this be waived", "late fee"
**Root Cause Tree**:
- Fee line item description generic ("ANNUAL MEMBERSHIP FEE") with no in-app drill-down explaining what it covers
- Fee waiver eligibility unknown to customer (e.g., spend threshold waives annual fee)
- Late fee surprise — payment due date notification not sent or missed
- Foreign transaction fee not disclosed clearly at point of transaction
- Fee amount changed (e.g., annual fee increase) without adequate advance notice
**Self-Service Gap**: Can customer tap a fee line item and see a plain-language explanation? Is fee waiver eligibility and current progress shown? Is the due date prominently visible with notifications?
**Typical Volume**: 15–20% of general inquiry calls
**Call Reduction Lever**: Tappable fee explainer on every fee line item, fee waiver progress tracker ("Spend $X more this year to waive your $95 annual fee"), payment due date banner with 3-day reminder, foreign transaction fee disclosure shown at the time of international transactions

### Pattern 3: Interest Rate & APR Inquiries
**Signal**: "what's my interest rate", "why is my rate this high", "how is interest calculated", "when does interest start", "difference between APR types"
**Root Cause Tree**:
- APR shown as one number but multiple rates apply (purchase, cash advance, penalty) — customer doesn't know which applies to them
- Daily periodic rate calculation not explained — customers don't understand how daily interest accrues
- Grace period definition unclear — customer doesn't know when interest-free period ends
- Penalty APR triggered after late payment — customer didn't know this could happen
- Rate comparison to promotional rate after promo expiry causes confusion
**Self-Service Gap**: Is the APR clearly labeled by type (purchase, cash advance, penalty) with plain-language explanation? Is the grace period end date visible per billing cycle? Is there an interest calculator showing projected interest if minimum payment is made?
**Typical Volume**: 10–15% of general inquiry calls
**Call Reduction Lever**: APR breakdown screen with each rate labeled, grace period countdown per billing cycle, interest projection calculator ("If you pay $50/month at 24.99% APR, payoff takes 3.2 years — total interest: $312"), penalty APR warning when late payment risk is detected

### Pattern 4: Card Benefits & Perks Inquiries
**Signal**: "what benefits does my card have", "do I have travel insurance", "how do I use my lounge access", "extended warranty", "cell phone protection"
**Root Cause Tree**:
- Benefits guide exists as a PDF but is not accessible in-app or easily searchable
- Customer doesn't know which benefits require activation or registration
- Benefit eligibility unclear (e.g., travel insurance only covers flights booked with the card)
- Multiple card tiers have different benefits — customer confused which tier they're on
- Benefit changed or was removed without clear communication
**Self-Service Gap**: Is there a searchable, in-app benefits hub that lists all active benefits with eligibility rules? Are benefits that require activation flagged clearly? Can customer see which tier they're on and what that unlocks?
**Typical Volume**: 10–15% of general inquiry calls
**Call Reduction Lever**: In-app benefits hub with search, categorized by benefit type (travel, purchase protection, lifestyle), activation-required badge on benefits needing registration, personalized benefits page showing only what applies to their specific card, onboarding benefit highlight flow for new cardholders

### Pattern 5: Credit Limit Increase / Eligibility Inquiries
**Signal**: "can I get a higher limit", "am I eligible for a limit increase", "why was I denied", "how do I request an increase", "when can I reapply"
**Root Cause Tree**:
- Credit limit increase request flow is not easily findable in-app
- Eligibility criteria not communicated before application — customer applies without knowing requirements
- Denial reason is vague ("does not meet our criteria") with no actionable path forward
- Reconsideration timeline not stated — customer calls repeatedly checking eligibility
- Hard inquiry risk not disclosed before customer initiates request
**Self-Service Gap**: Is there an in-app CLI request with pre-eligibility check (soft pull)? Is the denial reason specific with steps to re-qualify? Is the re-application wait period stated explicitly?
**Typical Volume**: 5–10% of general inquiry calls (but high satisfaction impact)
**Call Reduction Lever**: In-app CLI request with soft-pull eligibility check before committing, clear denial reason with re-qualification roadmap ("Your limit will be reviewed again in 6 months — here's what improves eligibility"), automatic re-eligibility notification when criteria are met

### Pattern 6: Product Information & Comparison Inquiries
**Signal**: "which card should I get", "what's the difference between my cards", "can I switch to a different card", "features of this product", "is there a better card for me"
**Root Cause Tree**:
- Product comparison tool does not exist in-app for existing customers comparing their own portfolio
- Card recommendation logic is one-way (only at acquisition) — not proactive for existing customers
- Product switch eligibility and process is unclear — customers don't know they can product-change without a new application
- Card benefits for their current card are not surfaced relative to alternatives
- Application flow does not explain what happens to their current card if they upgrade
**Self-Service Gap**: Is there an in-app product comparison or "find the right card for me" tool for existing customers? Is the product change (not new application) flow available and discoverable? Does the recommendation engine surface if a customer is on a sub-optimal product for their spend pattern?
**Typical Volume**: 5–10% of general inquiry calls
**Call Reduction Lever**: In-app product selector/quiz for existing customers, personalized card recommendation based on spend history ("Based on your dining spend, CardX would earn you $150 more per year"), one-tap product change request with clear impact summary, proactive annual "Is your card still right for you?" insight

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `exact_problem_statement` and `digital_friction` within the general inquiry bucket
2. **Pattern Matching**: Map top problem statements to the 6 patterns above using keyword and theme matching
3. **Volume Sizing**: Calculate % of general inquiry bucket each pattern represents
4. **Findability Assessment**: Check `digital_friction` for mentions of "couldn't find", "not visible", "no information" — these signal information architecture failures
5. **Cross-Reference**: Apply `apply_skill("general_inquiry", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in general inquiry data |
|------|-------------------------------------------|
| **Digital** | Could the answer be found in-app without calling? Is information architecture clear? Are key figures (balance, limit, APR, benefits) findable within 2 taps? Is search functional for account info? |
| **Operations** | Are balance and payment reflections delayed? Are CLI decisions taking too long? Are account status updates synced across systems? Are fee adjustments processed timely? |
| **Communication** | Are proactive disclosures sent for fee changes, rate changes, or benefit updates? Are due dates and billing cycle changes communicated early? Are denial decisions explained in writing? |
| **Policy** | Are fee waiver policies flexible enough for first-time exceptions? Are CLI eligibility rules disclosed pre-application? Can hard inquiry be replaced with soft-pull for standard requests? Are benefit change communications regulatory or discretionary? |

## Anti-Patterns (What NOT to Conclude)
- Don't treat general inquiries as low-priority just because they aren't complaints — high volume preventable calls drive significant cost even without customer frustration
- Don't assume customers prefer calling for information — most general inquiry calls represent a digital self-service failure, not a preference for human contact
- Don't recommend adding more content to existing pages — recommend surfacing the right content at the right moment (contextual disclosure, not more PDFs)
- Don't conflate "customer didn't know" with "customer was uneducated" — if the information required a phone call to find, the product design failed
- Don't recommend removing human support for complex inquiries — recommend ensuring simple, repetitive inquiries are fully self-serviceable so agents handle only genuinely complex cases

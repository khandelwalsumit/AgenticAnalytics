# Promotions & Offers — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Promotion, Offer, Sign-Up Bonus, Balance Transfer, Intro Rate, Spend Offer, Statement Credit, Merchant Deal, Limited-Time Offer, Upgrade Offer, Welcome Bonus, Cashback Promotion, Credit Offer.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim promotions/offer issue
- `digital_friction` — Digital barrier preventing offer self-service
- `solution_by_ui` — UI improvements for offer visibility and tracking
- `solution_by_education` — Customer education opportunities around offer terms
- `policy_friction` — Policy friction tied to offer eligibility or redemption rules
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Sign-Up / Welcome Bonus Not Credited
**Signal**: "didn't receive my bonus", "welcome offer not applied", "sign-up bonus missing", "promised $200 and never got it"
**Root Cause Tree**:
- Minimum spend met but not within qualifying window (customer unaware of deadline)
- Spend threshold met but certain transaction categories excluded (e.g., balance transfers don't count)
- Bonus posted to wrong account cycle or delayed beyond expected posting date
- Customer signed up through a non-qualifying channel (branch vs. online link)
- Duplicate account or reapplication disqualification not communicated at point of application
**Self-Service Gap**: Can customer track their progress toward the welcome bonus spend threshold? Is the qualifying window visible in-app? Is the posting timeline clearly stated post-application?
**Typical Volume**: 20–30% of promotions calls — often highest single driver
**Call Reduction Lever**: Welcome bonus tracker with spend progress bar ("Spend $850 more by June 30 to earn $200 bonus"), qualifying category rules on one screen, estimated posting date once threshold met, notification when bonus posts

### Pattern 2: Promotional Balance Transfer Rate Confusion
**Signal**: "intro rate not applied", "balance transfer rate wrong", "thought it was 0%", "promo period ended"
**Root Cause Tree**:
- Promotional APR end date not prominently visible; customer unaware it expired
- Minimum payment during promo period didn't cover enough principal — deferred interest shock
- Balance transfer fee not clearly shown at initiation (e.g., 3% fee applied unexpectedly)
- Promo rate applied to existing balance but new purchases accruing standard rate — confusion between balances
- Promotion expired while transfer was pending (applied too late)
**Self-Service Gap**: Is the promotional APR end date shown on each statement and in-app? Is there a deferred interest explainer? Can customer see which balance bucket (transfer vs. purchase) their payments are applied to?
**Typical Volume**: 15–25% of promotions calls
**Call Reduction Lever**: Countdown timer for promo end date visible in-app and on statements, deferred interest risk warning 60/30 days before expiry, payment allocation breakdown ("Your payment was applied: $X to balance transfer, $Y to purchases"), push notification 30 days before promo ends

### Pattern 3: Spend-and-Get Offer Progress Not Visible
**Signal**: "did I hit the spend amount", "how much more do I need", "offer tracker", "not sure if I qualify"
**Root Cause Tree**:
- Spend-and-get offers exist in marketing but have no in-app progress tracker
- Qualifying merchant categories not listed in offer terms (or buried in fine print)
- Offer tied to specific card but customer used alternate card by mistake
- Spend accrual has a lag — customer sees $0 progress days after qualifying purchases
**Self-Service Gap**: Is there an offer tracker per active promotion? Are qualifying category exclusions shown clearly? Does the app notify customer when they complete the spend requirement?
**Typical Volume**: 15–20% of promotions calls
**Call Reduction Lever**: Per-offer progress tracker ("Spend $200 more by Aug 31 to earn 5,000 bonus points"), eligible vs. excluded merchant category list accessible from offer detail, completion notification with estimated credit date

### Pattern 4: Statement Credit / Promotional Credit Not Posted
**Signal**: "didn't get my credit", "statement credit missing", "promised credit not applied", "where's my $50 credit"
**Root Cause Tree**:
- Credit posts on a billing cycle lag (customer expects immediate credit, actual is 1–2 cycles)
- Qualifying action completed but system didn't register it (e.g., linking a streaming subscription)
- Offer required activation and customer never activated it
- Credit applied but offset by fees — customer sees net-zero and assumes it didn't apply
- Offer was one-time but customer expected recurring
**Self-Service Gap**: Can customer see pending credits before they post? Is the credit posting timeline in the offer detail? Is activation status visible in-app?
**Typical Volume**: 20–25% of promotions calls
**Call Reduction Lever**: Pending credits view in account dashboard, credit posting timeline shown per offer ("Expected credit: within 2 billing cycles"), offer activation status with one-tap activation CTA, notification when statement credit is applied

### Pattern 5: Merchant-Specific Deal Not Honored
**Signal**: "merchant offer didn't work", "cashback from [merchant] not received", "partner deal expired", "didn't get my discount"
**Root Cause Tree**:
- Offer requires card to be added to merchant wallet — customer wasn't prompted to do so
- Merchant offer has geographic or channel restrictions (in-store only, not online)
- Offer expired or was removed after customer bookmarked it but before use
- Minimum purchase amount not met at the merchant
- Customer used wrong tender (split payment voided offer)
**Self-Service Gap**: Does the app guide customer through offer activation steps per merchant? Is expiry date shown at offer level? Is channel restriction (in-store only) clearly labeled?
**Typical Volume**: 10–15% of promotions calls
**Call Reduction Lever**: Step-by-step merchant offer activation guide per deal, expiry date and channel restriction prominent in offer listing, expiry reminder notification 48 hours before deal ends, automatic card-linking for eligible recurring merchants

### Pattern 6: Product Upgrade / Downgrade Offer Confusion
**Signal**: "upgrade offer not what I expected", "changed card and lost my offer", "downgrade removed my promo", "not sure if I should accept this offer"
**Root Cause Tree**:
- Product change voids existing promotional rates — customer not warned before accepting upgrade
- Upgrade offer terms differ from current card benefits — customer can't easily compare
- Introductory period restarts vs. carries over — not clear in offer communication
- Annual fee change with upgrade not prominently stated
- Customer accepted upgrade and lost cashback category that was driving their decision
**Self-Service Gap**: Is there a side-by-side benefit comparison before accepting an upgrade/downgrade? Is the impact on existing promotions explicitly stated? Can customer simulate what changes?
**Typical Volume**: 5–10% of promotions calls (but high churn risk if negative outcome)
**Call Reduction Lever**: Pre-upgrade impact summary ("Accepting this offer will: end your 0% promo APR on April 15, change your rewards from 3x dining to 2x dining, add $95 annual fee"), explicit confirmation step, 30-day downgrade reversal window

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `exact_problem_statement` and `digital_friction` within the promotions/offers bucket
2. **Pattern Matching**: Map top problem statements to the 6 patterns above using keyword matching
3. **Volume Sizing**: Calculate % of promotions bucket each pattern represents
4. **Activation Gap Check**: Check `solution_by_ui` for mentions of activation, tracker, or visibility — these signal self-service gaps
5. **Cross-Reference**: Apply `apply_skill("promotions_offers", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in promotions/offers data |
|------|---------------------------------------------|
| **Digital** | Is offer progress trackable in-app? Are activation steps clearly guided? Is the credit posting timeline visible? Is there a pending credits view? |
| **Operations** | Are statement credits posted within SLA? Is the spend-accrual lag acceptable? Are manual credit adjustments backlogged? Is offer registration timely? |
| **Communication** | Are promo end dates communicated 30/60 days before expiry? Are activation requirements emailed at offer start? Are credit postings confirmed via push? |
| **Policy** | Are offer exclusions regulatory or internal? Can deferred interest rules be simplified? Are minimum spend thresholds risk-based or arbitrary? Can upgrade reversal windows be extended? |

## Anti-Patterns (What NOT to Conclude)
- Don't assume all "credit not posted" calls are system errors — most are posting-lag confusion or missed activation steps
- Don't recommend eliminating offer exclusions — recommend surfacing them clearly at point of enrollment
- Don't conflate rewards program promotions with standalone spend-and-get offers — they have different mechanics
- Don't treat promo expiry complaints as customer negligence — if the expiry date requires a phone call to find, the communication design is the problem
- Don't recommend blanket promo extensions — recommend better expiry communication and timely completion reminders

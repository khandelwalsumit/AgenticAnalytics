# Rewards & Loyalty — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Rewards, Points, Cashback, Redemption, Miles, Tier, Loyalty, Bonus, Promotional Offer, Earn Rate, Expiry, Forfeiture.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim rewards issue
- `digital_friction` — Digital barrier in rewards experience
- `solution_by_ui` — UI improvements for rewards visibility
- `policy_friction` — Policy friction in rewards programs
- `solution_by_education` — Customer education opportunities
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Points Not Posted After Qualifying Transaction
**Signal**: "where are my points", "didn't get my cashback", "points not credited", "missing rewards"
**Root Cause Tree**:
- Points posting delay not aligned with customer expectation (real-time expectation vs 1–2 billing cycle reality)
- Transaction posted but points engine hasn't processed yet (batch vs real-time mismatch)
- Transaction didn't qualify but customer assumed it did (excluded merchant category codes)
- Promotional earning rule applied different multiplier than expected
**Self-Service Gap**: Can customer see "pending points" before they post? Can they see earn rate per transaction? Is the posting timeline explained at transaction level?
**Typical Volume**: 25–35% of rewards calls — often the single largest driver
**Call Reduction Lever**: "Pending points" view in rewards dashboard, estimated posting date per transaction, earn rate visibility at transaction level ("This purchase earns 2x — expected points: 500"), push notification when points post

### Pattern 2: Redemption Failure / Confusion
**Signal**: "can't redeem", "not enough points", "redemption failed", "how do I use points"
**Root Cause Tree**:
- Minimum redemption threshold not visible before attempt
- Points-to-dollar conversion rate unclear
- Redemption options buried in app navigation (findability failure)
- Partial redemption not allowed (must use minimum increment)
- Eligible redemption partners not clearly listed
**Self-Service Gap**: Can customer see redemption options + eligibility on one screen? Is the conversion math shown before confirming? Is minimum threshold displayed upfront?
**Typical Volume**: 15–20% of rewards calls
**Call Reduction Lever**: Redemption calculator on rewards dashboard ("You have 15,000 points = $150"), one-tap redemption for common options (statement credit, gift cards), show "You need X more points to redeem" when below threshold

### Pattern 3: Points Expiry Without Adequate Warning
**Signal**: "points expired", "lost my rewards", "didn't know they expire", "no warning"
**Root Cause Tree**:
- Expiry notification sent too late (7 days before is not enough for accumulated value)
- Notification buried in email (not in-app or push)
- Expiry rules differ by card type and customer doesn't know which applies
- No option to extend or preserve expiring points
**Self-Service Gap**: Is expiry date visible on rewards dashboard? Are there multiple notification channels (push + email + in-app)? Can customer extend expiry by making a qualifying transaction?
**Typical Volume**: 5–10% of rewards calls (but VERY high emotional intensity)
**Call Reduction Lever**: 90/30/7 day cascade notifications across all channels, in-app expiry countdown, "Use 500 points before March 15 or they expire" with one-tap redemption CTA, option to convert to statement credit before expiry

### Pattern 4: Promotional Offer Eligibility Confusion
**Signal**: "didn't get the bonus", "promotion not applied", "offer terms", "thought I qualified"
**Root Cause Tree**:
- Promotional terms buried in fine print (minimum spend, merchant exclusions, time window)
- Customer targeted with offer but didn't meet ALL qualifying criteria
- Offer tracking not visible ("You've spent $300 of $500 needed for bonus")
- Conflict between multiple active promotions not communicated
**Self-Service Gap**: Can customer see active offers with progress tracking? Are qualifying criteria clearly listed on one screen? Is there a "Why didn't I earn the bonus?" self-service diagnostic?
**Typical Volume**: 10–15% of rewards calls
**Call Reduction Lever**: Offer tracker with progress bar ("Spend $200 more by April 30 to earn 10,000 bonus points"), qualifying criteria checklist visible in offer detail, post-period "Your offer results" notification explaining outcome

### Pattern 5: Tier/Status Changes
**Signal**: "tier changed", "lost my status", "benefits removed", "how do I qualify"
**Root Cause Tree**:
- Tier evaluation window and requirements not clearly communicated
- Downgrade notification arrives after benefits are removed (retroactive frustration)
- Qualification progress not visible ("You need $X more spend to maintain Gold status")
- Tier benefits comparison not easily accessible
**Self-Service Gap**: Is tier progress visible year-round? Are upcoming tier changes communicated 60+ days in advance? Can customer see exactly what they lose/gain with a tier change?
**Typical Volume**: 3–5% of rewards calls (but high churn correlation)
**Call Reduction Lever**: Tier progress dashboard ("$2,000 more spend by Dec 31 to keep Platinum"), 60-day advance warning for downgrades, side-by-side tier benefits comparison, "How to maintain your status" guide

### Pattern 6: Earn Rate / Cashback Rate Confusion
**Signal**: "wrong earn rate", "should be 2x", "cashback percentage wrong", "not earning on this category"
**Root Cause Tree**:
- Merchant category codes don't match customer's mental model ("Walmart.com" codes as online not grocery)
- Category bonuses have caps that aren't prominent (e.g., "3x on dining up to $500/quarter")
- Base vs bonus earn rates not distinguished in transaction view
- Card-specific earn structure differs from marketing messaging
**Self-Service Gap**: Can customer see the earn rate applied to EACH transaction? Is the category mapping logic explained? Are category caps shown with progress?
**Typical Volume**: 5–10% of rewards calls
**Call Reduction Lever**: Per-transaction earn rate display in transaction history, category cap progress bar, MCC-to-category mapping explainer, earn rate simulator for prospective purchases

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `exact_problem_statement` and `digital_friction` within the rewards bucket
2. **Pattern Matching**: Map top problem statements to the 6 patterns above using keyword matching
3. **Volume Sizing**: Calculate % of rewards bucket for each pattern
4. **Self-Service Readiness**: Check `solution_by_ui` and `solution_by_education` to see what digital fixes are already suggested
5. **Cross-Reference**: Apply `apply_skill("rewards", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in rewards data |
|------|----------------------------------|
| **Digital** | Is rewards balance easily visible? Is earn-per-transaction shown? Can customer redeem entirely in-app? Is expiry date visible? |
| **Operations** | Are points posting within SLA? Are promotional bonuses credited on time? Are manual adjustments backlogged? |
| **Communication** | Is expiry communicated early enough? Are tier changes pre-announced? Are promotional outcomes explained? |
| **Policy** | Are expiry policies regulatory or internal? Can minimum redemption thresholds be lowered? Are category exclusions competitively justified? |

## Anti-Patterns (What NOT to Conclude)
- Don't assume all "missing points" calls are system errors — many are posting-delay confusion or non-qualifying transactions
- Don't recommend eliminating expiry policies — recommend better expiry communication and prevention options
- Don't conflate earn rate complaints with system bugs — most are merchant category code misunderstandings
- Don't treat promotional offer confusion as customer error — if terms require a phone call to understand, the terms are the problem

# Payment & Transfer — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Payments, Transfers, Fund Transfer, Bill Pay, Payment Failed, Declined, Refund, ACH, Wire, P2P, Balance Transfer, Payment Due, Auto Pay.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim payment/transfer issue
- `digital_friction` — Digital barrier during payment flow
- `solution_by_technology` — Technology fix recommendations
- `solution_by_ui` — UI/UX improvements for payment flows
- `solution_by_ops` — Operational process improvements
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Payment Failed With Unclear Error
**Signal**: "payment declined", "transaction failed", "couldn't go through", "error when paying"
**Root Cause Tree**:
- Error code displayed is a generic "transaction failed" without specificity
- Customer can't distinguish between: insufficient funds, merchant restriction, card block, daily limit, risk hold
- No retry guidance (should they try again? Use different card? Wait?)
- Error doesn't tell customer WHAT to do next
**Self-Service Gap**: Does the error page offer a "Why did this fail?" explainer? Is there a one-tap retry? Can customer see their available balance and limits in context?
**Typical Volume**: 20–30% of payment calls
**Call Reduction Lever**: Specific error messages with next-step CTAs ("Your daily limit of $5,000 was reached. Resets tomorrow at midnight. [View limits]"), inline retry with alternative payment method suggestion

### Pattern 2: Transfer Limit Hit Without Visibility
**Signal**: "can't send more", "transfer limit", "exceeded limit", "why is there a limit"
**Root Cause Tree**:
- Daily/monthly/per-transaction limits not visible before initiation
- Limit hit during flow (after entering amount) instead of proactive check
- Customer doesn't know which limit applies (daily vs monthly vs per-payee)
- Limit increase process requires calling in
**Self-Service Gap**: Can customer see all their limits in one place? Can they request a temporary increase online? Are limits shown BEFORE they start the transfer?
**Typical Volume**: 10–15% of payment calls
**Call Reduction Lever**: Show "You can send up to $X today" on transfer initiation screen, allow self-service temporary limit increase for verified customers, show which specific limit was hit

### Pattern 3: Pending Transaction Confusion ("Where Is My Money?")
**Signal**: "money deducted but not received", "pending charge", "when will it post", "double charge"
**Root Cause Tree**:
- Authorization vs settlement timing not explained (2–5 business days is normal but not intuitive)
- Pending transactions shown identically to posted transactions
- Holds from gas stations, hotels, car rentals inflate apparent charges
- International transactions have longer settlement windows
**Self-Service Gap**: Does the app distinguish pending from posted? Does it explain hold amounts? Can customer see estimated settlement date?
**Typical Volume**: 15–25% of payment calls
**Call Reduction Lever**: Visual distinction for pending vs posted (greyed out, "pending" badge), estimated settlement date, hold amount explanation ("$100 hold by Shell Gas — final charge may differ"), education tooltip on first pending transaction view

### Pattern 4: Refund Timeline Not Communicated
**Signal**: "where is my refund", "merchant refunded but I don't see it", "how long does refund take"
**Root Cause Tree**:
- Merchant processed refund but bank settlement takes 3–10 business days
- No proactive notification when refund posts
- Customer can't see pending refund in transaction history
- Partial refunds confusing (different from original charge amount)
**Self-Service Gap**: Can customer see pending refunds? Is estimated arrival date shown? Is there a push notification when refund posts?
**Typical Volume**: 10–15% of payment calls
**Call Reduction Lever**: Show pending refund with estimated date, push notification on refund posting, refund tracker ("Refund from Amazon — expected by March 5")

### Pattern 5: Auto-Pay Setup / Failure
**Signal**: "auto pay didn't work", "double payment", "can't set up autopay", "autopay charged wrong amount"
**Root Cause Tree**:
- Auto-pay enrollment confirmation unclear
- Payment amount options confusing (minimum, statement balance, fixed amount, full balance)
- Schedule timing mismatch (enrolled on 15th, due date 12th, first auto-pay misses)
- Failed auto-pay notification arrives too late to manually pay before late fee
**Self-Service Gap**: Can customer see auto-pay status? Can they modify amount/date easily? Is the next auto-pay date and amount visible on dashboard?
**Typical Volume**: 5–10% of payment calls
**Call Reduction Lever**: Clear auto-pay dashboard showing next payment date + amount, 3-day advance notification ("Auto-pay of $X scheduled for March 12"), immediate notification on auto-pay failure with manual payment CTA

### Pattern 6: International / Cross-Border Transfer Issues
**Signal**: "international transfer", "exchange rate", "SWIFT fee", "money not received abroad"
**Root Cause Tree**:
- FX rates and fees not shown until after confirmation
- Correspondent bank fees deducted without explanation
- Recipient's bank details format varies by country
- Processing time not communicated (1 day domestic vs 3–5 days international)
**Self-Service Gap**: Is total cost (fee + FX markup) shown upfront? Can customer track international transfer status? Are recipient bank detail formats validated?
**Typical Volume**: 5–8% of payment calls (but high per-call value)
**Call Reduction Lever**: All-in cost calculator before confirmation, step-by-step transfer tracker with estimated arrival, country-specific recipient detail templates

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `digital_friction` and `exact_problem_statement` within the payment bucket
2. **Failure Type Segmentation**: Categorize by the 6 patterns above based on problem statement keywords
3. **Volume Impact**: Size each failure type as % of total payment calls
4. **Error Message Audit**: Look at `solution_by_ui` for specific error message improvement suggestions already in the data
5. **Cross-Reference**: Apply `apply_skill("payment_transfer", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in payment data |
|------|----------------------------------|
| **Digital** | Are error messages specific enough to self-serve? Is retry flow frictionless? Are limits visible pre-transaction? |
| **Operations** | Are settlements delayed beyond SLA? Are refunds processed within SLA? Are manual holds causing delays? |
| **Communication** | Is transaction status updated in real time? Are failure notifications timely? Are refund ETAs communicated? |
| **Policy** | Are transfer limits regulatory or internal? Can limits be adjusted per customer risk? Are cooling-off periods required by law? |

## Anti-Patterns (What NOT to Conclude)
- Don't attribute merchant-side declines to bank failures (distinguish "your bank declined" vs "merchant doesn't accept this card")
- Don't conflate pending authorizations with actual charges — pending ≠ posted
- Don't recommend removing fraud checks — recommend making them transparent
- Don't assume all "failed payment" calls are system errors — many are limit/balance issues the customer could self-diagnose with better visibility

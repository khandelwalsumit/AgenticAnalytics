# Transaction & Statement — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Transaction, Statement, Charge, Balance, Transaction History, Missing Transaction, Duplicate Charge, Statement Download, Mini Statement, Transaction Detail, Unrecognized Charge, Statement Delivery.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim transaction/statement issue
- `digital_friction` — Digital barriers to accessing transaction data
- `solution_by_ui` — UI improvements for transaction display
- `solution_by_education` — Customer education on transaction timing and formats
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Unrecognized Charge — "What Is This?"
**Signal**: "don't recognize this charge", "what is this transaction", "I didn't make this purchase", "unknown merchant"
**Root Cause Tree**:
- Merchant descriptor on statement doesn't match the store name customer knows (e.g., "SQ *COFFEE SHOP" vs "Blue Bottle Coffee")
- Parent company name used instead of brand name (e.g., "YUMBRANDS" vs "KFC")
- Online marketplaces show platform name, not individual seller
- Subscription renewals from services customer forgot they signed up for
**Self-Service Gap**: Can customer search merchant descriptor to see mapped merchant name + logo? Is there a "Don't recognize this? Tap to see details" feature? Can customer see merchant category, location, and time?
**Typical Volume**: 20–30% of transaction calls — often the largest single driver
**Call Reduction Lever**: Merchant logo + clean name mapping in transaction detail, "Is this your charge?" self-service flow with merchant details + map location, subscription labeling ("Monthly subscription — first charged Sept 2024"), digital receipt attachment when available

### Pattern 2: Missing Transaction — "Where Is My Payment?"
**Signal**: "transaction not showing", "payment missing", "deducted but not showing", "can't find my transaction"
**Root Cause Tree**:
- Authorization captured but settlement pending (transaction exists but in different section)
- Transaction posted to different account (joint account, other card)
- Transaction search is poor (can't search by amount, merchant, or date range)
- Transactions only visible for last 30/60/90 days without statement access
**Self-Service Gap**: Can customer search by amount and date? Is the pending vs posted distinction clear? Can customer view all accounts in one search? Is transaction history longer than 90 days?
**Typical Volume**: 10–15% of transaction calls
**Call Reduction Lever**: Universal transaction search (amount, merchant, date range), cross-account transaction view, "Can't find it? Try pending transactions" suggestion, 12+ month history without requiring statement download

### Pattern 3: Pending vs Posted Confusion
**Signal**: "pending charge", "when will it post", "amount changed", "hold amount different"
**Root Cause Tree**:
- Pending authorizations and posted transactions look identical in the UI
- Hold amounts (gas, hotel, car rental) differ from final charge without explanation
- Customer doesn't understand that pending = authorized, posted = final
- Some pending transactions disappear and reappear as posted with different amounts
**Self-Service Gap**: Are pending transactions visually distinct? Is "pending" explained in context? Are hold amounts annotated? Is estimated posting date shown?
**Typical Volume**: 10–15% of transaction calls
**Call Reduction Lever**: Visual distinction (grey badge, "Pending" label), tooltip explaining pending vs posted on first view, hold amount annotation ("$100 hold by Marriott — final charge may differ"), estimated posting date

### Pattern 4: Duplicate Charges
**Signal**: "charged twice", "duplicate transaction", "double charge", "two charges for same thing"
**Root Cause Tree**:
- Authorization + settlement appearing as two separate line items (perceived duplicate)
- Actual merchant double-charge (rare but happens)
- Subscription charged twice due to renewal timing
- Split transactions by merchant (e.g., tip added as separate charge)
**Self-Service Gap**: Can customer see authorization-to-settlement linkage? Is there a "Report duplicate" flow? Can customer compare timestamps and amounts to self-diagnose?
**Typical Volume**: 5–10% of transaction calls
**Call Reduction Lever**: Link authorization to its settlement in transaction view ("This pending charge settled as the $47.50 charge below"), "Report potential duplicate" one-tap flow that auto-checks for auth/settlement pairs before filing dispute

### Pattern 5: Statement Download / Delivery Issues
**Signal**: "can't download statement", "statement not available", "need statement for tax", "email statement not received"
**Root Cause Tree**:
- Statement generation delay (not available on statement date)
- Download format issues (PDF rendering, CSV not available)
- Email delivery failures (spam filter, full inbox, wrong email)
- Old statements (>12 months) not accessible digitally
- Statement date vs payment due date confusion
**Self-Service Gap**: Can customer download current and historical statements instantly? Are multiple formats available (PDF, CSV, OFX)? Can customer see statement generation status?
**Typical Volume**: 5–10% of transaction calls
**Call Reduction Lever**: Instant statement download in multiple formats, 7+ year digital statement archive, email delivery confirmation, statement-ready push notification, downloadable annual summary for tax season

### Pattern 6: Balance Discrepancy
**Signal**: "balance is wrong", "available balance different", "doesn't add up", "credit limit wrong"
**Root Cause Tree**:
- Available balance ≠ statement balance ≠ current balance (three different numbers, all "correct")
- Pending transactions reduce available balance but aren't shown in transaction list
- Credit limit changes not communicated
- Rewards/cashback credits not reflected in expected balance
**Self-Service Gap**: Is the balance breakdown explained (current balance, pending charges, available credit)? Is there a "How is my balance calculated?" explainer? Are recent credit limit changes shown?
**Typical Volume**: 5–10% of transaction calls
**Call Reduction Lever**: Balance breakdown widget ("Statement balance $1,200 + Pending charges $300 = Current balance $1,500 | Available credit: $3,500"), credit limit change notification with reason, balance reconciliation view

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `exact_problem_statement` and `digital_friction` within the transaction/statement bucket
2. **Pattern Matching**: Map top problem statements to the 6 patterns above
3. **Volume Sizing**: Calculate % of transaction bucket for each pattern
4. **UI/Findability Assessment**: Check `solution_by_ui` for transaction display improvement suggestions
5. **Cross-Reference**: Apply `apply_skill("transaction_statement", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in transaction/statement data |
|------|------------------------------------------------|
| **Digital** | Is transaction search functional? Are merchant descriptors readable? Is pending vs posted clear? Can statements be downloaded? |
| **Operations** | Are statements generated on time? Are transaction postings delayed? Is merchant descriptor data updated? |
| **Communication** | Are balance changes explained? Are statement-ready notifications sent? Are pending transaction timelines communicated? |
| **Policy** | How long are statements retained digitally? Are there regulatory requirements for statement formats? Can retention be extended? |

## Anti-Patterns (What NOT to Conclude)
- Don't assume "unrecognized charge" calls are fraud — most are merchant descriptor confusion
- Don't conflate pending authorizations with posted charges — they are different lifecycle stages
- Don't attribute merchant descriptor issues to the bank alone — descriptors are set by merchants and acquirers
- Don't recommend removing pending transactions from the view — customers need to see them, just with clear labeling

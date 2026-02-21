# Payment & Transfer Analysis Skill

## Focus Areas
- Payment failures and declined transactions
- Fund transfers (internal, external, P2P)
- Refund processing and delays
- Transaction limits and restrictions
- Payment method issues (card, UPI, net banking, wallet)

## Key Fields to Analyze
- `exact_problem_statement` — Customer's specific payment issue
- `digital_friction` — Digital channel barriers during payment
- `solution_by_technology` — Technology fixes for payment issues
- `solution_by_ui` — UI improvements for payment flows
- `call_reason` → `granular_theme_l5` — Full call reason hierarchy

## Analysis Framework

### Step 1: Categorize by Failure Type
- **Declined transactions** — insufficient funds, card blocks, risk flags
- **Processing errors** — timeout, gateway failure, network issues
- **Limit-related** — daily/monthly limits, per-transaction caps
- **Authentication failures** — OTP timeout, 3DS failure, biometric rejection
- **Beneficiary issues** — invalid account, name mismatch, IFSC errors

### Step 2: Identify Root Cause Patterns
- Is the failure at the bank's end, gateway, or app level?
- Are certain payment methods disproportionately affected?
- Is there a time-of-day or volume pattern?
- Are error messages clear enough for self-service resolution?

### Step 3: Map to Solution Channels
- **UI fixes** — better error messages, payment retry flows, limit visibility
- **Technology fixes** — gateway fallbacks, timeout handling, caching
- **Ops fixes** — manual review queues, exception handling processes
- **Education** — customer guidance on limits, alternative payment methods

### Step 4: Assess Impact
- Volume of affected transactions (% of total payment calls)
- Revenue impact (failed payments = lost revenue opportunity)
- Customer effort score (how many contacts before resolution?)
- Digital containment potential (can this be self-served?)

## Investigation Questions
1. What are the top 5 payment failure reasons by volume?
2. What percentage of payment issues are resolved on first contact?
3. Which payment methods generate the most friction calls?
4. Are payment error messages actionable for customers?
5. What is the split between reversible vs non-reversible failures?
6. How many payment issues could be prevented with better UI?
7. What is the refund processing SLA compliance rate?

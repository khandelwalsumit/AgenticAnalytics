---
name: payment_specialist
description: Deep specialist knowledge for Payments & Transfers domain — ACH rails, wire transfers, payment holds, Reg E, faster payments, and dispute workflows.
---

<skill name="payment_specialist">

# Payments & Transfers: Specialist Domain Knowledge

## Core Payment Rails and Their Failure Modes

### ACH (Automated Clearing House)
- **Processing windows**: ACH batches settle in T+1 (standard) or same-day for SAMEDAY ACH. Customers frequently call when they don't understand why a transfer initiated at 5PM won't reflect until the next business day.
- **Return codes**: R01 (insufficient funds), R02 (account closed), R03 (no account/unable to locate), R10 (customer advises unauthorised) are the most common. Each triggers a specific customer-visible message.
- **Holds on incoming ACH**: New payee relationships may trigger a 3–5 business day hold even on ACH credit. Customers mistake this for a bank error.
- **Prenote requirements**: Some institutions require a zero-dollar prenote before first ACH debit. Customers get confused when the first real debit is delayed.

### Wire Transfers
- **Domestic wires**: Fed same-day settlement if submitted before cutoff (typically 5PM ET). Late submissions hold overnight — a frequent source of "my wire didn't post" calls.
- **International SWIFT wires**: Multi-correspondent bank routing means 1–5 business day settlement. Customers with urgent cross-border needs often don't understand this.
- **IBAN vs. SWIFT codes**: Confusion between IBAN (account identifier) and SWIFT/BIC (bank identifier) causes wire rejections. Common in EU-destined transfers.
- **OFAC screening holds**: Payments to sanctioned countries or flagged entities trigger automatic holds. Customers rarely understand why their wire is stuck.
- **Wire fees**: Outgoing domestic wire: typically $25–$35. Outgoing international: $40–$50. Customers with waiver eligibility (premium accounts) frequently call because fees were not auto-waived.

### Zelle / Real-Time Payments (RTP)
- **Irreversibility**: Zelle and RTP payments are final and instant. Customers calling to "cancel" a Zelle payment after sending to the wrong number have no recourse except recipient cooperation.
- **Enrolment delays**: New Zelle enrolment via mobile number/email can take up to 3 days. Customers expect instant activation.
- **Velocity limits**: Zelle daily/weekly limits (typically $2,500/day) cause friction for customers trying to send large amounts. Limits differ by relationship tier.

## Regulation E: The Friction Multiplier

Reg E covers consumer electronic fund transfers. Non-compliance generates regulatory risk; over-compliance generates unnecessary friction.

- **10-business-day provisional credit**: For unresolved disputes, the bank must credit within 10 business days. Customers who don't receive this call repeatedly.
- **Error resolution window**: Customers have 60 days from statement date to report errors. After that, liability shifts. Customers calling outside this window often escalate to supervisors.
- **Investigation timeline**: Bank has 45 days (90 for POS international or new accounts) to resolve. Customers expect faster resolution and call repeatedly during this window.
- **Dispute vs. fraud**: Customers conflate "I didn't authorise this" (fraud/Reg E) with "I changed my mind" (dispute, not covered by Reg E). This distinction drives the call reason and resolution path.

## Payment Holds: The #1 Call Driver in Payments

### Hold Types
1. **New payee hold**: First transfer to a new external account held 3–5 business days
2. **Large dollar hold**: Transfers above threshold (often $10K+) require additional verification
3. **Fraud alert hold**: Behavioural scoring triggers a hold; customer must call to verify
4. **OFAC/sanctions hold**: Automatic hold; cannot be released without Compliance clearance
5. **Insufficient funds hold**: Pending ACH debit where real-time balance is insufficient

### Hold Reduction Levers
- Proactive SMS/push notification at hold initiation (reduces "where's my money" calls by ~30%)
- In-app hold status page with estimated release date
- One-click reversal option for new-payee holds with customer confirmation
- Raising hold thresholds for established customers (>12 months, no fraud history)

## Fraud and Dispute Workflows in Payments

### First-Party vs. Third-Party Fraud
- **First-party**: Customer initiated the payment but claims they didn't (buyer's remorse or friendly fraud). These are the most complex to resolve and cannot be covered under Reg E if the customer authorised the transaction.
- **Third-party**: Genuine unauthorised access. Covered by Reg E. Bank must provisionally credit within 10 days.

### Dispute Triggers Specific to Payments
- Duplicate payment: Same amount, same payee, within 24 hours — customers call immediately
- Wrong amount: Payee received different amount than intended
- Wrong payee: ACH routed to wrong account (routing/account number mismatch)
- Payment reversal not processed: Payee claims to have returned funds but customer hasn't received credit

## Common Self-Service Friction Points (Digital Dimension)

1. **Payment status tracking**: Customers cannot see detailed payment status in-app (e.g., "In transit via ACH, expected credit 2PM tomorrow"). They call to check status.
2. **Scheduled payment modification**: After a future-dated payment is set, customers cannot easily modify the amount or date without cancelling and re-initiating.
3. **Payee verification**: No confirmation that the payee account number is valid before submitting. Customers discover errors post-submission.
4. **International beneficiary entry**: Complex form with country-specific fields (IBAN, SWIFT, sort code, BSB). Error messages are not specific enough to guide corrections.
5. **Payment cutoff visibility**: Customers don't know they've missed the wire cutoff until the next day.

## Proactive Communication Opportunities

| Payment Event | Optimal Notification Channel | Timing |
|---|---|---|
| Payment initiated | Push + email | At initiation |
| Hold placed | Push + SMS | Within 5 minutes |
| Payment cleared | Push | At settlement |
| Wire cutoff approaching | Push | 2 hours before cutoff |
| Dispute case updated | Push + email | Within 1 hour of update |
| Provisional credit applied | Push + email | At credit |

## Key Metrics for Payments Friction Sizing

- **Hold rate**: % of transfers that trigger any hold (benchmark: <8% for established customers)
- **Dispute rate**: % of payments disputed within 60 days (benchmark: <0.5%)
- **STP rate (Straight-Through Processing)**: % of payments that process without any manual intervention (benchmark: >95% for domestic ACH)
- **First-call resolution on payment status**: % of payment status calls resolved without escalation (benchmark: >85%)

</skill>

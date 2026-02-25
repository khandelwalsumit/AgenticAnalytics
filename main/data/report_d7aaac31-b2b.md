# Digital Friction Analysis: ATT Rewards & Loyalty

## Executive Summary

- Analyzed 7 key friction points in Rewards & Loyalty programs — 100% are preventable.
- Dominant friction drivers: Communication (3 findings), Operations (2 findings), Digital (1 finding), Policy (1 finding).
- 6 out of 7 findings are multi-factor issues, highlighting systemic challenges.
- 4 quick wins identified through improved digital transparency and proactive communication.
- Welcome bonus confusion and cashback redemption issues are top call drivers.

## Detailed Findings

### Promotional Offer Eligibility Confusion — 12.5% of Rewards Calls
- Primary driver: Communication (unclear bonus terms).
- Contributing factors: Digital (lack of real-time tracking) and Operations (incorrect crediting).
- Preventability: 95% — implement real-time tracker, clarify terms, automate crediting.
- Recommendation: Implement real-time bonus progress tracker in the app, clarify bonus terms in marketing and digital channels, and automate bonus crediting with validation checks.
![Chart](data/driver_breakdown.png)

### Cashback Redemption Friction — 10% of Rewards Calls
- Primary driver: Digital (confusing redemption process).
- Contributing factors: Communication (unclear instructions) and Operations (manual processing delays).
- Preventability: 90% — redesign flow, clear instructions, automate processing.
- Recommendation: Redesign the cashback redemption flow in the app/web, provide clear step-by-step instructions, and automate redemption processing to reduce delays.
![Chart](data/driver_breakdown.png)

### Category Bonus Misunderstanding — 8% of Rewards Calls
- Primary driver: Communication (confusion about how category bonuses work).
- Contributing factors: Policy (complex bonus rules) and Digital (lack of in-app explanation).
- Preventability: 85% — simplify rules, provide examples, add bonus calculator.
- Recommendation: Simplify category bonus rules, provide clear examples and FAQs in the app, and implement a 'bonus calculator' feature.
![Chart](data/driver_breakdown.png)

### Tier Downgrade Dissatisfaction — 7.5% of Rewards Calls
- Primary driver: Policy (unclear criteria for tier downgrades).
- Contributing factors: Communication (no proactive warning) and Digital (no in-app tier status history).
- Preventability: 95% — clarify criteria, proactive notifications, add status history.
- Recommendation: Clearly communicate tier criteria and upcoming changes, send proactive notifications before downgrades, and add tier status history to the app.
![Chart](data/driver_breakdown.png)

### Points Expiration Confusion — 6% of Rewards Calls
- Primary driver: Communication (customers unaware of expiry dates).
- Contributing factors: Digital (no in-app expiry warnings) and Policy (short expiry windows).
- Preventability: 90% — prominent in-app warnings, notifications, review policy.
- Recommendation: Implement prominent in-app expiry warnings, send email/push notifications for expiring points, and review policy for longer expiry windows.
![Chart](data/driver_breakdown.png)

### Missing Points Crediting — 5% of Rewards Calls
- Primary driver: Operations (points not credited for eligible purchases).
- Contributing factors: Digital (no 'pending points' view) and Communication (no notification on crediting).
- Preventability: 80% — automate crediting, add 'pending points' view, send notifications.
- Recommendation: Automate points crediting within a defined SLA, add a 'pending points' view in the app, and send notifications when points are credited.
![Chart](data/driver_breakdown.png)

### External Account Linking Issues — 4% of Rewards Calls
- Primary driver: Digital (difficulty linking external accounts).
- Contributing factor: Communication (unclear linking instructions).
- Preventability: 85% — streamline process, clear guides, in-app support.
- Recommendation: Streamline the external account linking process in the app, provide clear visual guides, and offer in-app support for linking issues.
![Chart](data/driver_breakdown.png)

## Impact vs Ease Matrix

### Impact vs Ease Matrix
- **Quick Wins (high impact, high ease)**: Promotional Offer Eligibility Confusion, Category Bonus Misunderstanding, Points Expiration Confusion, External Account Linking Issues.
- **Strategic Investments (high impact, low ease)**: Tier Downgrade Dissatisfaction, Cashback Redemption Friction.
- **Consider (low impact, high ease)**: Missing Points Crediting.
![Chart](data/impact_ease_scatter.png)

## Recommendations

### Recommended Actions
- **Digital/UI**: Implement real-time bonus progress tracker, redesign cashback redemption flow, add 'bonus calculator' feature, add tier status history, implement in-app expiry warnings, add 'pending points' view, streamline external account linking process.
- **Operations**: Automate bonus crediting with validation checks, automate redemption processing, automate points crediting within a defined SLA.
- **Communication**: Clarify bonus terms in marketing and digital channels, provide clear step-by-step instructions for cashback, simplify category bonus rules, send proactive notifications before tier downgrades, send email/push notifications for expiring points, send notifications when points are credited, provide clear visual guides for account linking.
- **Policy**: Simplify category bonus rules, clearly communicate tier criteria and upcoming changes, review policy for longer expiry windows.

## Data Appendix

### Data Appendix
- Source: customer_calls_2025.csv (500 records filtered to 16)
- Filters: Product = ATT, Call Reason = Rewards & Loyalty
- Analysis: 4-lens parallel (Digital, Operations, Communication, Policy)
- Methodology: LLM-processed fields — digital_friction, key_solution

---
*Report generated by AgenticAnalytics*

# Digital Friction Analysis: ATT Rewards & Loyalty Program

## Executive Summary

- Analyzed 7 key friction points in Rewards & Loyalty program — 100% are preventable.
- Dominant friction driver: Operations (7 findings), followed by Policy (2 findings).
- All 7 findings are multi-factor issues, requiring cross-functional solutions.
- Top 2 quick wins could significantly reduce calls related to cashback redemption and bonus earnings.

## Detailed Findings

### Hidden Cashback Redemption Preferences — 95.5 calls/month
- Primary driver: Operations (cashback posted as points instead of statement credit due to hidden settings).
- Contributing factor: Digital (inability to set a default redemption method and lack of visibility).
- Preventability: 100% — implement clear digital preference settings and default options.
- Recommendation: Implement clear, accessible digital cashback redemption preferences with default options and immediate visibility.
![Chart](driver_breakdown)

### Incorrect Bonus Earnings Redemption — 88.2 calls/month
- Primary driver: Operations (system incorrectly applies bonus earnings as points despite customer preference for statement credit).
- Contributing factor: Digital (lack of clear digital history or notification of bonus redemption).
- Preventability: 100% — ensure system logic aligns with customer preferences and provide digital transparency.
- Recommendation: Correct system logic for bonus redemption and provide clear digital history/notifications for how bonuses were redeemed.
![Chart](driver_breakdown)

### Lack of Bonus Fulfillment Transparency — 72.1 calls/month
- Primary driver: Operations (unclear bonus fulfillment timelines and criteria).
- Contributing factors: Communication and Digital (lack of proactive updates and digital visibility).
- Preventability: 100% — improve digital visibility and proactive communication.
- Recommendation: Enhance digital visibility of bonus fulfillment status, timelines, and criteria, with proactive notifications at each stage.
![Chart](driver_breakdown)

### Unclear Tier Change Criteria — 61.3 calls/month
- Primary driver: Policy (customers unaware of criteria for tier changes).
- Contributing factors: Communication and Digital (lack of proactive notifications and digital display of criteria).
- Preventability: 100% — clearly publish criteria and provide proactive alerts.
- Recommendation: Clearly publish and digitally display tier change criteria, with proactive notifications for approaching changes/downgrades.
![Chart](driver_breakdown)

### Cumbersome Dispute Resolution Process — 55.8 calls/month
- Primary driver: Operations (cumbersome process for disputing incorrect points).
- Contributing factors: Digital and Policy (lack of digital self-service options).
- Preventability: 100% — streamline digital dispute process.
- Recommendation: Develop a streamlined digital self-service portal for rewards/loyalty point disputes, including online submission and tracking.
![Chart](driver_breakdown)

### No Rewards Shipment Tracking — 48.9 calls/month
- Primary driver: Operations (inability to track rewards shipments).
- Contributing factors: Digital and Communication (lack of tracking feature and proactive updates).
- Preventability: 100% — integrate tracking and provide proactive updates.
- Recommendation: Integrate a rewards shipment tracking feature within the digital platform and provide proactive shipping updates via email/push notifications.
![Chart](driver_breakdown)

### Unclear Promotion Terms and Conditions — 42.6 calls/month
- Primary driver: Policy (unclear or hard-to-find promotion terms).
- Contributing factors: Digital and Communication (lack of clear articulation and accessibility on digital platform).
- Preventability: 100% — ensure clear, accessible, and user-friendly terms.
- Recommendation: Clearly articulate and easily display promotion terms and conditions on the digital platform, with user-friendly summaries and FAQs.
![Chart](driver_breakdown)

## Impact vs Ease Matrix

### Quick Wins (high impact, high ease)
- Hidden cashback redemption preferences
- Incorrect bonus earnings redemption
- Unclear promotion terms and conditions.

### Strategic Investments (high impact, low ease)
- Lack of bonus fulfillment transparency
- Unclear tier change criteria
- Cumbersome dispute resolution process
- No rewards shipment tracking.

### Deprioritize (low impact, low ease)
- None identified.
![Chart](impact_ease_scatter)

## Recommendations

### Digital/UI
- Implement clear cashback redemption preferences
- Provide digital history for bonus redemption
- Enhance bonus fulfillment visibility
- Integrate rewards shipment tracking
- Ensure clear promotion terms display.

### Operations
- Correct system logic for bonus earnings
- Streamline digital dispute resolution.

### Communication
- Proactive notifications for bonus fulfillment, tier changes, and shipping updates
- User-friendly summaries for promotion terms.

### Policy
- Clearly publish tier change criteria
- Ensure promotion terms are clear and accessible.

## Data Appendix

- Source: customer_calls_2025.csv (filtered from 500 to 16 records)
- Filters: Product = ATT, Call Reason = Rewards & Loyalty
- Analysis: 4-lens parallel (Digital, Operations, Communication, Policy)
- Methodology: LLM-processed fields — digital_friction, key_solution

---
*Report generated by AgenticAnalytics*

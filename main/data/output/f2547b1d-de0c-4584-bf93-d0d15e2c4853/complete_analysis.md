# Digital Friction Analysis: ATT Rewards & Loyalty

This analysis focuses on 16 ATT customer calls related to Rewards & Loyalty, identifying 7 distinct digital friction points. The primary issue, affecting 43.75% of these calls, is customers' inability to change cashback redemption preferences digitally. These issues are highly preventable through targeted digital product enhancements.

### Top 3 Critical Pain Points

**1. Cashback Redemption Preference Confusion**
- Customers cannot find where to change their cashback redemption preference from points to statement credit, leading to frustration when cashback is automatically posted as points.
- *Example:* Pattern: 43.75% of rewards calls (7 calls) are due to cashback being posted as points instead of statement credit, with no digital option to change this preference.
- **Call volume:** 7 calls | 43.75% of total
- **Recommended:** Add a prominent 'Redemption Preferences' section in the rewards dashboard.

**2. Incorrect Category Bonus Application**
- Customers are not receiving expected category bonuses (e.g., 5x gas) due to merchant category code (MCC) mismatches, where a gas station is coded as a 'convenience store', and there's no digital explanation.
- *Example:* Pattern: 18.75% of rewards calls (3 calls) are from customers not receiving 5x gas category bonus due to merchant coding as 'convenience store'.
- **Call volume:** 3 calls | 18.75% of total
- **Recommended:** Implement a transaction detail view that clearly displays the merchant category code (MCC) and the associated earn rate for each transaction.

**3. Partial Welcome Bonus Receipt**
- Customers are receiving partial welcome bonuses despite believing they met all spend requirements, indicating a lack of clear progress tracking or visibility into specific offer terms.
- *Example:* Pattern: 12.5% of rewards calls (2 calls) are from customers who received only 40,000 points instead of the expected 60,000 welcome bonus.
- **Call volume:** 2 calls | 12.5% of total
- **Recommended:** Introduce an 'Offer Tracker' in the rewards section, showing progress towards welcome bonuses.

### Quick Wins

| Solution | Theme | Impact |
|----------|-------|--------|
| Add a prominent 'Redemption Preferences' section in the rewards dashboard. | ATT_Rewards & Loyalty | **~7 calls (43.75%)** |
| Introduce an 'Offer Tracker' for welcome bonuses. | ATT_Rewards & Loyalty | **~2 calls (12.5%)** |
| Implement proactive tier downgrade notifications. | ATT_Rewards & Loyalty | **~1 calls (6.25%)** |

---

## Impact vs Ease Prioritization

| Theme | Volume | Top 3 Problems | Solutions | Ease | Impact | Priority |
|-------|--------|-----------------|-----------|------|--------|----------|
| **ATT_Rewards & Loyalty** | **16 calls** | 1. Cashback posted as points, no preference change (7 calls) 2. Incorrect gas category bonus (3 calls) 3. Partial welcome bonus received (2 calls) | 1. Add 'Redemption Preferences' section 2. Display MCC and earn rate in transaction details 3. Introduce 'Offer Tracker' | 7/10 | 9/10 | **8.2** |

---

## Recommended Actions

### Digital/UX
1. **Add a prominent 'Redemption Preferences' section in the rewards dashboard allowing customers to easily select their preferred cashback redemption method (points vs. statement credit).** — ATT_Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Implement a transaction detail view that clearly displays the merchant category code (MCC) and the associated earn rate for each transaction, along with an explainer for how MCCs are determined.** — ATT_Rewards & Loyalty — Reduces ~3 calls (18.75%)
3. **Introduce an 'Offer Tracker' in the rewards section, showing progress towards welcome bonuses, clearly outlining all qualifying criteria, and providing a detailed breakdown of earned points.** — ATT_Rewards & Loyalty — Reduces ~2 calls (12.5%)
4. **Implement proactive in-app notifications and email alerts for upcoming tier downgrades (e.g., 60 and 30 days prior), clearly stating the reason for downgrade and the impact on benefits.** — ATT_Rewards & Loyalty — Reduces ~1 calls (6.25%)
5. **Add an 'Upcoming & Past Bonuses' section in the rewards dashboard, showing expected anniversary bonus dates and status (pending/posted) with a clear timeline.** — ATT_Rewards & Loyalty — Reduces ~1 calls (6.25%)
6. **Enhance transaction details to show the applied earn rate and the reason for it (e.g., '1x base points - merchant coded as general retail' or '3x grocery bonus - $X remaining on qualifying spend').** — ATT_Rewards & Loyalty — Reduces ~1 calls (6.25%)
7. **Implement a 'Point Transfer History' section in the rewards dashboard, showing the status of each transfer (pending/completed), the date, and an estimated arrival time for partner points.** — ATT_Rewards & Loyalty — Reduces ~1 calls (6.25%)

### Operations

### Communication

### Policy


---

## ATT_Rewards & Loyalty

> **Priority:** 8.2/10 | **Ease:** 7/10 | **Impact:** 9/10
> **Volume:** 16 calls | 3.2% of total

### Drivers

| Driver | Call Count | % Contribution | Type | Dimension |
|--------|-----------|----------------|------|-----------|
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | **7** | 43.75% | Primary | digital |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | **3** | 18.75% | Secondary | digital |
| Customer signed up for a 60,000 point welcome bonus offer but only received 40,000 after meeting the spend requirement. | **2** | 12.5% | Secondary | digital |
| Customer was downgraded from Platinum to Gold tier without any warning or notification. Lost access to airport lounge benefit. | **1** | 6.25% | Secondary | digital |
| Customer's anniversary bonus points from last year haven't been credited. Account anniversary was 3 months ago. | **1** | 6.25% | Secondary | digital |
| Customer made $300 in grocery purchases last month but points for the 3x category bonus weren't credited. Regular 1x points were applied. | **1** | 6.25% | Secondary | digital |
| Customer transferred points to airline partner 5 days ago but they still don't appear in the airline frequent flyer account. | **1** | 6.25% | Secondary | digital |

### Recommended Solutions
- **Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. → Add a prominent 'Redemption Preferences' section in the rewards dashboard allowing customers to easily select their preferred cashback redemption method (points vs. statement credit).** — Expected reduction: ~7 calls
- **Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. → Implement a transaction detail view that clearly displays the merchant category code (MCC) and the associated earn rate for each transaction, along with an explainer for how MCCs are determined.** — Expected reduction: ~3 calls
- **Customer signed up for a 60,000 point welcome bonus offer but only received 40,000 after meeting the spend requirement. → Introduce an 'Offer Tracker' in the rewards section, showing progress towards welcome bonuses, clearly outlining all qualifying criteria, and providing a detailed breakdown of earned points.** — Expected reduction: ~2 calls
- **Customer was downgraded from Platinum to Gold tier without any warning or notification. Lost access to airport lounge benefit. → Implement proactive in-app notifications and email alerts for upcoming tier downgrades (e.g., 60 and 30 days prior), clearly stating the reason for downgrade and the impact on benefits.** — Expected reduction: ~1 calls
- **Customer's anniversary bonus points from last year haven't been credited. Account anniversary was 3 months ago. → Add an 'Upcoming & Past Bonuses' section in the rewards dashboard, showing expected anniversary bonus dates and status (pending/posted) with a clear timeline.** — Expected reduction: ~1 calls
- **Customer made $300 in grocery purchases last month but points for the 3x category bonus weren't credited. Regular 1x points were applied. → Enhance transaction details to show the applied earn rate and the reason for it (e.g., '1x base points - merchant coded as general retail' or '3x grocery bonus - $X remaining on qualifying spend').** — Expected reduction: ~1 calls
- **Customer transferred points to airline partner 5 days ago but they still don't appear in the airline frequent flyer account. → Implement a 'Point Transfer History' section in the rewards dashboard, showing the status of each transfer (pending/completed), the date, and an estimated arrival time for partner points.** — Expected reduction: ~1 calls

---

---

## Appendix: Analysis Pipeline Trace

### Narrative Agent Output
Summary of what the narrative agent produced: Report plan with 4 sections: Executive Summary, Impact vs Ease Prioritization, Recommended Actions by Dimension, and ATT_Rewards & Loyalty — Detailed Analysis.

### Synthesizer Agent Output
Summary of theme aggregation: 1 themes, 16 total calls, 7 findings

### Individual Agent Outputs
#### Digital Friction Agent
Summary: 7 buckets analyzed, 7 findings, 16 total calls

#### Operations Agent
Summary: 0 buckets analyzed, 0 findings, 0 total calls

#### Communication Agent
Summary: 0 buckets analyzed, 0 findings, 0 total calls

#### Policy Agent
Summary: 0 buckets analyzed, 0 findings, 0 total calls


---
*Report generated by AgenticAnalytics*

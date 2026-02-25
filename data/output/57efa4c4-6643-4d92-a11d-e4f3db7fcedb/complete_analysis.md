# Digital Friction Analysis: Rewards & Loyalty

## Executive Summary

This analysis focuses on 16 ATT customer calls related to Rewards & Loyalty programs, identified through specific product and call reason filters. The findings highlight critical friction points impacting customer satisfaction and driving call volume.

### Top 3 Critical Pain Points

1. **Cashback Redemption Preference Confusion**
- Customers are experiencing friction due to cashback being posted as points instead of statement credit, with no clear or intuitive self-service option to manage their redemption preference.
- *Example:* 7 calls (43.75% of total volume) specifically mention cashback posted as points instead of statement credit, with no clear option to change this preference.
- **Call volume:** 7 calls | 43.75% of total
- **Recommended:** Implement a clear, easily discoverable self-service option within the rewards dashboard or account settings for customers to manage their cashback redemption preference (points vs. statement credit).

2. **Incorrect Category Bonus Application**
- Customers are not receiving expected category bonuses (e.g., gas, grocery) because merchant category codes (MCCs) do not align with their purchase expectations, leading to frustration and calls.
- *Example:* 4 calls (25.0% of total volume) highlight issues where purchases at gas stations or grocery stores did not receive the advertised bonus due to MCC mismatches.
- **Call volume:** 4 calls | 25.0% of total
- **Recommended:** Enhance transparency by displaying merchant category codes (MCCs) and their corresponding earn rates for each transaction in the activity feed, along with a tool to check MCC before purchase or a 'dispute category' option.

3. **Welcome Bonus Discrepancies**
- There is a discrepancy between advertised welcome bonus points and the actual points credited after customers meet spend requirements, causing confusion and dissatisfaction.
- *Example:* 2 calls (12.5% of total volume) report instances where the credited welcome bonus did not match the advertised amount after meeting spend requirements.
- **Call volume:** 2 calls | 12.5% of total
- **Recommended:** Develop an in-app offer tracker that visually displays progress towards meeting bonus requirements and ensures the bonus crediting system accurately applies the promised amount upon meeting criteria.

### Quick Wins

| Solution | Theme | Impact |
|----------|-------|--------|
| Add a prominent and intuitive option in the rewards dashboard or account settings for customers to easily switch their cashback redemption preference between points and statement credit. | Rewards & Loyalty | **~7 calls (43.75%)** |
| Implement a robust notification system for tier changes, providing advance warnings (e.g., 60-90 days) via in-app alerts and email. | Rewards & Loyalty | **~1 calls (6.25%)** |
| Create a 'My Offers' section in the app with a progress bar for each active bonus offer. | Rewards & Loyalty | **~2 calls (12.5%)** |

---

## Impact vs Ease Prioritization

| Theme | Volume | Top 3 Problems | Solutions | Ease | Impact | Priority |
|-------|--------|-----------------|-----------|------|--------|----------|
| **Rewards & Loyalty** | **16 calls** | 1. Cashback redemption preference (7 calls) 2. Incorrect category bonus (4 calls) 3. Welcome bonus discrepancies (2 calls) | 1. Provide clear option to change cashback preference 2. Display MCCs and earn rates 3. In-app offer tracker | 7.0/10 | 8.0/10 | **7.6** |

![impact_ease_scatter](D:\Workspace\AgenticAnalytics\data\tmp\57efa4c4-6643-4d92-a11d-e4f3db7fcedb\impact_ease_scatter.png)

---

## Recommended Actions

### Digital/UX
1. **Provide clear, easily discoverable option to change cashback redemption preference (points vs. statement credit) in the rewards dashboard or account settings.** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Display merchant category code (MCC) for each transaction and explain how it maps to bonus categories. Provide a tool to check MCC before purchase or a 'dispute category' option.** — Rewards & Loyalty — Reduces ~4 calls (25.0%)
3. **Develop an in-app offer tracker that visually displays progress towards meeting bonus requirements.** — Rewards & Loyalty — Reduces ~2 calls (12.5%)
4. **Implement a proactive notification system for tier changes, providing customers with ample advance notice (e.g., 60+ days) before any downgrade takes effect, via in-app alerts and email.** — Rewards & Loyalty — Reduces ~1 calls (6.25%)
5. **Create a 'Pending Rewards' section in the rewards dashboard to show expected bonus points with their estimated posting dates.** — Rewards & Loyalty — Reduces ~1 calls (6.25%)
6. **Implement a points transfer tracker in the app, showing the status and estimated completion time for transfers to airline/hotel partners.** — Rewards & Loyalty — Reduces ~1 calls (6.25%)
7. **Display the specific earn rate applied to each transaction in the transaction history, along with the merchant category code, and provide an explainer for category mapping.** — Rewards & Loyalty — Reduces ~1 calls (6.25%)

### Operations
1. **Implement a self-service option for customers to manage their cashback redemption preference (points vs. statement credit) within the app/online portal.** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Provide transparency on merchant category codes (MCCs) and their mapping to bonus categories. Implement a feature to show transaction MCC and corresponding earn rate.** — Rewards & Loyalty — Reduces ~3 calls (18.75%)

### Communication
1. **Provide clear onboarding communication about cashback redemption preferences and an easily accessible in-app setting to manage them.** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Implement in-app explanations of merchant category codes and how they map to bonus categories, visible at the transaction level.** — Rewards & Loyalty — Reduces ~3 calls (18.75%)

### Policy
1. **Implement a clear self-service option in the app/web to select and change default cashback redemption preference (points vs. statement credit).** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Review and potentially broaden merchant category code (MCC) mapping for bonus categories (e.g., include common gas station convenience stores under 'gas'). Provide in-app transparency on MCCs.** — Rewards & Loyalty — Reduces ~3 calls (18.75%)

---

## Rewards & Loyalty

> **Priority:** 7.6/10 | **Ease:** 7.0/10 | **Impact:** 8.0/10
> **Volume:** 16 calls | 3.2% of total

### Drivers

| Driver | Call Count | % Contribution | Type | Dimension |
|--------|-----------|----------------|------|-----------|
| Cashback posted as points instead of statement credit; inability to change redemption preference. | **7** | 43.75% | Primary | digital |
| Cashback posted as points instead of statement credit; inability to change redemption preference. | **7** | 43.75% | Primary | operations |
| Cashback posted as points instead of statement credit, redemption preference unclear | **7** | 43.75% | Primary | communication |
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | **7** | 43.75% | Primary | policy |
| Incorrect category bonus due to merchant category code (MCC) mismatch (e.g., gas station coded as convenience store, grocery purchases). | **4** | 25.0% | Secondary | digital |
| Incorrect category bonus due to merchant category code (MCC) mismatch (e.g., gas station coded as convenience store). | **3** | 18.75% | Secondary | operations |
| Category bonus not applied due to merchant coding (e.g., gas station as convenience store) | **3** | 18.75% | Secondary | communication |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | **3** | 18.75% | Secondary | policy |

### Recommended Solutions
- **Cashback posted as points instead of statement credit; inability to change redemption preference. → Provide clear, easily discoverable option to change cashback redemption preference (points vs. statement credit) in the rewards dashboard or account settings.** — Expected reduction: ~7 calls
- **Cashback posted as points instead of statement credit; inability to change redemption preference. → Implement a self-service option for customers to manage their cashback redemption preference (points vs. statement credit) within the app/online portal.** — Expected reduction: ~7 calls
- **Cashback posted as points instead of statement credit, redemption preference unclear → Provide clear onboarding communication about cashback redemption preferences and an easily accessible in-app setting to manage them.** — Expected reduction: ~7 calls
- **Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. → Implement a clear self-service option in the app/web to select and change default cashback redemption preference (points vs. statement credit).** — Expected reduction: ~7 calls
- **Incorrect category bonus due to merchant category code (MCC) mismatch (e.g., gas station coded as convenience store, grocery purchases). → Display merchant category code (MCC) for each transaction and explain how it maps to bonus categories. Provide a tool to check MCC before purchase or a 'dispute category' option.** — Expected reduction: ~4 calls
- **Incorrect category bonus due to merchant category code (MCC) mismatch (e.g., gas station coded as convenience store). → Provide transparency on merchant category codes (MCCs) and their mapping to bonus categories. Implement a feature to show transaction MCC and corresponding earn rate.** — Expected reduction: ~3 calls
- **Category bonus not applied due to merchant coding (e.g., gas station as convenience store) → Implement in-app explanations of merchant category codes and how they map to bonus categories, visible at the transaction level.** — Expected reduction: ~3 calls
- **Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. → Review and potentially broaden merchant category code (MCC) mapping for bonus categories (e.g., include common gas station convenience stores under 'gas'). Provide in-app transparency on MCCs.** — Expected reduction: ~3 calls

![friction_distribution](D:\Workspace\AgenticAnalytics\data\tmp\57efa4c4-6643-4d92-a11d-e4f3db7fcedb\friction_distribution.png)

---

---

## Appendix: Analysis Pipeline Trace

### Narrative Agent Output
- Generated a report plan with 4 sections: Executive Summary, Impact vs Ease Prioritization, Recommended Actions by Dimension, and Rewards & Loyalty — Detailed Analysis.

### Synthesizer Agent Output
- 1 themes aggregated.
- 16 total calls analyzed.
- 8 findings identified.

### Individual Agent Outputs
#### Digital Friction Agent
- Summary: 1 buckets analyzed, 7 findings, 16 total calls

#### Operations Agent
- Summary: 1 buckets analyzed, 2 findings, 10 total calls

#### Communication Agent
- Summary: 1 buckets analyzed, 2 findings, 10 total calls

#### Policy Agent
- Summary: 1 buckets analyzed, 2 findings, 10 total calls

---
*Report generated by AgenticAnalytics*

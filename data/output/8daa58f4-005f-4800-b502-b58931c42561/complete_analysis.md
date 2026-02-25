<!-- SLIDE: executive_summary | layout: title_impact | title: "16 Calls, 100% Preventable: Fixing Self-Service Failures in ATT's Rewards Program" -->

# 16 Calls, 100% Preventable: Fixing Self-Service Failures in ATT's Rewards Program

Analysis of 16 customer calls for ATT's Rewards & Loyalty program reveals that 100% of this call volume is driven by preventable friction in the digital experience and operational backend.

---

<!-- SLIDE: executive_summary | layout: callout_stat | title: "The Situation" -->

## The Situation

This analysis covers 16 customer support calls filtered for the "ATT" product line where the primary call reasons were "Rewards & Loyalty" or "Products & Offers". The findings represent a targeted look at high-friction customer journeys within the loyalty program.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 1: Redemption Failures Drive 7 Calls" -->

## Pain Point 1: Redemption Failures Drive 7 Calls

**What's happening:** Customers expecting cashback rewards are receiving points instead and are unable to find or change their redemption preference in the app or website, forcing them to call.
**The evidence:** 7 separate customers called because the self-service path to manage redemption preferences is either missing, broken, or too difficult to find.
**Call volume:** 7 calls | 43.75% of total
**The fix:** Implement a clear, easily discoverable self-service 'Redemption Preferences' section in the rewards dashboard.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 2: Incorrect Bonuses Drive 4 Calls" -->

## Pain Point 2: Incorrect Bonuses Drive 4 Calls

**What's happening:** Customers are not receiving expected category bonuses because of how merchants are coded in the backend system, leading to confusion and a sense of being short-changed.
**The evidence:** 4 customers called after noticing their purchases at locations like gas stations were miscoded as convenience stores, making them ineligible for the correct bonus multiplier.
**Call volume:** 4 calls | 25.0% of total
**The fix:** Display the merchant category code (MCC) for each transaction and provide an in-app diagnostic tool to explain why a specific bonus was or was not applied.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 3: Missing Promotions Drive 3 Calls" -->

## Pain Point 3: Missing Promotions Drive 3 Calls

**What's happening:** Welcome and anniversary bonuses are not being credited correctly or on time, forcing customers to call and manually request the points they were promised.
**The evidence:** 3 customers called because their promotional bonuses were either partially paid or completely missing long after the qualifying conditions were met.
**Call volume:** 3 calls | 18.75% of total
**The fix:** Implement an in-app offer and bonus tracker showing progress toward spend requirements and a clear "Pending Bonuses" section with estimated posting dates.

---

<!-- SLIDE: quick_wins | layout: action_list | title: "Start Monday: 2 Quick Wins" -->

## Start Monday: 2 Quick Wins

| Action | Theme | Resolves | Why It's Fast |
|--------|-------|----------|---------------|
| Build a clear 'Redemption Preferences' self-service UI | Rewards & Loyalty | ~7 calls (43.75%) | This is a front-end change that clarifies an existing, but hidden, backend process. |
| Send 60-day advance notifications for tier downgrades | Rewards & Loyalty | ~1 call (6.25%) | Utilizes existing email/push notification systems to deliver a new, templated message. |

---

<!-- SLIDE: matrix | layout: section_divider | title: "Where to Act First" -->

# Where to Act First

Not all problems are equal. Not all fixes are equal. This matrix surfaces where limited effort yields the greatest call deflection.

---

<!-- SLIDE: matrix | layout: table_full | title: "Impact vs. Ease: Full Prioritization Matrix" -->

## Impact vs. Ease: Prioritization Matrix

| Theme | Volume (calls) | Top 3 Problems | Recommended Solutions | Ease (1–10) | Impact (1–10) | Priority Score |
|-------|---------------|----------------|----------------------|-------------|---------------|----------------|
| Rewards & Loyalty | 16 | Cashback posted as points (7 calls), Incorrect category bonus (4 calls), Promotional bonus missing (3 calls) | Build redemption preference UI, Display merchant category codes, Implement in-app bonus tracker | 6.5 | 8.0 | 7.4 |

---

<!-- SLIDE: matrix_bet | layout: callout_stat | title: "The Highest-ROI Bet in This Dataset" -->

## The Biggest Bet

**Rewards & Loyalty** — fixing the top 3 drivers alone deflects **14 calls (87.5% of total volume)** and is achievable within one quarter.

---

<!-- SLIDE: recommendations | layout: section_divider | title: "Recommended Actions by Team" -->

# Recommended Actions by Owning Team

Organized by owning team for clear accountability. Each action is sequenced by priority score — highest first.

---

<!-- SLIDE: recommendations_digital | layout: action_list | title: "Digital / UX Actions" -->

## Digital / UX

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Implement a clear 'Redemption Preferences' section in the rewards dashboard | Rewards & Loyalty | ~7 calls (43.75%) | 7.4 |
| Implement a 'Points Transfer History' section with status and estimated completion | Rewards & Loyalty | ~1 call (6.25%) | 7.4 |

---

<!-- SLIDE: recommendations_ops | layout: action_list | title: "Operations Actions" -->

## Operations

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Display merchant category code (MCC) and applied earn rate for each transaction | Rewards & Loyalty | ~4 calls (25.0%) | 7.4 |

---

<!-- SLIDE: recommendations_comms | layout: action_list | title: "Communications Actions" -->

## Communications

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Implement an in-app offer tracker for welcome/promotional bonuses | Rewards & Loyalty | ~3 calls (18.75%) | 7.4 |

---

<!-- SLIDE: recommendations_policy | layout: action_list | title: "Policy / Governance Actions" -->

## Policy / Governance

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Implement a tier status dashboard and send 60-day advance notifications for downgrades | Rewards & Loyalty | ~1 call (6.25%) | 7.4 |

---

<!-- SLIDE: theme_divider | layout: section_divider | title: "Rewards & Loyalty — Deep Dive" -->

# Rewards & Loyalty — Deep Dive

**Priority:** 7.4/10 | **Ease:** 6.5/10 | **Impact:** 8.0/10
**Volume:** 16 calls | 100% of overall analyzed volume

---

<!-- SLIDE: theme_narrative | layout: callout_stat | title: "Rewards & Loyalty: The Story" -->

## Rewards & Loyalty: The Story

Customers believe they are earning and redeeming rewards as advertised, but are forced to call when the system fails them. Whether it's cashback turning into points without consent (7 calls) or promised bonuses not appearing (7 calls combined), the experience erodes trust and creates unnecessary service demand for issues that should be self-service.

---

<!-- SLIDE: theme_drivers | layout: scorecard_drivers | title: "Rewards & Loyalty: Root Cause Breakdown" -->

## Rewards & Loyalty: Root Cause Breakdown

| Driver | Call Count | % of Theme | Type | Owning Dimension | Recommended Solution |
|--------|-----------|------------|------|-----------------|---------------------|
| Cashback posted as points instead of statement credit; customer cannot find or change redemption preference. | 7 | 43.75% | Primary | digital | Implement a clear, easily discoverable self-service 'Redemption Preferences' section in the rewards dashboard allowing customers to select their default redemption method (cashback...). |
| Incorrect category bonus applied due to merchant miscoding (e.g., gas station as convenience store, grocery bonus not credited). | 4 | 25.0% | Secondary | operations | Display merchant category code (MCC) and the applied earn rate for each transaction. Provide an in-app explainer for common MCC discrepancies and a 'Why didn't I earn X points?' diagnostic. |
| Promotional bonuses (welcome/anniversary) not fully or timely credited. | 3 | 18.75% | Secondary | communication | Implement an in-app offer tracker for welcome bonuses showing progress towards spend requirements and a clear breakdown of points earned vs. expected. Add a 'Pending Bonuses' section. |
| Tier downgrade without prior warning or notification, leading to loss of benefits. | 1 | 6.25% | Secondary | policy | Implement a tier status dashboard showing current status and progress. Send 60-day advance notifications (push/email/in-app) for upcoming tier downgrades, clearly outlining lost benefits. |
| Points transferred to airline partner delayed and not appearing in frequent flyer account. | 1 | 6.25% | Secondary | digital | Implement a 'Points Transfer History' section showing status and estimated completion times. Clearly communicate expected transfer timelines. Investigate and resolve systemic delays. |

---

<!-- SLIDE: theme_consequence | layout: callout_stat | title: "If Nothing Changes: Rewards & Loyalty" -->

## If Nothing Changes

Without clear self-service options for redemption and bonus tracking, the 16 calls analyzed this cycle represent a recurring operational cost. As the loyalty program grows, these 100% preventable calls will scale directly with it, continuing to damage customer trust and increase service expense.
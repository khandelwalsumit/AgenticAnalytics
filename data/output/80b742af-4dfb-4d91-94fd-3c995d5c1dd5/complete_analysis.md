<!-- SLIDE: executive_summary | layout: title_impact | title: "16 Calls Expose a Broken Rewards Experience Driven by 3 Fixable Failures" -->

# 16 Calls Expose a Broken Rewards Experience Driven by 3 Fixable Failures

Analysis of 16 ATT customer calls reveals that 75% of all 'Rewards & Loyalty' issues stem from just three root causes: confusing redemption preferences, opaque bonus rules, and broken welcome offers. These failures are driving repeated, unnecessary calls and eroding trust in the loyalty program.

---

<!-- SLIDE: executive_summary | layout: callout_stat | title: "The Situation" -->

## The Situation

This analysis covers 16 calls from ATT customers specifically filtered for the 'Rewards & Loyalty' call reason. The findings represent a targeted look into the most critical friction points preventing customers from successfully managing their card benefits without agent intervention.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 1: Redemption Confusion Drives 7 Calls" -->

## Pain Point 1: Redemption Confusion Drives 7 Calls

**What's happening:** Customers are earning cashback but the system defaults to crediting it as points, not as a statement credit as they expect. They are then forced to call an agent because there is no self-service option to change this preference.
**The evidence:** 7 separate callers explicitly stated their cashback was posted incorrectly and they could not find a way to fix it online or in the app.
**Call volume:** 7 calls | 44% of total
**The fix:** Build a clear, self-service toggle in the rewards dashboard for customers to set their primary redemption preference (statement credit vs. points).

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 2: Opaque Bonus Rules Deny Rewards for 3 Calls" -->

## Pain Point 2: Opaque Bonus Rules Deny Rewards for 3 Calls

**What's happening:** Customers are not receiving category bonuses for purchases they believe should qualify. The system is denying the bonus based on a hidden Merchant Category Code (MCC) that misclassifies the purchase (e.g., a gas station coding as a 'convenience store').
**The evidence:** 3 customers called because their 5x gas category bonus was not applied. In each case, the root cause was a merchant coding mismatch invisible to the customer until the reward was denied.
**Call volume:** 3 calls | 19% of total
**The fix:** Display the Merchant Category Code (MCC) and the applied bonus rate directly in the transaction details for every purchase.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 3: Welcome Bonus Errors Frustrate New Customers (2 Calls)" -->

## Pain Point 3: Welcome Bonus Errors Frustrate New Customers (2 Calls)

**What's happening:** New cardmembers are meeting the spend requirements for their welcome bonus but are receiving a lower point value than advertised (e.g., 40,000 instead of 60,000 points). This creates immediate distrust in the program's value proposition.
**The evidence:** 2 new customers called to dispute the amount of their welcome bonus, stating they had met the terms of the original offer.
**Call volume:** 2 calls | 13% of total
**The fix:** Implement a real-time welcome bonus tracker in the app that clearly shows progress toward the spend requirement and the exact bonus they will receive.

---

<!-- SLIDE: quick_wins | layout: action_list | title: "Start Monday: 2 Quick Wins" -->

## Start Monday: 2 Quick Wins

| Action | Theme | Resolves | Why It's Fast |
|--------|-------|----------|---------------|
| Implement self-service redemption preference settings. | Rewards & Loyalty | ~7 calls (44%) | This is a standard feature in loyalty platforms and can be enabled via a front-end UI change tied to an existing API endpoint. |
| Implement proactive notifications for tier changes. | Rewards & Loyalty | ~1 call (6%) | Utilizes existing notification infrastructure (email, push) to trigger alerts based on an upcoming tier change date in the customer database. |

---

<!-- SLIDE: matrix | layout: section_divider | title: "Where to Act First" -->

# Where to Act First

Not all problems are equal. Not all fixes are equal. Because all 16 calls fall under a single, high-priority theme, this matrix clarifies the specific drivers that must be addressed to have the greatest impact on call reduction.

---

<!-- SLIDE: matrix | layout: table_full | title: "Impact vs. Ease: Full Prioritization Matrix" -->

## Impact vs. Ease: Prioritization Matrix

| Theme | Volume (calls) | Top 3 Problems | Recommended Solutions | Ease (1–10) | Impact (1–10) | Priority Score |
|-------|---------------|----------------|----------------------|-------------|---------------|----------------|
| Rewards & Loyalty | 16 | Redemption preference confusion (7 calls), Merchant category miscoding (3 calls), Incorrect welcome bonus (2 calls) | Build self-service redemption settings, Expose MCC codes in transaction history, Implement a welcome bonus tracker | 6.75 | 7.75 | 7.35 |

---

<!-- SLIDE: matrix_bet | layout: callout_stat | title: "The Highest-ROI Bet in This Dataset" -->

## The Biggest Bet

**Rewards & Loyalty** — fixing the top 3 drivers alone deflects **12 calls (75% of total volume)** and is achievable within one quarter by focusing development on self-service features and data transparency.

---

<!-- SLIDE: recommendations | layout: section_divider | title: "Recommended Actions by Team" -->

# Recommended Actions by Owning Team

Organized by owning team for clear accountability. Each action is sequenced by the priority score of the theme it addresses.

---

<!-- SLIDE: recommendations_digital | layout: action_list | title: "Digital / UX Actions" -->

## Digital / UX

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Build a self-service toggle for redemption preference (points vs. statement credit). | Rewards & Loyalty | ~7 calls (44%) | 7.35 |
| Display the Merchant Category Code (MCC) and applied bonus rate in transaction details. | Rewards & Loyalty | ~3 calls (19%) | 7.35 |
| Implement a real-time welcome bonus tracker showing progress and expected payout. | Rewards & Loyalty | ~2 calls (13%) | 7.35 |
| Implement proactive 60-day advance notifications for tier downgrades. | Rewards & Loyalty | ~1 call (6%) | 7.35 |

---

<!-- SLIDE: recommendations_ops | layout: action_list | title: "Operations Actions" -->

## Operations

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Ensure back-end systems correctly apply customer-selected redemption preferences. | Rewards & Loyalty | ~7 calls (44%) | 7.35 |
| Provide a clear escalation path for agents to correct MCC-related bonus errors. | Rewards & Loyalty | ~3 calls (19%) | 7.35 |

---

<!-- SLIDE: recommendations_comms | layout: action_list | title: "Communications Actions" -->

## Communications

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Clearly communicate the default redemption setting during card onboarding. | Rewards & Loyalty | ~7 calls (44%) | 7.35 |
| Publish clear explainers on how Merchant Category Codes (MCCs) determine bonuses. | Rewards & Loyalty | ~3 calls (19%) | 7.35 |
| Send confirmation notifications when a customer changes their redemption preference. | Rewards & Loyalty | ~7 calls (44%) | 7.35 |

---

<!-- SLIDE: recommendations_policy | layout: action_list | title: "Policy / Governance Actions" -->

## Policy / Governance

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Mandate that cashback redemption preferences must be a customer-configurable setting. | Rewards & Loyalty | ~7 calls (44%) | 7.35 |
| Establish a clear policy for handling MCC disputes and applying goodwill credits. | Rewards & Loyalty | ~3 calls (19%) | 7.35 |

---

<!-- SLIDE: theme_divider | layout: section_divider | title: "Rewards & Loyalty — Deep Dive" -->

# Rewards & Loyalty — Deep Dive

**Priority:** 7.35/10 | **Ease:** 6.75/10 | **Impact:** 7.75/10
**Volume:** 16 calls | 100% of overall analyzed volume

---

<!-- SLIDE: theme_narrative | layout: callout_stat | title: "Rewards & Loyalty: The Story" -->

## Rewards & Loyalty: The Story

Customers believe they are earning and redeeming rewards as advertised, but are forced to call when the system defaults their cashback to points, denies bonuses on a technicality, or fails to deliver on promotional promises. This friction undermines the core value of the loyalty program, turning potential advocates into frustrated callers who question the value of their ATT card.

---

<!-- SLIDE: theme_drivers | layout: scorecard_drivers | title: "Rewards & Loyalty: Root Cause Breakdown" -->

## Rewards & Loyalty: Root Cause Breakdown

| Driver | Call Count | % of Theme | Type | Owning Dimension | Recommended Solution |
|--------|-----------|------------|------|-----------------|---------------------|
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | 7 | 43.75% | Primary | digital | Make redemption preference settings easily discoverable and editable in the rewards dashboard. |
| Cashback posted as points instead of statement credit; redemption preference not configurable. | 7 | 43.75% | Primary | operations | Implement self-service redemption preference settings in the app/online. |
| Cashback posted as points instead of statement credit; inability to change redemption preference. | 7 | 43.75% | Primary | communication | Clearly communicate default redemption preference during onboarding and provide an easily accessible setting to change it. |
| The default cashback redemption method (points vs. statement credit) is not easily configurable by the customer. | 7 | 43.75% | Primary | policy | Implement a clear, self-service option in the app/website for customers to set their default redemption preference. |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | 3 | 18.75% | Secondary | digital | Display merchant category code (MCC) and its mapped bonus category in transaction details. |
| Category bonus not applied due to merchant category code (MCC) mismatch (e.g., gas station coded as convenience store). | 3 | 18.75% | Secondary | operations | Provide transparency on merchant category codes (MCCs) and how they map to bonus categories in the app/online. |
| Gas category bonus not applied due to merchant coding as 'convenience store'. | 3 | 18.75% | Secondary | communication | Provide clear examples of how Merchant Category Codes (MCCs) affect bonus categories. |
| Bonus category eligibility is unclear due to discrepancies between customer understanding and actual Merchant Category Codes (MCCs). | 3 | 18.75% | Secondary | policy | Display the Merchant Category Code (MCC) for each transaction and provide an in-app explanation of how MCCs map to bonus categories. |

---

<!-- SLIDE: theme_consequence | layout: callout_stat | title: "If Nothing Changes: Rewards & Loyalty" -->

## If Nothing Changes

Without clear self-service options for redemption and transparent bonus rules, all 16 of these monthly call types will persist. This will continue to drive up service costs, erode customer trust, and negate the positive brand impact the loyalty program is designed to create.
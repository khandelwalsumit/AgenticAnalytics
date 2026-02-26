<!-- SLIDE: executive_summary | layout: title_impact | title: "16 Calls Reveal One Critical Failure in Rewards Self-Service" -->

# 16 Calls Reveal a Critical Failure in Rewards Self-Service Costing Hours in Avoidable Agent Time

A small sample of 16 customer calls exposes a systemic failure in rewards self-service, with 44% of all issues stemming from a single, entirely fixable preference setting that is currently missing from the digital experience.

---

<!-- SLIDE: executive_summary | layout: callout_stat | title: "The Situation" -->

## The Situation

This report analyzes a targeted set of 16 customer support calls for the ATT product, filtered specifically for the "Rewards & Loyalty" call reason. The analysis identifies the root causes of customer friction and quantifies their impact to prioritize fixes.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 1: Redemption Preferences Are Hidden, Driving 44% of Calls" -->

## Pain Point 1: Redemption Preferences Are Hidden, Driving 44% of Calls

**What's happening:** Customers earning cashback rewards expect a statement credit but are defaulted into receiving points. The digital interface provides no clear, self-service path to change this preference.
**The evidence:** 7 of the 16 customers called support for the sole purpose of changing their redemption method after failing to find a way to do it themselves online or in the app.
**Call volume:** 7 calls | 43.8% of total
**The fix:** Build a clear, self-service toggle in the rewards dashboard to allow customers to set and modify their preferred redemption method (statement credit vs. points).

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 2: Merchant Miscoding Voids Bonuses, Confusing 19% of Callers" -->

## Pain Point 2: Merchant Miscoding Voids Bonuses, Confusing 19% of Callers

**What's happening:** Customers are not receiving category-specific bonuses (e.g., 5x on gas) because the merchant's payment terminal is coded incorrectly (e.g., 'convenience store').
**The evidence:** 3 customers called because they made qualifying purchases at gas stations but did not receive the promised bonus points, leading to confusion and a loss of trust in the program.
**Call volume:** 3 calls | 18.8% of total
**The fix:** Enhance the transaction detail view to display the merchant category code (MCC) and provide an in-app explanation of how it impacts bonus earn rates.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 3: Welcome Bonus Errors Break Initial Trust" -->

## Pain Point 3: Welcome Bonus Errors Break Initial Trust

**What's happening:** New customers who meet the initial spending requirements are receiving only a partial welcome bonus, forcing them to call support to claim the full amount.
**The evidence:** 2 customers called because they were promised a 60,000 point bonus but only received 40,000 points, creating a negative first impression of the loyalty program.
**Call volume:** 2 calls | 12.5% of total
**The fix:** Develop an in-app offer tracker that shows progress towards promotional bonuses and provides a self-service diagnostic for any discrepancies.

---

<!-- SLIDE: quick_wins | layout: action_list | title: "Start Monday: 1 Quick Win" -->

## Start Monday: Quick Wins

| Action | Theme | Resolves | Why It's Fast |
|--------|-------|----------|---------------|
| Implement a self-service redemption preference toggle (credit vs. points) | Rewards & Loyalty | ~7 calls (43.8%) | This is a standard UI component that modifies a single account-level setting; no complex integration is required. |

---

<!-- SLIDE: matrix | layout: section_divider | title: "Where to Act First" -->

# Where to Act First

Not all problems are equal. Not all fixes are equal. This matrix surfaces where limited effort yields the greatest call deflection.

---

<!-- SLIDE: matrix | layout: table_full | title: "Impact vs. Ease: Full Prioritization Matrix" -->

## Impact vs. Ease: Prioritization Matrix

| Theme | Volume (calls) | Top 3 Problems | Recommended Solutions | Ease (1–10) | Impact (1–10) | Priority Score |
|-------|---------------|----------------|----------------------|-------------|---------------|----------------|
| Rewards & Loyalty | 16 | Cashback posted as points (7 calls), Incorrect gas category bonus (3 calls), Partial welcome bonus (2 calls) | Implement self-service redemption preference, Display merchant category code (MCC) in transaction details, Build an in-app offer tracker | 7.25 | 8.5 | 7.95 |

---

<!-- SLIDE: matrix_bet | layout: callout_stat | title: "The Highest-ROI Bet in This Dataset" -->

## The Biggest Bet

**Rewards & Loyalty** — fixing the top 3 drivers alone deflects **12 calls (75% of total volume)** and is achievable within one quarter.

---

<!-- SLIDE: recommendations | layout: section_divider | title: "Recommended Actions by Team" -->

# Recommended Actions by Owning Team

Organized by owning team for clear accountability. Each action is sequenced by priority score — highest first.

---

<!-- SLIDE: recommendations_digital | layout: action_list | title: "Digital / UX Actions" -->

## Digital / UX

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Build a clear, self-service option in the rewards dashboard to set redemption preference (cashback vs. points) | Rewards & Loyalty | ~7 calls (43.8%) | 7.95 |
| Implement a feature in the transaction detail view that shows the merchant category code (MCC) | Rewards & Loyalty | ~3 calls (18.8%) | 7.95 |
| Develop an in-app offer tracker showing progress towards promotional bonuses and qualifying criteria | Rewards & Loyalty | ~2 calls (12.5%) | 7.95 |

---

<!-- SLIDE: recommendations_ops | layout: action_list | title: "Operations Actions" -->

## Operations

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Implement a clear self-service option for customers to set/change cashback redemption preference with immediate effect | Rewards & Loyalty | ~7 calls (43.8%) | 7.95 |
| Improve merchant category code (MCC) mapping logic for bonus categories or provide a dispute tool | Rewards & Loyalty | ~3 calls (18.8%) | 7.95 |

---

<!-- SLIDE: recommendations_comms | layout: action_list | title: "Communications Actions" -->

## Communications

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Provide clear, proactive education on redemption options during onboarding and first points accrual | Rewards & Loyalty | ~7 calls (43.8%) | 7.95 |
| Educate customers proactively on how merchant category codes (MCCs) affect bonus categories | Rewards & Loyalty | ~3 calls (18.8%) | 7.95 |

---

<!-- SLIDE: recommendations_policy | layout: action_list | title: "Policy / Governance Actions" -->

## Policy / Governance

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Implement a self-service option for customers to manage their choice between cashback and points | Rewards & Loyalty | ~7 calls (43.8%) | 7.95 |
| Provide clearer definitions of bonus categories and MCC mapping in the app/website | Rewards & Loyalty | ~3 calls (18.8%) | 7.95 |

---

<!-- SLIDE: theme_divider | layout: section_divider | title: "Rewards & Loyalty — Deep Dive" -->

# Rewards & Loyalty — Deep Dive

**Priority:** 7.95/10 | **Ease:** 7.25/10 | **Impact:** 8.5/10
**Volume:** 16 calls | 3.2% of overall analyzed volume

---

<!-- SLIDE: theme_narrative | layout: callout_stat | title: "Rewards & Loyalty: The Story" -->

## Rewards & Loyalty: The Story

Customers are successfully earning rewards but are being forced to call support to manage basic preferences and understand why their bonuses are not applying correctly. A lack of self-service tools for redemption settings and a lack of transparency into merchant category codes is driving 10 of the 16 analyzed calls (62.5%), creating unnecessary friction and operational cost for entirely preventable issues.

---

<!-- SLIDE: theme_drivers | layout: scorecard_drivers | title: "Rewards & Loyalty: Root Cause Breakdown" -->

## Rewards & Loyalty: Root Cause Breakdown

| Driver | Call Count | % of Theme | Type | Owning Dimension | Recommended Solution |
|--------|-----------|------------|------|-----------------|---------------------|
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | 7 | 43.75% | Primary | digital | Provide a clear, self-service option in the rewards dashboard to set or change redemption preference (cashback vs. points/statement credit). |
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | 7 | 43.75% | Primary | operations | Implement clear self-service option for customers to set/change cashback redemption preference (points vs. statement credit) with immediate effect. |
| Cashback posted as points, not statement credit; redemption preference unclear | 7 | 43.75% | Primary | communication | Provide clear, proactive education on redemption options and how to set/change preferences during onboarding and first points accrual. Ensure in-app guidance on managing preference... |
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | 7 | 43.75% | Primary | policy | Implement a self-service option in the app/website for customers to easily manage and change their preferred rewards redemption method (cashback vs. points). |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | 3 | 18.75% | Secondary | digital | Implement a feature in the transaction detail view that shows the merchant category code and explains how it impacts earn rates. Provide an in-app tool to dispute incorrect MCCs or... |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | 3 | 18.75% | Secondary | operations | Improve merchant category code (MCC) mapping logic for bonus categories or provide in-app tool for customers to dispute MCC categorization. |
| Gas category bonus not applied due to merchant coding as 'convenience store' | 3 | 18.75% | Secondary | communication | Educate customers proactively on how merchant category codes (MCCs) affect bonus categories, with in-app examples. Display the actual MCC and applied earn rate in transaction detai... |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | 3 | 18.75% | Secondary | policy | Provide clearer definitions of bonus categories and merchant category code (MCC) mapping in the app/website, and offer a mechanism to dispute incorrect category coding. |

---

<!-- SLIDE: theme_consequence | layout: callout_stat | title: "If Nothing Changes: Rewards & Loyalty" -->

## If Nothing Changes

Without a self-service way to manage redemption preferences, the 7 out of 16 customers calling about this issue will continue to do so, representing a persistent and scalable 44% of all rewards-related calls that will grow directly with your customer base.
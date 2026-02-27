<!-- SLIDE: executive_summary | layout: title_impact | title: "16 Calls Reveal a Single Point of Failure in Rewards Self-Service" -->

# 16 Calls Reveal a Single Point of Failure in Rewards Self-Service

Nearly half of all analyzed customer calls about rewards are driven by a single, fixable self-service gap: customers cannot easily control how their cashback is redeemed, forcing them into the call center for a simple preference change.

---

<!-- SLIDE: executive_summary | layout: callout_stat | title: "The Situation" -->

## The Situation

This analysis covers 16 calls from ATT customers specifically regarding the "Rewards & Loyalty" program. The findings expose a high degree of call preventability (95%) concentrated in one dominant theme.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 1: Cashback Preferences Are Hidden, Driving 44% of Calls" -->

## Pain Point 1: Cashback Preferences Are Hidden, Driving 44% of Calls

**What's happening:** Customers expecting a statement credit are surprised to find their cashback awarded as points and cannot find a self-service option to change this default.
**The evidence:** A recurring pattern of customers explicitly stating they looked for, but could not find, a preference setting in the app or website.
**Call volume:** 7 calls | 43.75% of total
**The fix:** Build a clear, prominent toggle in the rewards dashboard to allow users to select their default cashback redemption method (points vs. statement credit).

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 2: Bonus Point Rules Are Opaque, Driving 25% of Calls" -->

## Pain Point 2: Bonus Point Rules Are Opaque, Driving 25% of Calls

**What's happening:** Customers are not receiving expected 5x bonus points because transactions at merchants like gas stations are being miscategorized as 'convenience stores'.
**The evidence:** Customers cite specific transactions where the merchant type did not match their expectation, leading to a lower rewards earn rate.
**Call volume:** 4 calls | 25.0% of total
**The fix:** Expose the Merchant Category Code (MCC) for each transaction in the app and improve back-end mapping to better reflect the true nature of the merchant.

---

<!-- SLIDE: pain_point | layout: three_column | title: "Pain Point 3: Welcome Bonuses Are Inconsistent, Driving 13% of Calls" -->

## Pain Point 3: Welcome Bonuses Are Inconsistent, Driving 13% of Calls

**What's happening:** New cardholders are meeting the spend requirements for their welcome bonus but are receiving partial or incorrect point amounts.
**The evidence:** Customers are forced to call and manually verify their spend and bonus eligibility, indicating a lack of proactive tracking and fulfillment.
**Call volume:** 2 calls | 12.5% of total
**The fix:** Implement an in-app welcome offer tracker showing progress towards the spend goal and the exact bonus to be awarded.

---

<!-- SLIDE: quick_wins | layout: action_list | title: "Start Monday: 3 Quick Wins" -->

## Start Monday: 3 Quick Wins

| Action | Theme | Resolves | Why It's Fast |
|--------|-------|----------|---------------|
| Build a cashback preference toggle in the app/web dashboard. | Rewards & Loyalty | ~7 calls (43.75%) | This is a front-end change leveraging existing account settings infrastructure. |
| Implement an in-app welcome bonus progress tracker. | Rewards & Loyalty | ~2 calls (12.5%) | Utilizes existing transaction data and can be built as a simple UI module. |
| Send proactive notifications before tier status downgrades. | Rewards & Loyalty | ~1 call (6.25%) | Leverages existing notification systems and tier status data. |

---

<!-- SLIDE: matrix | layout: section_divider | title: "Where to Act First" -->

# Where to Act First

Not all problems are equal. Not all fixes are equal. This matrix surfaces where limited effort yields the greatest call deflection.

---

<!-- SLIDE: matrix | layout: table_full | title: "Impact vs. Ease: Full Prioritization Matrix" -->

## Impact vs. Ease: Prioritization Matrix

| Theme | Volume (calls) | Top 3 Problems | Recommended Solutions | Ease (1–10) | Impact (1–10) | Priority Score |
|-------|---------------|----------------|----------------------|-------------|---------------|----------------|
| Rewards & Loyalty | 16 | Cashback preference hidden (7 calls), MCC confusion (4 calls), Welcome bonus errors (2 calls) | Build preference toggle, Expose MCC data, Add offer tracker | 6.8 | 7.9 | 7.46 |

---

<!-- SLIDE: matrix_bet | layout: callout_stat | title: "The Highest-ROI Bet in This Dataset" -->

## The Biggest Bet

**Rewards & Loyalty** — fixing the top 2 drivers alone deflects **11 calls (68.75% of total volume)** and is achievable within one quarter.

---

<!-- SLIDE: recommendations | layout: section_divider | title: "Recommended Actions by Team" -->

# Recommended Actions by Owning Team

Organized by owning team for clear accountability. Each action is sequenced by priority score — highest first.

---

<!-- SLIDE: recommendations_digital | layout: action_list | title: "Digital / UX Actions" -->

## Digital / UX

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Provide a clear, discoverable option to manage cashback redemption preferences. | Rewards & Loyalty | ~7 calls (43.75%) | 7.46 |
| Implement a feature to show the Merchant Category Code (MCC) for each transaction. | Rewards & Loyalty | ~4 calls (25.0%) | 7.46 |

---

<!-- SLIDE: recommendations_ops | layout: action_list | title: "Operations Actions" -->

## Operations

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Implement a self-service backend to honor customer cashback preferences. | Rewards & Loyalty | ~7 calls (43.75%) | 7.46 |
| Improve Merchant Category Code (MCC) mapping logic to accurately reflect merchants. | Rewards & Loyalty | ~4 calls (25.0%) | 7.46 |

---

<!-- SLIDE: recommendations_comms | layout: action_list | title: "Communications Actions" -->

## Communications

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Provide clear upfront education on default redemption methods in onboarding. | Rewards & Loyalty | ~7 calls (43.75%) | 7.46 |
| Implement an in-app explainer for category bonuses and how MCCs work. | Rewards & Loyalty | ~4 calls (25.0%) | 7.46 |

---

<!-- SLIDE: recommendations_policy | layout: action_list | title: "Policy / Governance Actions" -->

## Policy / Governance

| Action | Theme | Resolves | Priority |
|--------|-------|----------|----------|
| Establish a policy that allows customers to easily set and change redemption defaults. | Rewards & Loyalty | ~7 calls (43.75%) | 7.46 |
| Review and clarify MCC policies for bonus categories to reduce ambiguity. | Rewards & Loyalty | ~4 calls (25.0%) | 7.46 |

---

<!-- SLIDE: theme_divider | layout: section_divider | title: "Rewards & Loyalty — Deep Dive" -->

# Rewards & Loyalty — Deep Dive

**Priority:** 7.46/10 | **Ease:** 6.8/10 | **Impact:** 7.9/10
**Volume:** 16 calls | 100% of overall analyzed volume

---

<!-- SLIDE: theme_narrative | layout: callout_stat | title: "Rewards & Loyalty: The Story" -->

## Rewards & Loyalty: The Story

Customers believe they are earning valuable cashback, but their trust is broken when that value is trapped in a points system they didn't choose. The inability to find a simple preference setting forces them to call, turning a loyalty benefit into a frustrating experience and driving up operational costs for what should be a fully digital interaction.

---

<!-- SLIDE: theme_drivers | layout: scorecard_drivers | title: "Rewards & Loyalty: Root Cause Breakdown" -->

## Rewards & Loyalty: Root Cause Breakdown

| Driver | Call Count | % of Theme | Type | Owning Dimension | Recommended Solution |
|--------|-----------|------------|------|-----------------|---------------------|
| Cashback posted as points instead of statement credit, preference unclear | 7 | 43.75% | Primary | digital | Provide clear, easily discoverable option to manage cashback redemption preferences (points vs. statement credit) within the rewards dashboard or profile settings. |
| Cashback posted as points instead of statement credit, preference unclear | 7 | 43.75% | Primary | operations | Implement a clear, self-service option for customers to set and change their cashback redemption preference (points vs. statement credit) in the app/online portal. |
| Cashback posted as points instead of statement credit, preference unclear | 7 | 43.75% | Primary | communication | Provide clear upfront education on default redemption methods and prominent in-app options to change preferences. |
| Default cashback redemption preference not easily changeable or understood | 7 | 43.75% | Primary | policy | Allow customers to easily set and change their default redemption preference (points vs. statement credit) via digital channels. |
| Merchant category code (MCC) confusion leading to incorrect bonus points | 4 | 25.0% | Secondary | communication | Implement an in-app explainer for category bonuses and MCCs, and display the actual earn rate applied to each transaction in the transaction history. |
| Merchant Category Code (MCC) mapping discrepancies for bonus categories | 4 | 25.0% | Secondary | policy | Review and clarify MCC policies for bonus categories; provide in-app tool for customers to check MCCs or see applied earn rates per transaction. |
| Customer used card at gas station, didn't get gas bonus (coded as 'convenience store') | 3 | 18.75% | Secondary | digital | Implement a feature to show the merchant category code (MCC) for each transaction and explain how it impacts earn rates. |
| Customer used card at gas station, didn't get gas bonus (coded as 'convenience store') | 3 | 18.75% | Secondary | operations | Improve merchant category code (MCC) mapping logic to accurately reflect common merchant types (e.g., gas stations that also operate as convenience stores). |

---

<!-- SLIDE: theme_consequence | layout: callout_stat | title: "If Nothing Changes: Rewards & Loyalty" -->

## If Nothing Changes

Without a clear self-service path to manage cashback preferences, the 7 out of 16 customers calling about this issue will continue to drive unnecessary contact center load, undermining the perceived value of the entire rewards program and increasing operational costs.
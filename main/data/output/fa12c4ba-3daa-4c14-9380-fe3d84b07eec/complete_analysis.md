# Digital Friction Analysis: ATT

This analysis focuses on 16 ATT customer calls, specifically addressing 'Rewards & Loyalty' issues. The data was filtered by 'Rewards & Loyalty' call reason and 'ATT' product, revealing critical friction points impacting customer experience.

### Top 3 Critical Pain Points

**1. Cashback Redemption Preference Confusion**
- Customers call because their cashback is posted as points instead of statement credit, and they cannot locate options to manage their redemption preferences.
- *Example:* Pattern: 7 calls (43.75% of total analyzed volume) directly cite issues with cashback being incorrectly applied as points due to unclear redemption settings.
- **Call volume:** 7 calls | 43.75% of total
- **Recommended:** Implement clear, self-service options in-app/web to manage cashback redemption preferences (points vs. statement credit).

**2. Incorrect Category Bonus Application**
- Customers are not receiving expected category bonuses (e.g., 5x gas) because merchants are coded differently (e.g., 'convenience store'), leading to missed rewards.
- *Example:* Pattern: 3 calls (18.75% of total analyzed volume) highlight gas station purchases being miscoded as 'convenience store', preventing 5x bonus.
- **Call volume:** 3 calls | 18.75% of total
- **Recommended:** Improve MCC mapping logic, provide transparent in-app MCC lookup/explanation tools, and display MCC for each transaction to clarify category bonus eligibility.

**3. Welcome Bonus Shortfalls**
- Customers report receiving fewer welcome bonus points than advertised, despite fulfilling all spend requirements, leading to dissatisfaction.
- *Example:* Pattern: 2 calls (12.5% of total analyzed volume) indicate discrepancies between expected and received welcome bonus points.
- **Call volume:** 2 calls | 12.5% of total
- **Recommended:** Implement an in-app offer tracker with progress, ensure automated and accurate bonus fulfillment, and proactively notify customers of expected bonus amounts and any discrepancies.

### Quick Wins

| Solution | Theme | Impact |
|----------|-------|--------|
| Implement clear, self-service options in-app/web to manage cashback redemption preferences (points vs. statement credit). | Rewards & Loyalty | **~7 calls (43.75%)** |
| Improve MCC mapping logic, provide transparent in-app MCC lookup/explanation tools. | Rewards & Loyalty | **~3 calls (18.75%)** |

---

## Impact vs Ease Prioritization

| Theme | Volume | Top 3 Problems | Solutions | Ease | Impact | Priority |
|-------|--------|-----------------|-----------|------|--------|----------|
| **Rewards & Loyalty** | **16 calls** | 1. Cashback redemption preference confusion (7 calls) 2. Incorrect category bonus application (3 calls) 3. Welcome bonus shortfalls (2 calls) | 1. Implement self-service cashback preference 2. Improve MCC mapping and provide lookup tools 3. Implement in-app offer tracker for welcome bonus | 7.25/10 | 8.0/10 | **7.7** |



---

## Recommended Actions

### Digital/UX
1. **Provide clear, self-service option to manage cashback redemption preferences (points vs. statement credit) in the rewards dashboard.** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Implement a real-time merchant category code lookup tool or provide clear examples of how common merchants are categorized for bonus earning.** — Rewards & Loyalty — Reduces ~3 calls (18.75%)

### Operations
1. **Implement clear, self-service redemption preference settings in-app and ensure correct cashback posting.** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Improve merchant category code (MCC) mapping logic and provide customer-facing MCC lookup/explanation tools.** — Rewards & Loyalty — Reduces ~4 calls (25.0%)

### Communication
1. **Clearly communicate default redemption preferences during onboarding and provide an easily discoverable in-app option to change preferences. Send a confirmation notification when redemption preferences are updated.** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Provide an in-app tool or FAQ explaining how merchant categories are determined and how they impact bonus earnings. Show the MCC for each transaction in the transaction detail.** — Rewards & Loyalty — Reduces ~3 calls (18.75%)

### Policy
1. **Implement a clear, self-service option in the app/web to select preferred cashback redemption method (points vs. statement credit) and ensure this preference is applied consistently across all channels.** — Rewards & Loyalty — Reduces ~7 calls (43.75%)
2. **Provide transparent merchant category code (MCC) mapping in the app, allowing customers to see how transactions are categorized and what bonus they will receive *before* or *immediately after* the transaction.** — Rewards & Loyalty — Reduces ~3 calls (18.75%)



---

## Rewards & Loyalty

> **Priority:** 7.7/10 | **Ease:** 7.25/10 | **Impact:** 8.0/10
> **Volume:** 16 calls | 100.0% of total

### Drivers

| Driver | Call Count | % Contribution | Type | Dimension |
|--------|-----------|----------------|------|-----------|
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | **7** | 43.75% | Primary | digital |
| Cashback posted as points instead of statement credit; redemption preference unclear | **7** | 43.75% | Primary | operations |
| Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. | **7** | 43.75% | Primary | communication |
| Cashback posted as points instead of statement credit; customer can't change redemption preference. | **7** | 43.75% | Primary | policy |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | **3** | 18.75% | Secondary | digital |
| Incorrect application of category bonus (e.g., gas, grocery) due to merchant coding | **4** | 25.0% | Secondary | operations |
| Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. | **3** | 18.75% | Secondary | communication |
| Missing category bonus (e.g., 5x gas) due to merchant miscoding (e.g., 'convenience store'). | **3** | 18.75% | Secondary | policy |

### Recommended Solutions
- **Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. → Provide clear, self-service option to manage cashback redemption preferences (points vs. statement credit) in the rewards dashboard.** — Expected reduction: ~7 calls
- **Cashback posted as points instead of statement credit; redemption preference unclear → Implement clear, self-service redemption preference settings in-app and ensure correct cashback posting.** — Expected reduction: ~7 calls
- **Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference. → Clearly communicate default redemption preferences during onboarding and provide an easily discoverable in-app option to change preferences. Send a confirmation notification when redemption preferences are updated.** — Expected reduction: ~7 calls
- **Cashback posted as points instead of statement credit; customer can't change redemption preference. → Implement a clear, self-service option in the app/web to select preferred cashback redemption method (points vs. statement credit) and ensure this preference is applied consistently across all channels.** — Expected reduction: ~7 calls
- **Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. → Implement a real-time merchant category code lookup tool or provide clear examples of how common merchants are categorized for bonus earning.** — Expected reduction: ~3 calls
- **Incorrect application of category bonus (e.g., gas, grocery) due to merchant coding → Improve merchant category code (MCC) mapping logic and provide customer-facing MCC lookup/explanation tools.** — Expected reduction: ~4 calls
- **Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'. → Provide an in-app tool or FAQ explaining how merchant categories are determined and how they impact bonus earnings. Show the MCC for each transaction in the transaction detail.** — Expected reduction: ~3 calls
- **Missing category bonus (e.g., 5x gas) due to merchant miscoding (e.g., 'convenience store'). → Provide transparent merchant category code (MCC) mapping in the app, allowing customers to see how transactions are categorized and what bonus they will receive *before* or *immediately after* the transaction.** — Expected reduction: ~3 calls



---

---

## Appendix: Analysis Pipeline Trace

### Narrative Agent Output
Summary of what the narrative agent produced: 1 report title, 1 subtitle, 5 sections (Executive Summary, Impact vs Ease Matrix, Recommendations by Dimension, Theme Deep Dive).

### Synthesizer Agent Output
Summary of theme aggregation: 1 themes, 16 total calls, 8 findings.

### Individual Agent Outputs
#### Digital Friction Agent
Summary: Not available.

#### Operations Agent
Summary: Not available.

#### Communication Agent
Summary: Not available.

#### Policy Agent
Summary: Not available.


---
*Report generated by AgenticAnalytics*

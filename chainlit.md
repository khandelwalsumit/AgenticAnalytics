# Agentic Analytics — Customer Friction Intelligence 🔍

Welcome! This system turns **raw customer call data** into **actionable friction insights** and a ready-to-present **PowerPoint report** — all through a simple chat conversation.

### How it Works

1. **You describe the data you want to explore** — e.g. a product, call reason, or customer segment.
2. The system **filters & buckets** your dataset, then shows you the key themes it found.
3. You pick which **friction dimensions** to analyze (or run all four):
   - 🖥️ **Digital** — UX gaps, app/web issues, self-service failures
   - ⚙️ **Operations** — Process breakdowns, SLA issues, handoff failures
   - 💬 **Communication** — Notification gaps, unclear messaging
   - 📜 **Policy** — Regulatory constraints, fee disputes
4. Four specialist AI agents analyze the data **in parallel** with access to skill based on the primary_domin of the call/theme.. so based on theme Primary_domin it lodas the skills in context and generate insights... skill tells the agent exactly what to focus on based of th detailed prompt for each primary_domina. then a Synthesizer merges their findings into a ranked, scored report.
5. A **Narrative + Formatting** pipeline auto-generates an executive slide deck (`.pptx`) you can download instantly.

---

# Agent Graph Flow 🔄

Every conversation is orchestrated by a **Supervisor** that acts as the central hub. It reads your message, decides the next step, and routes to the right agent — then gets control back after each agent finishes.

```
START → Supervisor ─┬─→ Planner ──────────────────→ Supervisor
                    ├─→ Data Analyst → Lens Confirmation → Supervisor
                    ├─→ Friction Analysis (subgraph) ──→ Supervisor
                    ├─→ Report Generation (subgraph) ──→ Supervisor
                    ├─→ Report Analyst ────────────────→ Supervisor
                    ├─→ Critique ──────────────────────→ Supervisor
                    └─→ END
```

### Node-by-Node Breakdown

| # | Agent | What it does |
|---|-------|-------------|
| 1 | **Supervisor** | Understands your intent → routes to the right agent. Loops back after every step. |
| 2 | **Planner** | Creates an ordered execution plan (extract → analyse → report → deliver). |
| 3 | **Data Analyst** | Loads dataset, applies filters (product / call_reason), buckets themes. |
| 4 | **Lens Confirmation** | Pauses the graph — asks you which friction dimensions to run before proceeding. |
| 5 | **Friction Analysis** *(subgraph)* | Fans out to 4 lens agents **in parallel** (Digital, Operations, Communication, Policy) × each data bucket, then feeds all outputs into the **Synthesizer** which merges findings, ranks them, and scores preventability. |
|5.1| **Skills** | **Friction Analysis** | each agent loads the skills based on primary_domain making it a speceliast on the domain for that bucket.. CALL_REASONS_TO_SKILLS = {
        "Payments & Transfers":["payment_transfer","fraud_dispute"],
        "Dispute & Fraud":["fraud_dispute","payment_transfer"],
        "Products & Offers":["promotions_offers"],
        "Sign On":["authentication"],
        "Profile & Settings":["profile_settings","authentication"],
        "Replace Card":["card_replacement","profile_settings"],
        "Transactions & Statements":["transaction_statement"],
        "Other":["general_inquiry"],
        "Rewards":["rewards","promotions_offers"]
}

| 6 | **Report Generation** *(subgraph)* | Runs **Narrative Agent** (writes executive story, theme dives, recommendations) → **Formatting Agent** (builds slide-by-slide blueprint) → **Artifact Writer** (renders `.pptx`, `.md`, `.csv` files). |
| 7 | **Report Analyst** | Verifies all artifacts exist, presents download links. |
| 8 | **Critique** *(optional)* | QA pass — grades synthesis quality, flags gaps, can trigger revisions. |

> 💡 After every agent finishes, control returns to the **Supervisor**, which reads the updated state and decides the next move — until the full plan is complete and you have your report.

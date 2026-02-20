# Profile & Settings Analysis Skill

## Focus Areas
- Personal information updates (name, email, phone, address)
- Preference and notification settings
- Communication channel preferences
- Account settings and security preferences
- KYC and document updates

## Key Fields to Analyze
- `exact_problem_statement` — Customer's specific profile/settings issue
- `solution_by_ui` — UI improvements for self-service updates
- `solution_by_ops` — Operational process improvements
- `call_reason` → `granular_theme_l5` — Full call reason hierarchy

## Analysis Framework

### Step 1: Categorize by Update Type
- **Contact info** — phone number, email address changes
- **Personal details** — name change, date of birth corrections
- **Address** — residential/mailing address updates
- **Preferences** — notification settings, language, currency
- **Security** — PIN change, security questions, linked devices
- **KYC/Documents** — ID verification, document re-submission

### Step 2: Identify Friction Points
- Which updates can be done self-service vs require agent assistance?
- What verification steps create friction during updates?
- Are update confirmations timely and clear?
- Do updates propagate correctly across all channels?

### Step 3: Self-Service Gap Analysis
- Map each update type to its current self-service capability
- Identify updates that customers expect to self-serve but can't
- Quantify the call volume for each non-self-service update type
- Assess the security justification for agent-only updates

### Step 4: Map Solutions
- **UI fixes** — in-app profile editing, progress tracking for pending updates
- **Ops fixes** — streamlined verification processes, faster processing times
- **Education** — guide customers to self-service options they may not know about

## Investigation Questions
1. What are the top profile/settings update requests by volume?
2. What percentage of profile updates could be self-served but aren't?
3. Which updates require the most verification steps?
4. How long do profile updates take to process end-to-end?
5. What is the error rate for self-service profile updates?
6. Are customers aware of existing self-service profile options?

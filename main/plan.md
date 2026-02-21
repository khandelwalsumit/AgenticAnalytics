# AgenticAnalytics — End-to-End Project Plan

## 1. Context & Problem Statement

The Customer Experience team has **300K+ call records** processed through batch LLM, producing structured analysis fields (problem statements, friction categories, solution pathways, L1–L5 call reason hierarchies). They need an intelligent, multi-agent system that helps analysts interactively explore this data, identify friction points, extract actionable insights, and generate crisp reports — all through a conversational UI.

**Tech Stack**: LangGraph (orchestration) + Gemini via Google AI Studio (LLM) + Chainlit (UI)

---

## 2. Key Design Decisions

### 2.1 Markdown-Driven Agent & Skill Definitions

Agents and skills are defined as **Markdown files** — no Python code for prompt engineering. This makes it trivial to add/update agents or skills without touching application code.

**Agent Markdown Format** (`agents/definitions/<name>.md`):
```yaml
---
name: data_analyst
model: gemini-2.5-flash
temperature: 0.1
top_p: 0.95
max_tokens: 8192
description: "Prepares data through schema discovery, filtering, and bucketing"
tools:
  - load_dataset
  - filter_data
  - bucket_data
  - sample_data
  - get_distribution
---

You are a Data Analyst agent specializing in customer experience data...

## Your Responsibilities
...system prompt continues...
```

**Skill Markdown Format** (`skills/domain/<name>.md`):
```markdown
# Payment & Transfer Analysis Skill

## Focus Areas
- Payment failures, transfer issues, refunds, limits

## Key Fields to Analyze
- exact_problem_statement, digital_friction, solution_by_ui

## Analysis Framework
When analyzing payment & transfer issues, follow this structure:
1. Categorize by failure type...
```

### 2.2 Merged Supervisor (No Separate Planner)

The Supervisor generates `PlanStep`, executes it, and updates progress in a single pass. This halves latency and cost vs a separate Planner agent. Can be re-split later if planning logic becomes heavy.

### 2.3 AgentFactory Class

A Python class that reads agent markdown files and uses `create_react_agent` from LangGraph + ChatGoogleGenerativeAI to instantiate agents dynamically.

### 2.4 Deterministic Metrics Engine

All quantitative computations (% distribution, top themes, comparison ratios, volume counts) are **Python-computed, not LLM-inferred**. The LLM interprets and narrates metrics — never computes them. Implemented as `MetricsEngine` in `tools/metrics.py`.

### 2.5 Data Payloads Out of Conversational Context

Raw DataFrames and large text blobs are stored in a session-scoped **DataStore** (file-backed cache keyed by session ID). `AnalyticsState` only holds metadata references. Agents fetch full data via tools when needed. This prevents memory bloat and slow serialization.

### 2.6 XML-Wrapped Skill Injection

`SkillLoader` wraps each skill's content in XML tags: `<skill name="payment_transfer" category="domain">...content...</skill>`. LLMs are optimized to read XML boundaries, improving cross-referencing accuracy.

### 2.7 Insight Ranking System

Agents output structured, scored findings — not free-text. Each finding includes `impact_score` (volume × friction_severity), `ease_score` (inverse complexity), and `confidence`.

### 2.8 Multi-Dimensional Friction Analysis (4-Lens Parallel Subgraph)

Instead of a single Business Analyst doing all analysis, **4 independent friction lens agents** examine the same data in parallel through distinct lenses:
- **Digital** — product/UX failures
- **Operations** — internal execution failures
- **Communication** — expectation management gaps
- **Policy** — regulatory/rule-driven friction

A **Synthesizer Agent** merges the 4 outputs, detects dominant drivers, ranks by impact × ease, and flags multi-factor themes.

### 2.9 Parallel Reporting Subgraph

Instead of a single Report Analyst, **3 specialized agents** work in parallel:
- **Narrative Agent** — executive storytelling
- **Data Visualization Agent** — chart generation via code execution
- **Formatting Agent** — assembles everything into Markdown + PPT

### 2.10 Scope Detector as Dedicated Classification Node

Post-analysis Q&A scope detection uses a lightweight, dedicated classification node with `structured_output` enforcing `in_scope: bool` — not a general conversation node. Fast, deterministic, low-cost.

### 2.11 Chainlit UI Enhancements

- Chat history persistence — resume previous sessions
- Critique toggle — on/off switch per chat session
- Download buttons — report (PPT) + data file at end of analysis
- Planner banner — top banner showing current plan step and completion progress
- Agent reasoning steps — each node's reasoning displayed as collapsible step
- Waiting indicator — blinking colored indicator when awaiting user confirmation

---

## 3. Architecture

```
User (Chainlit UI)
  │  ┌────────────────────────────────────┐
  │  │ Banner: Plan steps & progress      │
  │  │ Toggle: Critique ON/OFF            │
  │  └────────────────────────────────────┘
  ▼
┌──────────────────────────────────────────┐
│              SUPERVISOR                  │
│  (Plan + Route + Manage checkpoints)     │
└────┬─────────┬───────────┬──────────┬────┘
     ▼         ▼           ▼          ▼
  ┌──────┐ ┌──────────┐ ┌──────────┐ ┌────────┐
  │ Data │ │Business  │ │Report    │ │Critique│
  │Analyst│ │Analyst   │ │Analyst   │ │(toggle)│
  └──────┘ │(sub-sup) │ │(sub-sup) │ └────────┘
           └────┬─────┘ └────┬─────┘
                ▼            ▼
  ┌─────────────────┐  ┌─────────────────┐
  │ Analysis Squad  │  │ Reporting Squad  │
  │ (4 friction     │  │ (Narrative +     │
  │  agents +       │  │  DataViz +       │
  │  Synthesizer)   │  │  Formatting)     │
  └─────────────────┘  └─────────────────┘

  [Tools]   [Skills]   [DataStore]
  [Metrics]  (XML)     (file-backed)
              │
         Domain Skills
         (6 .md files)

  Post-Analysis:
  ┌──────────────────┐
  │  SCOPE DETECTOR  │  ← lightweight classification node
  │  (structured     │     with_structured_output(bool)
  │   output)        │
  └──────────────────┘
```

### Detailed Graph Flow

```
Supervisor → Data Analyst → [checkpoint] → Supervisor

  → friction_analysis (Send API fan-out):
      ├── Digital Friction Agent ──┐
      ├── Operations Agent ────────┤  (parallel execution)
      ├── Communication Agent ─────┤
      └── Policy Agent ────────────┘
                                   ↓
                      Synthesizer Agent (root cause + ease/impact prioritization)
                                   ↓
  → Supervisor → [checkpoint]

  → report_generation (Send API fan-out):
      ├── Narrative Agent ─────────┐  (parallel execution)
      ├── Data Visualization Agent ┤
      └───────────────────────────-┘
                                   ↓
                      Formatting Agent (assembles Markdown + PPT)
                                   ↓
  → Supervisor → Delivery (downloads + Q&A mode)
```

---

## 4. Project Structure

```
AgenticAnalytics/
├── app.py                              # Chainlit entry point
├── pyproject.toml                      # Dependencies (managed by uv)
├── plan.md                             # This file
├── .chainlit/
│   └── config.toml                     # Chainlit settings
├── config/
│   ├── __init__.py
│   └── settings.py                     # App config (model, paths, thresholds, agent groups)
├── core/
│   ├── __init__.py
│   ├── agent_factory.py                # AgentFactory: reads .md → creates LangGraph agents
│   ├── skill_loader.py                 # SkillLoader: reads skill .md, wraps in XML, injects
│   ├── data_store.py                   # DataStore: session-scoped file-backed cache
│   └── llm.py                          # Google AI Studio / Gemini LLM factory
├── agents/
│   ├── __init__.py
│   ├── state.py                        # AnalyticsState TypedDict + all structured types
│   ├── graph.py                        # Main StateGraph with Send API fan-outs
│   ├── nodes.py                        # Agent node functions (skill injection + state writing)
│   └── definitions/                    # Agent definitions as Markdown
│       ├── supervisor.md               # Orchestrator (plans, routes, checkpoints)
│       ├── data_analyst.md             # Data preparation
│       ├── business_analyst.md         # Sub-supervisor for Analysis Subgraph
│       ├── digital_friction_agent.md   # Digital Product Auditor lens
│       ├── operations_agent.md         # Process Accountability lens
│       ├── communication_agent.md      # Expectation Management lens
│       ├── policy_agent.md             # Governance Constraint lens
│       ├── synthesizer_agent.md        # Root Cause Synthesizer (merges 4 outputs)
│       ├── report_analyst.md           # Sub-supervisor for Reporting Subgraph
│       ├── narrative_agent.md          # Executive Storyteller
│       ├── dataviz_agent.md            # Chart generation via code execution
│       ├── formatting_agent.md         # Report assembly (Markdown + PPT)
│       └── critique.md                 # QA validation (toggleable)
├── skills/
│   └── domain/                         # Domain skills (6 files)
│       ├── payment_transfer.md
│       ├── transaction_statement.md
│       ├── authentication.md
│       ├── profile_settings.md
│       ├── fraud_dispute.md
│       └── rewards.md
├── tools/
│   ├── __init__.py                     # Tool registry + analysis/critique/supervisor/chart tools
│   ├── data_tools.py                   # load_dataset, filter_data, bucket_data, sample_data, get_distribution
│   ├── metrics.py                      # MetricsEngine: deterministic computations
│   └── report_tools.py                 # generate_markdown_report, export_to_pptx
├── utils/
│   ├── __init__.py
│   └── pptx_export.py                  # Markdown → PowerPoint converter
├── ui/
│   ├── __init__.py
│   ├── components.py                   # Chainlit UI components (banner, steps, indicators)
│   └── chat_history.py                 # Chat history persistence
└── data/
    └── .gitkeep                        # Placeholder for CSV data + generated charts
```

---

## 5. Agent Definitions

### 5.1 Supervisor (`agents/definitions/supervisor.md`)
- **Tools**: `[delegate_to_agent]`
- **Role**: Plans, routes to agents/subgraphs, manages checkpoints
- **Delegation targets**: `data_analyst`, `business_analyst`, `friction_analysis`, `report_generation`, `report_analyst`, `critique`
- **Q&A mode**: Delegates to Scope Detector; answers in-scope questions using existing artifacts

### 5.2 Data Analyst (`agents/definitions/data_analyst.md`)
- **Tools**: `[load_dataset, filter_data, bucket_data, sample_data, get_distribution]`
- **Role**: Data preparation — schema discovery, filtering, bucketing, sampling, distributions

### 5.3 Business Analyst (`agents/definitions/business_analyst.md`)
- **Tools**: `[analyze_bucket, get_findings_summary]`
- **Role**: Sub-supervisor for Analysis Subgraph — orchestrates 4 friction agents + Synthesizer
- **Does NOT** perform analysis itself — delegates to the friction agents

### 5.4 Digital Friction Agent (`agents/definitions/digital_friction_agent.md`)
- **Tools**: `[analyze_bucket, apply_skill]`
- **Role**: Digital Product Auditor — findability, UX, self-service capability
- **Primary Question**: "Could this issue have been resolved through digital experience?"
- **Failure types**: findability, feature_gap, awareness, navigation, eligibility_visibility
- **All 6 domain skills** injected at runtime

### 5.5 Operations Agent (`agents/definitions/operations_agent.md`)
- **Tools**: `[analyze_bucket, apply_skill]`
- **Role**: Process Accountability — SLA violations, manual dependencies, system lag
- **Primary Question**: "Was this call triggered because operational workflow failed?"
- **Breakpoint types**: sla_delay, manual_dependency, system_lag, incorrect_processing
- **All 6 domain skills** injected at runtime

### 5.6 Communication Agent (`agents/definitions/communication_agent.md`)
- **Tools**: `[analyze_bucket, apply_skill]`
- **Role**: Expectation Management — missing notifications, unclear status, poor expectation setting
- **Primary Question**: "If the customer had known this in advance, would they still have called?"
- **Gap types**: missing_notification, unclear_status, expiry_visibility, proactive_education
- **All 6 domain skills** injected at runtime

### 5.7 Policy Agent (`agents/definitions/policy_agent.md`)
- **Tools**: `[analyze_bucket, apply_skill]`
- **Role**: Governance Constraint — regulatory, risk controls, compliance, internal rules
- **Primary Question**: "Is the friction caused by a rule rather than a failure?"
- **Constraint types**: regulatory, risk_control, compliance_requirement, internal_rule
- **All 6 domain skills** injected at runtime

### 5.8 Synthesizer Agent (`agents/definitions/synthesizer_agent.md`)
- **Tools**: `[get_findings_summary]`
- **Role**: Root Cause Synthesizer — merges 4 lens outputs into unified intelligence
- **Receives**: 4 friction agent outputs as extra_context
- **Produces**: Dominant driver detection, multi-factor flagging, preventability scoring, impact × ease ranking
- **Output schema** adds: `dominant_driver`, `contributing_factors`, `preventability_score`

### 5.9 Report Analyst (`agents/definitions/report_analyst.md`)
- **Tools**: `[get_findings_summary]`
- **Role**: Sub-supervisor for Reporting Subgraph — orchestrates Narrative + DataViz + Formatting
- **Does NOT** produce reports itself

### 5.10 Narrative Agent (`agents/definitions/narrative_agent.md`)
- **Tools**: `[get_findings_summary]`
- **Role**: Executive Storyteller — transforms findings into compelling narratives
- **Produces**: executive_summary (under 200 words), theme_narratives, quick_wins_highlight

### 5.11 Data Visualization Agent (`agents/definitions/dataviz_agent.md`)
- **Tools**: `[analyze_bucket, execute_chart_code]`
- **Role**: Generates charts via Python code execution (matplotlib)
- **Chart types**: friction distribution bar, impact vs ease scatter, multi-lens stacked bar, preventability overview
- **Saves**: chart image files to `data/` directory

### 5.12 Formatting Agent (`agents/definitions/formatting_agent.md`)
- **Tools**: `[generate_markdown_report, export_to_pptx]`
- **Role**: Report assembly — combines narrative + charts into final Markdown + PPT
- **Report sections**: Executive Summary, Multi-Dimensional Findings, Charts, Impact vs Ease Matrix, Recommendations, Data Appendix

### 5.13 Critique (`agents/definitions/critique.md`)
- **Tools**: `[validate_findings, score_quality]`
- **Role**: QA on all analyst outputs — toggleable by user
- **Checks**: Data accuracy, completeness, actionability, consistency, bias

### 5.14 Scope Detector (Dedicated Node — not an agent .md)
- **Implementation**: Lightweight node using `llm.with_structured_output(ScopeDecision)`
- **Input**: User question + `analysis_scope` snapshot
- **Output**: `ScopeDecision(in_scope: bool, reason: str)`

---

## 6. Domain Skills

| Skill | File | Focus |
|---|---|---|
| Payment & Transfer | `skills/domain/payment_transfer.md` | Payment failures, transfer issues, refunds, limits |
| Transaction & Statement | `skills/domain/transaction_statement.md` | Transaction history, statement access, discrepancies |
| Authentication | `skills/domain/authentication.md` | Login issues, OTP, biometric, session management |
| Profile & Settings | `skills/domain/profile_settings.md` | Profile updates, preferences, notification settings |
| Fraud & Dispute | `skills/domain/fraud_dispute.md` | Unauthorized transactions, dispute resolution, alerts |
| Rewards | `skills/domain/rewards.md` | Points, cashback, redemption, tier benefits |

> **Note**: Operational skills (`digital.md`, `operations.md`, `policy.md`) were removed — their analytical content was folded directly into the friction agent system prompts.

---

## 7. Core Components

### 7.1 AgentFactory (`core/agent_factory.py`)
```python
class AgentFactory:
    """Reads agent .md files → creates LangGraph agents."""
    def parse_agent_md(name) -> AgentConfig       # Parse YAML frontmatter + prompt
    def make_agent(name, extra_context="") -> Agent  # Create LangGraph react agent
    def make_node(name, extra_context="") -> Callable  # Returns a node function
```

### 7.2 SkillLoader (`core/skill_loader.py`)
```python
class SkillLoader:
    """Reads skill .md files, wraps in XML tags, injects into prompts."""
    def load_skill(name) -> str         # Single skill, XML-wrapped
    def load_skills(names) -> str       # Multiple skills, concatenated
    def list_skills() -> dict           # Available skills by category
```

### 7.3 DataStore (`core/data_store.py`)
```python
class DataStore:
    """Session-scoped file-backed cache for large data payloads."""
    def store_dataframe(key, df, metadata) -> str
    def get_dataframe(key) -> pd.DataFrame
    def store_text(key, content, metadata) -> str
    def get_text(key) -> str
    def get_metadata(key) -> dict
    def cleanup()
```

### 7.4 MetricsEngine (`tools/metrics.py`)
```python
class MetricsEngine:
    """Deterministic Python computations — keeps math out of LLM."""
    def get_distribution(df, column) -> dict
    def compute_impact_score(volume_pct, friction_severity) -> float
    def compute_ease_score(complexity) -> float
    def rank_findings(findings, sort_by="impact_score") -> list[dict]
    def top_n(df, column, n=10) -> list[dict]
```

### 7.5 Tool Registry (`tools/__init__.py`)
```python
TOOL_REGISTRY = {
    # Data tools
    "load_dataset", "filter_data", "bucket_data", "sample_data", "get_distribution",
    # Analysis tools
    "analyze_bucket", "apply_skill", "get_findings_summary",
    # Report tools
    "generate_markdown_report", "export_to_pptx",
    # Critique tools
    "validate_findings", "score_quality",
    # Supervisor tools
    "delegate_to_agent",
    # DataViz tools
    "execute_chart_code",
}
```

---

## 8. Shared State (`agents/state.py`)

```python
class AnalyticsState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

    # User intent
    user_focus: str
    analysis_type: str                    # "domain" | "operational" | "combined"
    selected_skills: list[str]
    critique_enabled: bool

    # Plan (Supervisor generates + executes)
    current_plan: dict
    plan_steps_total: int
    plan_steps_completed: int

    # Execution trace
    execution_trace: list[ExecutionTrace]

    # Data — METADATA ONLY (raw data in DataStore)
    dataset_path: str
    dataset_schema: dict
    active_filters: dict
    data_buckets: dict[str, dict]

    # Analysis — scored findings
    findings: list[RankedFinding]
    domain_analysis: dict
    operational_analysis: dict

    # Friction lens agent outputs
    digital_analysis: dict
    operations_analysis: dict
    communication_analysis: dict
    policy_analysis: dict

    # Synthesis output
    synthesis_result: dict

    # Reporting subgraph outputs
    narrative_output: dict
    dataviz_output: dict
    formatting_output: dict

    # Report — metadata only
    report_markdown_key: str
    report_file_path: str
    data_file_path: str

    # Quality
    critique_feedback: dict
    quality_score: float

    # Control flow
    next_agent: str
    requires_user_input: bool
    checkpoint_message: str
    phase: str                            # "analysis" | "qa"

    # Q&A mode
    analysis_complete: bool
    analysis_scope: ScopeSnapshot

    # UI state
    agent_reasoning: list[dict]
```

---

## 9. Graph Assembly (`agents/graph.py`)

### Node Registry (16 nodes)
| Node | Source |
|---|---|
| `supervisor` | AgentFactory + `supervisor.md` |
| `data_analyst` | AgentFactory + `data_analyst.md` |
| `business_analyst` | AgentFactory + `business_analyst.md` (with skill_loader) |
| `digital_friction_agent` | AgentFactory + `digital_friction_agent.md` (with skill_loader) |
| `operations_agent` | AgentFactory + `operations_agent.md` (with skill_loader) |
| `communication_agent` | AgentFactory + `communication_agent.md` (with skill_loader) |
| `policy_agent` | AgentFactory + `policy_agent.md` (with skill_loader) |
| `synthesizer_agent` | AgentFactory + `synthesizer_agent.md` |
| `report_analyst` | AgentFactory + `report_analyst.md` |
| `narrative_agent` | AgentFactory + `narrative_agent.md` |
| `dataviz_agent` | AgentFactory + `dataviz_agent.md` |
| `formatting_agent` | AgentFactory + `formatting_agent.md` |
| `critique` | AgentFactory + `critique.md` |
| `scope_detector` | Direct LLM call with `with_structured_output` |
| `user_checkpoint` | Simple passthrough (graph pauses via `interrupt_before`) |

### Edge Topology
```
START → supervisor

supervisor → {data_analyst, business_analyst, report_analyst, critique,
              scope_detector, user_checkpoint, __end__}         (string routes)
supervisor → [digital, ops, comm, policy]                       (Send fan-out: friction_analysis)
supervisor → [narrative, dataviz]                                (Send fan-out: report_generation)

digital_friction_agent → synthesizer_agent
operations_agent → synthesizer_agent
communication_agent → synthesizer_agent
policy_agent → synthesizer_agent
synthesizer_agent → supervisor

narrative_agent → formatting_agent
dataviz_agent → formatting_agent
formatting_agent → supervisor

data_analyst → supervisor
business_analyst → supervisor
report_analyst → supervisor
critique → supervisor
user_checkpoint → supervisor

scope_detector → {supervisor, __end__}
```

### Context Injection (`agents/nodes.py`)
| Agent Group | Extra Context Injected |
|---|---|
| Friction agents | All 6 domain skills via `skill_loader.load_skills(ALL_DOMAIN_SKILLS)` |
| Synthesizer | 4 friction agent outputs as JSON (`digital_analysis`, `operations_analysis`, `communication_analysis`, `policy_analysis`) |
| Reporting agents | Synthesis result + findings as JSON |
| Formatting agent | Also gets `narrative_output` + `dataviz_output` |
| Business analyst | Selected skills via `skill_loader.load_skills(selected)` |

### State Writing
Each friction/reporting agent writes to its dedicated state field via `AGENT_STATE_FIELDS` mapping.

---

## 10. Chainlit UI (`app.py` + `ui/`)

### Chat History (`ui/chat_history.py`)
- Persist conversation state using Chainlit's thread persistence
- User can resume previous analysis sessions from sidebar

### Banner & Progress (`ui/components.py`)
- **Planner Banner**: Top-of-chat element showing current step name, progress bar (step X of Y)
- **Agent Reasoning Steps**: Each agent execution rendered as collapsible step with reasoning text
- **Waiting Indicator**: Animated blinking element when awaiting user confirmation

### Critique Toggle
- Settings panel: "Critique: ON / OFF"
- Stored in `AnalyticsState.critique_enabled`
- When OFF, supervisor skips critique node entirely

### Download Buttons
- At end of analysis, two `cl.Action` buttons:
  - "Download Report (PPT)" → serves generated `.pptx` file
  - "Download Data File" → serves the filtered/bucketed CSV

---

## 11. Data Schema (CSV Columns)

| Column | Description |
|---|---|
| `exact_problem_statement` | Customer's exact problem from the call |
| `digital_friction` | Digital channel friction analysis |
| `policy_friction` | Policy-related friction analysis |
| `solution_by_ui` | Solution via UI/UX changes |
| `solution_by_ops` | Solution via operational changes |
| `solution_by_education` | Solution via customer education |
| `solution_by_technology` | Solution via technology fixes |
| `call_reason` | L1 — Top-level call reason |
| `call_reason_l2` | L2 — Secondary call reason |
| `broad_theme_l3` | L3 — Broad theme |
| `intermediate_theme_l4` | L4 — Intermediate theme |
| `granular_theme_l5` | L5 — Granular theme |
| `friction_driver_category` | Category of friction driver |

System auto-discovers additional columns at runtime via `load_dataset` tool.

---

## 12. Guided Analysis Flow

### Phase A: Analysis Pipeline

```
1.  Data Discovery      → delegate to data_analyst (load CSV, discover schema)
2.  User Checkpoint      → present schema summary, confirm focus area
3.  Data Preparation     → delegate to data_analyst (filtering + bucketing)
4.  User Checkpoint      → present bucket summary, confirm data slicing
5.  Friction Analysis    → delegate to friction_analysis (4 parallel agents)
6.  [Auto] Synthesis     → Synthesizer merges 4 outputs (root cause + ranking)
7.  User Checkpoint      → present multi-dimensional findings
8.  Critique (optional)  → delegate to critique (if enabled)
9.  Report Generation    → delegate to report_generation (Narrative + DataViz → Formatting)
10. Delivery             → present report + downloads, transition to Q&A mode
```

### Phase B: Post-Analysis Q&A Mode

```
User question → Scope Detector (structured classification)
  ├── IN-SCOPE  → Supervisor answers using existing artifacts
  └── OUT-OF-SCOPE → Explain divergence, suggest new chat

IN-SCOPE examples:
  - "Tell me more about the payment friction on mobile"
  - "Compare authentication issues between L3 themes"
  - "What % of digital friction is about findability?"

OUT-OF-SCOPE examples:
  - "Now analyze the credit card data" (new dataset)
  - "What about international transfers?" (not in current filters)

Artifacts available for Q&A:
  - data_buckets, findings, synthesis_result
  - domain_analysis, narrative_output, dataviz_output
  - report_markdown, dataset_schema
```

### Checkpoints (`interrupt_before`)
Graph pauses at `user_checkpoint` node for user input after:
- Data discovery (confirm schema understanding)
- Filter/bucket results (confirm data slicing)
- Analysis findings (steer or go deeper)

---

## 13. Implementation Phases

### Phase 1: Foundation (8 files)
1. `pyproject.toml` — Dependencies
2. `.env.example` — Environment variables
3. `config/settings.py` — Configuration constants + agent group constants
4. `core/llm.py` — Gemini LLM factory
5. `core/agent_factory.py` — AgentFactory (parse .md → create_react_agent)
6. `core/skill_loader.py` — SkillLoader (with XML wrapping)
7. `core/data_store.py` — DataStore (session-scoped file-backed cache)
8. `agents/state.py` — Shared state: AnalyticsState + all structured types

### Phase 2: Agent Definitions (13 files)
9. `agents/definitions/supervisor.md`
10. `agents/definitions/data_analyst.md`
11. `agents/definitions/business_analyst.md` — Sub-supervisor for Analysis
12. `agents/definitions/digital_friction_agent.md`
13. `agents/definitions/operations_agent.md`
14. `agents/definitions/communication_agent.md`
15. `agents/definitions/policy_agent.md`
16. `agents/definitions/synthesizer_agent.md`
17. `agents/definitions/report_analyst.md` — Sub-supervisor for Reporting
18. `agents/definitions/narrative_agent.md`
19. `agents/definitions/dataviz_agent.md`
20. `agents/definitions/formatting_agent.md`
21. `agents/definitions/critique.md`

### Phase 3: Domain Skills (6 files)
22. `skills/domain/payment_transfer.md`
23. `skills/domain/transaction_statement.md`
24. `skills/domain/authentication.md`
25. `skills/domain/profile_settings.md`
26. `skills/domain/fraud_dispute.md`
27. `skills/domain/rewards.md`

### Phase 4: Tools (4 files)
28. `tools/data_tools.py` — Data tools (uses MetricsEngine internally)
29. `tools/metrics.py` — MetricsEngine: deterministic computations
30. `tools/report_tools.py` — Report generation + PPT export
31. `utils/pptx_export.py` — Markdown → PowerPoint converter

### Phase 5: Tool Registry + Chart Tool (1 file)
32. `tools/__init__.py` — Tool registry + `execute_chart_code` + `delegate_to_agent`

### Phase 6: Graph & Nodes (2 files)
33. `agents/nodes.py` — Node functions (skill injection, context injection, state writing)
34. `agents/graph.py` — Main StateGraph with Send API fan-outs

### Phase 7: UI & Integration (4 files)
35. `ui/components.py` — Banner, reasoning steps, waiting indicator, download buttons
36. `ui/chat_history.py` — Chat history persistence
37. `.chainlit/config.toml` — Chainlit configuration
38. `app.py` — Chainlit app: on_chat_start, on_message, streaming, file handling

---

## 14. Verification Checklist

1. **Smoke test**: `AgentFactory.parse_agent_md()` correctly parses all 13 agent .md files
2. **Tool resolution**: All agent tool references resolve in `TOOL_REGISTRY`
3. **Skill test**: `SkillLoader.load_skills(ALL_DOMAIN_SKILLS)` returns XML-wrapped content for all 6
4. **DataStore test**: Store/retrieve DataFrames and text; verify metadata-only in state
5. **Metrics test**: `MetricsEngine` methods produce correct deterministic results
6. **Tool test**: Each tool works independently on sample data
7. **Graph compilation**: `build_graph()` compiles with all 16 nodes, no errors
8. **Agent isolation**: Each friction lens stays in its lane
9. **Scope Detector test**: Returns correct `ScopeDecision` for in/out-of-scope queries
10. **ExecutionTrace test**: Traces capture step_id, agent, tools_used, latency_ms
11. **End-to-end test**:
    - `chainlit run app.py` — starts with welcome message
    - Upload CSV → Data Analyst discovers schema → bucketing works
    - Friction analysis fan-out → 4 agents parallel → Synthesizer merges
    - Report generation fan-out → Narrative + DataViz → Formatting assembles
    - Download buttons appear → PPT opens correctly
    - Q&A mode works (in-scope drill-down + out-of-scope redirect)
12. **UI test**: Banner updates, reasoning steps render, indicators show, downloads work
13. **Memory test**: DataFrames NOT in LangGraph state; only metadata refs present

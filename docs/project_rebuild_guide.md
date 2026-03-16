# AgenticAnalytics Rebuild Guide

## Purpose

This document explains how to recreate this project from scratch while keeping the same folder structure, the same major runtime flow, and the same user-facing functionality.

It intentionally assumes:

- happy path only
- local development only
- one primary dataset
- one main UI (`Chainlit`)
- minimal recovery logic
- less orchestration complexity than the current codebase

Use this as the implementation contract for a clean rebuild.

---

## 1. What This Project Does

`AgenticAnalytics` is a multi-agent analytics application that:

1. accepts a user question about customer/service friction
2. loads a tabular dataset from `data/input`
3. filters and buckets the data
4. runs multiple analysis lenses in parallel
5. synthesizes findings into one ranked output
6. generates report artifacts (`.md`, `.docx`, `.pptx`, `.csv`)
7. lets the user resume threads and ask follow-up questions

The current implementation uses:

- `Chainlit` for chat UI
- `LangGraph` for workflow orchestration
- `LangChain` agents/tools for LLM execution
- `pandas` for data handling
- file-based persistence instead of a database

---

## 2. Happy-Path Product Behavior

The rebuild should support this exact simplified user flow:

1. User opens the Chainlit app.
2. App auto-detects a parquet file in `data/input` or accepts an uploaded CSV/parquet.
3. User asks an analysis question like "What promotion-related issues are ATT customers facing?"
4. Supervisor decides this is an analysis request.
5. Data analyst:
   - loads dataset
   - applies filters
   - buckets rows into themes
   - asks which lenses to run
6. User replies with lens selection or "run all lenses".
7. Planner creates a task plan.
8. Dispatcher runs:
   - `friction_analysis`
   - `report_drafts`
   - `artifact_writer`
   - `report_analyst`
9. App shows progress in the task list.
10. App renders download buttons for generated files.
11. User can later resume the thread and ask questions about the finished report.

For the simplified rebuild, you do not need to implement:

- fault injection
- complex retry policies
- partial synthesis recovery
- elaborate checkpoint branching
- deep prompt tuning
- advanced chart layout fallback logic

---

## 3. Required Folder Structure

Recreate this structure first. Empty placeholder files are acceptable initially.

```text
AgenticAnalytics/
|-- agents/
|   |-- __init__.py
|   |-- definitions/
|   |   |-- business_analyst.md
|   |   |-- communication_agent.md
|   |   |-- critique.md
|   |   |-- data_analyst.md
|   |   |-- digital_friction_agent.md
|   |   |-- formatting_agent.md
|   |   |-- narrative_agent.md
|   |   |-- operations_agent.md
|   |   |-- planner.md
|   |   |-- policy_agent.md
|   |   |-- qna_agent.md
|   |   |-- report_analyst.md
|   |   |-- supervisor.md
|   |   `-- synthesizer_agent.md
|   |-- graph.py
|   |-- graph_helpers.py
|   |-- nodes.py
|   |-- schemas.py
|   `-- state.py
|-- core/
|   |-- __init__.py
|   |-- agent_factory.py
|   |-- chat_model.py
|   |-- data_store.py
|   |-- file_data_layer.py
|   `-- skill_loader.py
|-- data/
|   |-- .cache/
|   |-- input/
|   |   |-- adf.parquet
|   |   |-- template.pptx
|   |   |-- template_catalog.json
|   |   `-- template_splanned_strucure.md
|   `-- output/
|-- docs/
|-- public/
|   |-- favicon.ico
|   |-- logo.png
|   |-- test.css
|   |-- test.js
|   `-- theme.json
|-- skills/
|   `-- domain/
|       |-- authentication.md
|       |-- card_replacement.md
|       |-- fraud_dispute.md
|       |-- general_inquiry.md
|       |-- payment_transfer.md
|       |-- profile_settings.md
|       |-- promotions_offers.md
|       |-- rewards.md
|       `-- transaction_statement.md
|-- test/
|   |-- checks.py
|   |-- manual_testing.md
|   `-- test_artifacts.py
|-- tools/
|   |-- __init__.py
|   |-- data_tools.py
|   |-- metrics.py
|   |-- report_tools.py
|   `-- template_extractor.py
|-- ui/
|   |-- __init__.py
|   |-- chat_history.py
|   `-- components.py
|-- utils/
|   |-- __init__.py
|   |-- docx_export.py
|   |-- pptx_builder.py
|   |-- pptx_export.py
|   `-- section_splitter.py
|-- .env
|-- .gitignore
|-- app.py
|-- config.py
`-- main.py
```

Notes:

- `main.py` can remain a trivial placeholder.
- `app.py` is the actual application entry point.
- The active IDE path `business_logic/core/orchestrator.py` is not part of this checked-in repo. The real orchestrator is `agents/graph.py`.

---

## 4. High-Level Architecture

Keep this architecture in the rebuild.

### UI layer

- `app.py`
- `ui/components.py`
- `ui/chat_history.py`
- `core/file_data_layer.py`

Responsibilities:

- start Chainlit
- authenticate user
- handle uploads
- stream workflow updates
- persist threads and chat state
- show tasks, reasoning, and downloads

### Orchestration layer

- `agents/graph.py`
- `agents/nodes.py`
- `agents/state.py`
- `agents/schemas.py`

Responsibilities:

- define LangGraph state
- define nodes
- route between nodes
- keep plan progress
- interrupt for user confirmation

### Agent-definition layer

- `agents/definitions/*.md`
- `core/agent_factory.py`

Responsibilities:

- keep prompts outside Python
- parse frontmatter from markdown
- construct either structured-output agents or tool-calling agents

### Data and persistence layer

- `core/data_store.py`
- `core/file_data_layer.py`
- `ui/chat_history.py`

Responsibilities:

- store large intermediate payloads outside graph state
- persist chat threads locally
- persist resumable thread state locally

### Analysis and report tools

- `tools/data_tools.py`
- `tools/report_tools.py`
- `tools/__init__.py`
- `tools/metrics.py`
- `utils/*.py`

Responsibilities:

- data loading/filtering/bucketing
- bucket analysis support
- findings accumulation
- report generation
- docx/pptx/csv export

### Skill layer

- `skills/domain/*.md`
- `core/skill_loader.py`

Responsibilities:

- inject domain-specific reference instructions into friction agents

---

## 5. Simplified End-to-End Flow

Implement this flow first.

```text
User message
  -> supervisor
  -> data_analyst
  -> interrupt for lens confirmation
  -> planner
  -> plan_dispatcher
  -> friction_analysis
  -> plan_dispatcher
  -> report_drafts
  -> plan_dispatcher
  -> artifact_writer
  -> plan_dispatcher
  -> report_analyst
  -> supervisor/qna/end
```

### Node responsibilities

#### `supervisor`

Input:

- conversation messages
- existing plan
- dataset/filter context
- completion state

Output:

- decision: `answer`, `plan`, or `execute`
- next node
- optional user-facing message

Simplified rule set:

- if no dataset prep has happened, route to `data_analyst`
- if plan exists and analysis is not complete, route to `execute`
- if analysis is complete and user asks a follow-up question, route to `qna`
- otherwise route to `planner` or `data_analyst`

#### `data_analyst`

Calls tools:

- `load_dataset`
- `filter_data`
- `bucket_data`

Writes:

- `filters_applied`
- `data_buckets`
- `themes_for_analysis`
- `filtered_parquet_path`

Then pauses for user confirmation of which analysis lenses to run.

#### `planner`

Creates ordered tasks like:

1. `data_analyst`
2. `friction_analysis`
3. `report_drafts`
4. `artifact_writer`
5. `report_analyst`

In the rebuild, this can be deterministic first and LLM-generated later.

#### `plan_dispatcher`

Pure Python node.

Responsibilities:

- mark current task as done
- promote next task to `in_progress`
- set `next_agent`
- mark `analysis_complete` when all tasks finish

#### `friction_analysis`

Composite node that internally runs selected lens agents in parallel:

- `digital_friction_agent`
- `operations_agent`
- `communication_agent`
- `policy_agent`

Then run `synthesizer_agent`.

For the rebuild, keep this simple:

- iterate through buckets
- run selected lens agents
- save each lens output as markdown
- merge them with synthesizer

#### `report_drafts`

Creates:

- narrative markdown
- slide blueprint JSON

Main outputs:

- `narrative_output`
- `formatting_output`

#### `artifact_writer`

Creates:

- markdown file
- csv export
- docx file
- pptx file

Writes final artifact paths into state.

#### `report_analyst`

Final delivery node.

Responsibilities:

- verify files exist
- emit final completion message
- allow UI to render downloads

#### `qna`

Loads the generated markdown report and answers questions from that content only.

---

## 6. State Contract

Create `agents/state.py` with one `AnalyticsState` typed dict. Keep the same field names so the rest of the structure stays compatible.

Minimum required fields:

```python
messages
critique_enabled
plan_steps_total
plan_steps_completed
plan_tasks
execution_trace
reasoning
last_completed_node
dataset_path
dataset_schema
data_buckets
filtered_parquet_path
bucket_paths
top_themes
analytics_insights
findings
digital_analysis
operations_analysis
communication_analysis
policy_analysis
friction_output_files
friction_md_paths
lens_synthesis_paths
synthesis_result
synthesis_output_file
synthesis_path
narrative_output
narrative_path
dataviz_output
formatting_output
report_markdown_key
report_file_path
docx_file_path
data_file_path
markdown_file_path
critique_feedback
quality_score
next_agent
supervisor_decision
checkpoint_message
checkpoint_prompt
pending_input_for
analysis_scope_reply
analysis_complete
phase
proposed_filters
filters_applied
themes_for_analysis
analysis_objective
selected_agents
auto_approve_checkpoints
thread_id
fault_injection
error_count
recoverable_error
```

Rule for the rebuild:

- keep raw large data out of state
- only store metadata, file paths, summaries, and small JSON payloads in state

---

## 7. Agent Inventory

Recreate these agent prompt files in `agents/definitions/`.

### Required for the rebuild

- `supervisor.md`
- `planner.md`
- `data_analyst.md`
- `digital_friction_agent.md`
- `operations_agent.md`
- `communication_agent.md`
- `policy_agent.md`
- `synthesizer_agent.md`
- `narrative_agent.md`
- `formatting_agent.md`
- `report_analyst.md`
- `qna_agent.md`

### Optional initially

- `business_analyst.md`
- `critique.md`

You can keep `critique` and `business_analyst` as placeholders in v1 of the rebuild.

### Tool mapping

Use this simplified mapping:

- `supervisor`: no tools
- `planner`: no tools
- `data_analyst`: `load_dataset`, `filter_data`, `bucket_data`, `sample_data`, `get_distribution`
- `digital_friction_agent`: `analyze_bucket`, `apply_skill`
- `operations_agent`: `analyze_bucket`, `apply_skill`
- `communication_agent`: `analyze_bucket`, `apply_skill`
- `policy_agent`: `analyze_bucket`, `apply_skill`
- `synthesizer_agent`: no tools if it reads from state/files
- `narrative_agent`: `get_findings_summary`
- `formatting_agent`: no tools if blueprint is deterministic
- `report_analyst`: `generate_markdown_report`, `export_to_pptx`, `export_to_docx`, `export_filtered_csv`
- `qna_agent`: no tools; use report markdown as prompt context

### Structured vs ReAct agents

Keep this split:

- structured-output agents:
  - `supervisor`
  - `planner`
  - `synthesizer_agent`
- tool-calling ReAct agents:
  - `data_analyst`
  - four friction agents
  - `narrative_agent`
  - `report_analyst`
  - `qna_agent`

For the simplified rebuild, `formatting_agent` can be fully deterministic in Python instead of an LLM.

---

## 8. Skills Inventory

Create the following domain skill files in `skills/domain/`:

- `authentication.md`
- `card_replacement.md`
- `fraud_dispute.md`
- `general_inquiry.md`
- `payment_transfer.md`
- `profile_settings.md`
- `promotions_offers.md`
- `rewards.md`
- `transaction_statement.md`

Purpose:

- each bucket gets one or more business-domain skills
- friction agents use those skills as injected analysis frameworks

Simplified implementation:

- each skill file can just contain short markdown guidance
- `SkillLoader` should wrap it in XML-like tags
- friction agents only need plain text injection, nothing more complex

---

## 9. Data Layer Design

### `core/data_store.py`

This is a session-scoped file cache for large payloads.

Support these operations:

- `store_dataframe(key, df, metadata)`
- `get_dataframe(key)`
- `store_text(key, content, metadata)`
- `get_text(key)`
- `store_versioned_md(base_name, content, metadata)`
- `get_path(key)`
- `get_metadata(key)`
- `list_keys()`
- `cleanup()`

Storage pattern:

- base directory: `data/.cache/<thread_id>/`
- registry file: `data/.cache/<thread_id>/_registry.json`

### `core/file_data_layer.py`

This is Chainlit thread persistence.

Use local JSON storage:

- `data/.cache/data_layer/threads/*.json`
- `data/.cache/data_layer/users/*.json`

This is enough for:

- sidebar thread history
- chat resume
- local testing without a database

### `ui/chat_history.py`

Separate from the Chainlit thread layer.

This file persists analytics workflow state:

- `data/.cache/states/<thread_id>.json`

Reason:

- thread history and workflow state are different concerns
- workflow state must be resumable even if the UI restarts

---

## 10. Tool Contracts

### Data tools

Implement these first in `tools/data_tools.py`.

#### `load_dataset(path="")`

Behavior:

- read parquet from `DEFAULT_PARQUET_PATH`
- return schema, row count, sample values, relevant columns

#### `filter_data(filters)`

Behavior:

- apply column-value filters using pandas
- store filtered dataframe in `DataStore`
- return counts and applied filters

Happy-path simplification:

- ignore fuzzy resolution beyond simple column existence checks

#### `bucket_data(group_by="", focus="")`

Behavior:

- group filtered data by configured hierarchy
- create buckets with metadata
- assign domain skills from `CALL_REASONS_TO_SKILLS`
- store one combined bucketed dataframe in `DataStore`

Happy-path simplification:

- one-level grouping is enough for v1  
- recursive sub-bucketing can be added later

#### `sample_data(bucket, n=5)`

Return only a small sample for prompt context.

#### `get_distribution(column, bucket="")`

Return value counts and percentages.

### Analysis tools in `tools/__init__.py`

#### `analyze_bucket(bucket, questions)`

Should return:

- bucket metadata
- row count
- top distributions
- sample rows

#### `apply_skill(skill_name, bucket)`

Should return:

- skill content
- bucket metadata
- top problems

#### `get_findings_summary()`

Should return ranked accumulated findings.

### Report tools in `tools/report_tools.py`

#### `generate_markdown_report(...)`

Create `complete_analysis.md`.

#### `export_filtered_csv()`

Create `filtered_data.csv`.

#### `export_to_docx()`

Convert markdown to `report.docx`.

#### `export_to_pptx()`

Generate `report.pptx`.

Happy-path simplification:

- allow markdown-to-pptx fallback if structured blueprint rendering is not ready

---

## 11. Configuration Contract

Create `config.py` with these categories.

### Paths

- `ROOT_DIR`
- `AGENTS_DIR`
- `SKILLS_DIR`
- `DATA_DIR`
- `DATA_INPUT_DIR`
- `DATA_OUTPUT_DIR`
- `DATA_CACHE_DIR`
- `THREAD_STATES_DIR`

### Main settings

- `DEFAULT_PARQUET_PATH`
- `PPTX_TEMPLATE_PATH`
- `GROUP_BY_COLUMNS`
- `LLM_ANALYSIS_CONTEXT`
- `LLM_ANALYSIS_FOCUS`
- `MIN_BUCKET_SIZE`
- `MAX_BUCKET_SIZE`
- `TAIL_BUCKET_ENABLED`

### Agent groups

- `FRICTION_AGENTS`
- `REPORTING_AGENTS`
- `ALL_DOMAIN_SKILLS`
- `CALL_REASONS_TO_SKILLS`

### Model settings

- `DEFAULT_MODEL`
- `DEFAULT_TEMPERATURE`
- `DEFAULT_TOP_P`
- `DEFAULT_MAX_TOKENS`

### Runtime tuning

- `MAX_MULTITHREADING_WORKERS`
- `MAX_SUPERVISOR_MSGS`
- `MAX_DISPLAY_LENGTH`
- `LOG_LEVEL`
- `LOG_FORMAT`
- `LOG_DATE_FORMAT`

For the rebuild, keep config simple and environment-driven through `.env`.

---

## 12. Minimal Implementation Order

Build in this order. Do not start with prompts or UI polish.

### Phase 1: Skeleton

1. create folder structure
2. create `config.py`
3. create `app.py` with a trivial Chainlit app
4. create `agents/state.py`
5. create empty agent markdown files

Exit condition:

- app starts
- folders resolve
- dataset path can be read from config

### Phase 2: Persistence

1. implement `DataStore`
2. implement `FileDataLayer`
3. implement `ui/chat_history.py`

Exit condition:

- thread files persist
- state files persist
- data cache folders are created per thread

### Phase 3: Tools

1. implement `tools/metrics.py`
2. implement `tools/data_tools.py`
3. implement `tools/report_tools.py`
4. implement tool registry in `tools/__init__.py`

Exit condition:

- dataset loads
- filters apply
- bucketing works
- markdown/docx/pptx/csv can be written

### Phase 4: Agent loading

1. implement `core/skill_loader.py`
2. implement `core/agent_factory.py`
3. implement `core/chat_model.py`

Exit condition:

- agent markdown files can be parsed
- structured agents can be created
- tool-calling agents can be created

### Phase 5: Orchestration

1. implement `agents/schemas.py`
2. implement `agents/nodes.py`
3. implement `agents/graph.py`

Exit condition:

- graph compiles
- supervisor routes correctly
- happy-path run completes end to end

### Phase 6: UI behavior

1. implement `ui/components.py`
2. connect upload handling in `app.py`
3. connect resume handling in `app.py`
4. connect download rendering in `app.py`

Exit condition:

- tasks render
- reasoning renders
- files are downloadable
- resume works

### Phase 7: Prompt quality

1. improve agent prompts
2. add domain skills
3. tighten narrative/report quality

This phase should happen last.

---

## 13. Simplified Python Module Responsibilities

### `app.py`

Owns:

- Chainlit startup
- session setup
- file upload handling
- graph streaming
- UI task updates
- state save/load hooks

Keep these handlers:

- `@cl.password_auth_callback`
- `@cl.data_layer`
- `@cl.on_chat_start`
- `@cl.on_message`
- `@cl.on_chat_resume`
- `@cl.on_chat_end`

### `core/agent_factory.py`

Must:

- parse markdown frontmatter
- cache agent definitions
- cache LLM instances
- create structured chains
- create tool-calling agents

### `agents/graph.py`

Must:

- define all graph nodes inside `build_graph()`
- compile a `StateGraph`
- keep routing explicit

### `agents/nodes.py`

Must provide reusable helpers for:

- invoking structured agents
- invoking ReAct agents
- building extra prompt context
- extracting tool result state
- advancing plan progress

### `tools/metrics.py`

Must support:

- summary stats
- top N
- value distributions
- finding ranking

---

## 14. Artifact Output Rules

When a run completes, the rebuild must create a thread-specific output folder:

```text
data/output/<thread_id>/
  report.docx
  report.pptx
  filtered_data.csv
  complete_analysis.md
```

Temporary and intermediate files should live in:

```text
data/.cache/<thread_id>/
```

Examples of cached content:

- filtered parquet
- bucketed parquet
- friction markdown versions
- synthesis markdown versions
- narrative markdown versions
- registry JSON

---

## 15. Prompt File Format

Each agent markdown file should have:

```md
---
name: supervisor
description: Routes requests
model: gemini-2.5-flash
temperature: 0.1
top_p: 0.95
max_tokens: 8192
tools: []
handoffs: []
---

System prompt goes here.
```

Rules:

- keep prompt text in markdown, not Python
- put tool names in frontmatter
- let `AgentFactory` resolve them from `TOOL_REGISTRY`

---

## 16. Recommended Simplifications for the Rebuild

These changes reduce effort without changing the main product behavior.

### Make planner deterministic first

Instead of using an LLM planner immediately, hardcode:

1. `data_analyst`
2. `friction_analysis`
3. `report_drafts`
4. `artifact_writer`
5. `report_analyst`

Later, switch planner back to structured LLM output.

### Make formatting deterministic first

Instead of asking an LLM to create slide blueprints, generate the slide plan in Python from synthesis findings.

### Make `friction_analysis` less granular first

Instead of writing one markdown file per agent per bucket version, start with:

- one combined output per selected lens
- one synthesis output

### Keep QnA simple

Load `complete_analysis.md` and answer directly from it.

### Skip critique in v1

You can keep the `critique` files present but unused.

---

## 17. Definition of Done

The rebuild is complete when all of the following are true:

1. `Chainlit` app starts from `app.py`.
2. A parquet file in `data/input` is automatically recognized.
3. A user can ask an analysis question.
4. Data is filtered and bucketed.
5. User can choose selected lenses.
6. Selected lens agents run and produce findings.
7. Synthesizer merges the findings.
8. Narrative/report outputs are generated.
9. Files are written to `data/output/<thread_id>/`.
10. Download buttons appear in the UI.
11. Thread resume restores prior state.
12. User can ask follow-up questions against the generated report.

---

## 18. Suggested Build Checklist

Use this as the actual execution checklist.

### Repo and setup

- create folder tree
- add `.env`
- add `config.py`
- install dependencies

### Core runtime

- implement `DataStore`
- implement `FileDataLayer`
- implement thread-state persistence

### Tools

- implement metrics helpers
- implement data tools
- implement report tools
- implement tool registry

### Agents

- add prompt markdown files
- implement agent loader/factory
- implement skill loader
- implement schemas

### Graph

- implement state model
- implement node helpers
- implement graph routing
- implement happy-path interrupt for lens confirmation

### UI

- implement chat start/message/resume hooks
- implement task list sync
- implement reasoning display
- implement downloads

### Verification

- run one complete analysis
- verify output files
- verify resume
- verify follow-up QnA

---

## 19. Practical Notes for the Rebuild

- Keep `app.py` as the only runtime entry point.
- Keep `agents/graph.py` as the single orchestration source of truth.
- Keep prompts in markdown files so non-code changes stay cheap.
- Keep file persistence local until there is a real need for a database.
- Keep state small and file references large.
- Prefer deterministic Python for planning and formatting until the rest of the system is stable.

---

## 20. Short Version

If you only follow one implementation summary, follow this:

1. Recreate the folder structure exactly.
2. Build file-based persistence first.
3. Build pandas tools second.
4. Build a deterministic LangGraph happy-path pipeline third.
5. Add LLM prompts and quality improvements last.

That sequence will get you to a working clone of the current product shape with much less back and forth than trying to rebuild the full present-day complexity immediately.

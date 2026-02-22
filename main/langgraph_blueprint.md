# LangGraph Blueprint (Product Contract)

## Goal
Define a production-safe graph contract where:
- checkpoints are optional (not required for every step)
- each node has explicit input/output expectations
- UI can render progress and reasoning without node-specific hacks

## 1) Core State Contract

Use a single state shape, but keep node outputs as deltas:

```python
class AnalyticsState(TypedDict, total=False):
    # Conversation
    messages: list[Any]
    phase: str  # "analysis" | "qa"
    analysis_complete: bool

    # Plan / progress
    plan_tasks: list[dict]  # [{id, title, status, sub_agents?}]
    plan_steps_total: int
    plan_steps_completed: int

    # Orchestration
    next_agent: str
    requires_user_input: bool
    checkpoint_message: str
    checkpoint_prompt: str

    # Artifacts
    report_file_path: str
    data_file_path: str

    # UX telemetry
    reasoning: list[dict]  # [{step_name, step_text, verbose?}]
```

## 2) Node Output Contract

Every node should return only what changed.
Recommended minimum contract:

```json
{
  "reasoning": [{"step_name": "Agent", "step_text": "What happened"}],
  "requires_user_input": false,
  "next_agent": "supervisor"
}
```

Optional fields:
- `plan_tasks`, `plan_steps_total`, `plan_steps_completed`
- `checkpoint_message`, `checkpoint_prompt` (only when input is required)
- `messages` (AIMessage list)
- artifact fields (`report_file_path`, `data_file_path`)
- lifecycle fields (`analysis_complete`, `phase`)

## 3) Checkpoint Policy (Your Change #1)

Current issue:
- checkpoint logic is mixed into step progression and can force prompts where not needed.

Recommended rule:
- only decision nodes set `requires_user_input=True`.
- all other nodes must explicitly set `requires_user_input=False`.
- never rely on stale `checkpoint_message` in state. If a node does not need input, it should also clear:
  - `checkpoint_message=""`
  - `checkpoint_prompt=""`

Good checkpoint candidates:
- after data discovery (confirm scope/columns)
- after data slicing (confirm buckets/filters)
- after synthesis (confirm report direction)

Non-checkpoint nodes:
- friction fan-out
- critique
- reporting fan-out
- qa answer node

## 4) Recommended Graph Routing

Keep supervisor as control plane:

1. `supervisor` decides next step from `plan_steps_completed`, `analysis_complete`, and user response.
2. worker node runs and returns delta.
3. edge returns to `supervisor` unless worker is part of a fixed subgraph chain.

For your current mock graph:
- keep `friction -> synthesizer`
- keep `critique -> reporting`
- everything else can return to supervisor for deterministic routing.

## 5) Exact Node I/O Contracts (Current Graph)

### supervisor
Input:
- `plan_tasks`, `plan_steps_completed`, `analysis_complete`, `critique_enabled`
Output:
- always: `next_agent`, `requires_user_input`
- sometimes: initial `plan_tasks`, `plan_steps_total`, `reasoning`

### data_discovery
Input:
- dataset context (or uploaded file path in product)
Output:
- `reasoning`
- `plan_steps_completed=1`
- checkpoint fields and `requires_user_input=True`

### data_prep
Input:
- approved discovery + filters/slicing directives
Output:
- updated `plan_tasks`
- `plan_steps_completed=2`
- checkpoint fields and `requires_user_input=True`

### friction
Input:
- prepared bucket definitions
Output:
- multi-agent reasoning lines
- `plan_tasks` with `sub_agents`
- `plan_steps_completed=3`

### synthesizer
Input:
- friction outputs
Output:
- synthesis reasoning
- `plan_steps_completed=4`
- synthesis checkpoint (`requires_user_input=True`)

### critique (optional)
Input:
- synthesis/findings
Output:
- QA reasoning only

### reporting
Input:
- approved synthesis
Output:
- reporting reasoning
- `plan_steps_completed=5`
- completion message + `analysis_complete=True`
- artifact paths

### qa_agent
Input:
- analysis artifacts + user question
Output:
- answer message
- `requires_user_input=False`

## 6) Emulation Example (Exact from Your Current Mock)

Example node: `synthesizer`

Expected input snapshot:
```json
{
  "plan_steps_completed": 3,
  "plan_tasks": [
    {"id": "3", "title": "Friction Analysis", "status": "in_progress", "sub_agents": [{"id": "f1"}, {"id": "f2"}, {"id": "f3"}, {"id": "f4"}]}
  ],
  "requires_user_input": false
}
```

Actual output delta:
```json
{
  "reasoning": [
    {
      "step_name": "Synthesizer Agent",
      "step_text": "Merging 4 agent outputs. Top driver: 'Findability' (Impact x Ease: 8.5). Auth + Digital = 41% of total friction."
    }
  ],
  "requires_user_input": true,
  "checkpoint_message": "**Synthesis Complete**\\nDominant driver: **Findability** (Impact x Ease: 8.5). `Authentication + Digital` -> 41% of total friction.",
  "checkpoint_prompt": "Proceed to Report Generation?",
  "plan_tasks": [
    {"id": "3", "title": "Friction Analysis", "status": "done"},
    {"id": "4", "title": "Synthesis", "status": "in_progress"}
  ],
  "plan_steps_completed": 4
}
```

## 7) System Design Improvements (Your Change #2)

1. Add a typed `NodeDelta` model (Pydantic/TypedDict) to validate every node return.
2. Split control from payload:
   - control: `next_agent`, `requires_user_input`
   - payload: reasoning, tasks, artifacts, ai messages
3. Add `checkpoint_id` for UI resume safety (avoid replaying old prompts).
4. Add `last_completed_node` for reliable restart after disconnect.
5. Normalize status enums for tasks and sub_agents:
   - `todo | in_progress | done | blocked`

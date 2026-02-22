# Chainlit Blueprint (UI Contract for LangGraph)

## Goal
Create a UI that is fully driven by graph node deltas, with no node-specific branching in UI code.

## 1) UI Responsibilities

The UI should only do these jobs:

1. collect user input and files
2. stream graph updates
3. render three channels:
   - reasoning stream
   - plan/task progress
   - checkpoint prompts
4. surface final artifacts (report/data downloads)
5. persist thread + state for resume

## 2) Node Delta -> UI Mapping

Map each update generically:

- `reasoning` -> append lines into one collapsible "Reasoning" step
- `plan_tasks` -> sync `TaskList` parent + sub-agent rows
- `requires_user_input=True` -> show checkpoint block and stop auto-advance
- `messages` -> emit assistant chat messages
- `analysis_complete=True` + artifact paths -> show download elements

Important:
- when `requires_user_input=False`, remove old waiting indicator and ignore stale checkpoint text.

## 3) Checkpoint Rendering Rule (Your Change #1)

Render checkpoint only if:

```python
if node_output.get("requires_user_input", False):
    show_checkpoint(node_output["checkpoint_message"], node_output["checkpoint_prompt"])
else:
    hide_checkpoint()
```

Do not render based on `checkpoint_message` presence alone.

## 4) Minimal UI Flow

1. `on_chat_start`
   - init graph, thread_id, base state
   - render welcome
2. `on_message`
   - add `HumanMessage`
   - stream graph updates
   - update reasoning/tasks/checkpoint/downloads
   - persist state
3. `on_chat_resume`
   - restore state snapshot
   - show phase/progress
4. `on_settings_update`
   - set flags such as `critique_enabled`

## 5) Recommended State Hygiene in UI

Before each new run:
- clear transient checkpoint UI message
- keep persisted task list and reasoning history

After each node update:
- merge only returned keys (`state.update(node_output)`)
- if node explicitly sets `requires_user_input=False`, clear:
  - local waiting prompt handle
  - `state["checkpoint_message"]`
  - `state["checkpoint_prompt"]`

## 6) One Concrete End-to-End Example

When graph returns from `data_discovery`:

```json
{
  "reasoning": [{"step_name":"Data Analyst","step_text":"Loading dataset and extracting schema..."}],
  "requires_user_input": true,
  "checkpoint_message": "**Data Discovery Complete**\\nFound **300,412 records**...",
  "checkpoint_prompt": "Do you confirm this focus area?",
  "plan_steps_completed": 1
}
```

UI behavior:
1. append reasoning line under "Reasoning" step
2. show checkpoint message
3. show blinking waiting indicator with prompt text
4. wait for next user message to continue graph

When next update sets `requires_user_input=false`:
1. remove waiting indicator
2. continue streaming subsequent node updates

## 7) Suggested Implementation Improvements (Your Change #2)

1. Add `render_node_update(node_name, node_output)` function to isolate UI mapping logic.
2. Add a `UIEvent` adapter layer so future frontend migration is easy.
3. Add guardrail for duplicate checkpoint rendering by tracking `last_checkpoint_hash`.
4. Persist lightweight `ui_state`:
   - current step panel open/closed
   - last visible checkpoint id
5. Add snapshot test fixtures:
   - input node delta -> expected Chainlit calls

## 8) Product-Ready Two-File Boundary

For your current request, keep only:
- `app.py` as Chainlit runtime + rendering adapter
- `graph.py` as orchestration and node contracts

Everything else (tools/agents/components) can be introduced later without changing this boundary.

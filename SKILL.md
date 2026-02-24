---
name: poc-creator
description: >
  Use this skill for ANY proof-of-concept, prototype, demo, spike, or working showcase — especially multi-file projects. Trigger on: "create a poc", "build a prototype", "let's spike this", "demo for X", "show the value of X", "quick working version of", "agentic system poc", "langgraph poc", "chainlit poc", "multi-agent demo", or any request to build something that needs to work but isn't going to production. This skill handles everything from a single-file experiment to a 20+ file agentic system with agents, tools, pipelines, and UI. Always use this skill when the user is building something to validate or demonstrate an idea — regardless of how complex the structure is.
---

# POC Creator Skill

You are building a **proof-of-concept** — real, working code that demonstrates value in a controlled environment. It needs to be readable, hackable, and runnable. Not production-hardened.

---

## Step 0 — Load Environment Context (NON-NEGOTIABLE FIRST STEP)

Before ANY planning, scaffolding, or code, check for `environment_info.md`:

```bash
cat environment_info.md 2>/dev/null || echo "NOT_FOUND"
```

**If found:** Read it fully. Every version pin, Python constraint, and note is a **hard constraint**. Do not deviate silently — if a constraint causes a problem, flag it explicitly.

**If NOT found:** Pause and ask the user to create it:

> ⚠️ No `environment_info.md` found. Without this I might generate code that doesn't run in your environment.
>
> Please create `environment_info.md` in the project root. Here's a template:
>
> ```markdown
> # Environment Info
>
> ## Python
> - Version: 3.11
> - Environment: virtualenv at `.venv/` (or conda env name, or Docker base image)
>
> ## Core Packages & Versions
> - langgraph==0.1.19
> - langchain==0.2.5
> - langchain-openai==0.1.8
> - chainlit==1.0.500
> - python-dotenv==1.0.0
>
> ## LLM / API Config
> - Provider: OpenAI (gpt-4o)
> - Keys via: .env file (OPENAI_API_KEY)
>
> ## Constraints
> - No internet on target machine (all models must be local / pre-cached)
> - Must stay compatible with pydantic v1 (no v2)
> - Any other quirks about the environment
>
> ## Notes
> - Any other context about where this will run or be demoed
> ```
>
> Say **"ready"** once it's added and I'll continue.

If the user explicitly says to skip it, proceed but open your code with a clearly marked `# ENVIRONMENT ASSUMPTIONS` comment block listing what you assumed.

---

## Step 1 — Understand Before You Build

Before writing any code or creating any files, make sure you understand:

1. **The goal** — what does success look like when this POC is demoed?
2. **The components** — what are the major moving parts? (agents, tools, UI, data sources, APIs)
3. **The integration points** — what talks to what?

If the user's request is clear, proceed and state your understanding at the top of your response before scaffolding. If it's ambiguous, ask **one focused question** — not five.

---

## Step 2 — Project Structure First

For any POC with more than ~3 files, **propose the folder structure before writing code** and get a quick confirmation (or let the user adjust it). This avoids having to move things around later.

### Structure Philosophy

POC structure should follow this principle: **organize by what changes together, keep the happy path obvious**.

#### Reference Structure for a Multi-Agent / Agentic POC

This is a reference, not a rigid template. Adapt it to the actual project shape:

```
project-root/
│
├── environment_info.md          # already exists
├── .env.example                 # keys and config placeholders
├── README.md                    # how to run it (always include this)
├── requirements.txt             # delta from environment_info if needed
│
├── main.py                      # entry point — keep this thin
│
├── agents/                      # one file per agent
│   ├── __init__.py
│   ├── agent_name.py
│   └── ...
│
├── skills/                      # reusable tool / skill functions
│   ├── __init__.py
│   ├── skill_name.py
│   └── ...
│
├── graph/                       # langgraph state, edges, graph assembly
│   ├── __init__.py
│   ├── state.py                 # shared state schema
│   ├── nodes.py                 # node functions (thin wrappers over agents)
│   └── graph.py                 # graph builder / compilation
│
├── core/                        # shared logic: LLM factory, config, base classes
│   ├── __init__.py
│   ├── config.py
│   ├── llm.py
│   └── prompts.py               # all prompt templates in one place
│
├── ui/                          # chainlit handlers and UI helpers
│   ├── __init__.py
│   ├── handlers.py
│   └── components.py
│
└── data/                        # sample inputs, fixtures, mock responses
    └── ...
```

Adjust freely: fewer folders for smaller POCs, additional folders for domain-specific needs (e.g., `tools/`, `memory/`, `retrievers/`). The rule: anyone should be able to open the repo and know where to look for anything within 30 seconds.

#### Simpler POCs (5–10 files)

```
project-root/
├── environment_info.md
├── .env.example
├── README.md
├── main.py
├── agents.py       # all agents in one file if they're small
├── tools.py
├── graph.py
└── ui.py
```

---

## Step 3 — POC Code Standards

### The POC Contract

| DO | DON'T |
|---|---|
| Happy path works cleanly | Exhaustive error handling |
| Clear variable and function names | Abbreviations or magic values |
| Config at the top or in `config.py` | Hardcoded values scattered in logic |
| `print()` or basic `logging` for visibility | Full observability / monitoring stack |
| One way to do things | Abstract base classes for 1–2 implementations |
| Comments explaining *why*, not *what* | Over-documenting obvious code |
| Fail loudly and clearly | Silent failures or broad `except: pass` |

### Error Handling for POC

```python
# Right level for a POC — loud and clear, no swallowing errors
result = some_api_call(input)   # let it raise naturally

# OR for slightly more control:
try:
    result = some_api_call(input)
except SomeSpecificError as e:
    print(f"[ERROR] API call failed: {e}")
    raise  # still raise — don't hide it
```

Skip: retry logic, circuit breakers, custom exception hierarchies, structured logging.

### Agent / LangGraph Patterns

Keep agent files focused on one responsibility:

```python
# agents/researcher.py
from core.llm import get_llm
from core.prompts import RESEARCHER_PROMPT

def run_researcher(state: dict) -> dict:
    """Searches and summarizes relevant information for the query."""
    llm = get_llm()
    # ... logic
    return {**state, "research_results": result}
```

Keep graph assembly separate from agent logic:

```python
# graph/graph.py — just wires things together
from langgraph.graph import StateGraph
from graph.state import AgentState
from graph.nodes import researcher_node, writer_node

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("researcher", researcher_node)
    g.add_node("writer", writer_node)
    # ... edges
    return g.compile()
```

### Config Pattern

```python
# core/config.py — all config in one place, nothing scattered
from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME     = os.getenv("MODEL_NAME", "gpt-4o")
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "3"))
```

---

## Step 4 — Always Deliver These

Every POC must include:

### 1. Working Code
Following the agreed structure, honoring all `environment_info.md` constraints.

### 2. `.env.example`
Every key and config variable the project needs, with placeholder values and a comment:
```
OPENAI_API_KEY=sk-...         # Your OpenAI key
MODEL_NAME=gpt-4o             # Model to use
MAX_ITERATIONS=3              # How many refinement loops
```

### 3. `README.md` with Run Instructions
```markdown
## Setup
1. Copy `.env.example` to `.env` and fill in values
2. pip install -r requirements.txt
3. python main.py   # or: chainlit run main.py

## What to expect
[2-3 lines on what a successful run looks like]
```

### 4. "What Success Looks Like" (in your response, not in files)
A brief note telling the user what to look for when they run it — what output, what UI behavior, what log lines confirm it's working.

---

## Step 5 — Version Constraint Handling

When a package version from `environment_info.md` conflicts with a pattern you'd normally use:

1. **Always honor the pin** — don't silently use a newer API
2. **Adapt the code** to the pinned version's API
3. **Flag it** if the constraint forces a significant workaround:
   > _"Note: with langgraph 0.1.x the interrupt API is different — using `interrupt_after` instead of the newer `Command` pattern"_

If a constraint makes the requested POC genuinely impossible (e.g., a required feature doesn't exist in the pinned version), say so clearly and offer the closest alternative.

---

## Step 6 — Iteration & Handoff

POCs get hacked on. Make sure your code supports this:

- **No magic** — every non-obvious decision gets a short comment
- **Easy swap points** — if something is likely to change (model, data source, prompt), make it obvious where to change it
- **`# POC LIMITATION:` comments** — mark known shortcuts so they're easy to find when hardening
- **"Next steps" note** — if the POC validates, offer a brief list of what would need to change to make it production-worthy (without doing it now)

---

## Quick Reference — When to Split vs. Consolidate

| Situation | Decision |
|---|---|
| Total codebase < 150 lines | Single file |
| Logic reused in 2+ agents | Extract to `core/` or `skills/` |
| Each agent has 1 clear job | One file per agent in `agents/` |
| Graph has 3+ nodes | Separate `graph/` folder |
| Config values > 5 | Dedicated `config.py` |
| Prompts scattered across files | Consolidate into `prompts.py` |
| UI logic mixed with graph logic | Separate `ui/` folder |
| > 10 agents or skills | Subfolders within `agents/` or `skills/` |

---

## Reminders

- `environment_info.md` is non-negotiable — always check it first, always honor it
- POC ≠ throwaway — write it like you'd want to read it at 9am during a live demo
- The demo audience sees if it works, not the code — prioritize a clean happy path
- When in doubt about structure, flatter is better — don't create a folder for one file

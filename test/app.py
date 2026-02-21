"""AgenticAnalytics — Chainlit App Framework (single-file).

A clean, plug-and-play Chainlit shell for any LangGraph graph.
Swap ``graph.py`` to switch between mock and production graphs.

Run: uv run chainlit run app.py

== GRAPH CONTRACT ==
Each node_output dict may contain:
  reasoning           : list[dict]  — [{step_name, step_text, verbose?}]
  plan_tasks           : list[dict]  — [{id, title, status}]  status ∈ {todo, in_progress, done}
  plan_steps_total     : int
  plan_steps_completed : int
  requires_user_input  : bool
  checkpoint_message   : str
  messages             : list[AIMessage]
  analysis_complete    : bool
  report_file_path     : str
  data_file_path       : str
"""
from __future__ import annotations

import json, os, uuid, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

import chainlit as cl
from chainlit.data import BaseDataLayer
from chainlit.step import StepDict
from chainlit.types import (
    Feedback,
    PageInfo,
    PaginatedResponse,
    Pagination,
    ThreadDict,
    ThreadFilter,
)
from chainlit.user import PersistedUser, User
from langchain_core.messages import HumanMessage

from graph import build_graph

# ══════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════
VERBOSE = False
# Ensure auth secret is long enough (32+ bytes)
if len(os.environ.get("CHAINLIT_AUTH_SECRET", "")) < 32:
    os.environ["CHAINLIT_AUTH_SECRET"] = os.environ.get("CHAINLIT_AUTH_SECRET", "dev").ljust(32, "0")

STORAGE_DIR = Path(".data")
THREADS_DIR = STORAGE_DIR / "threads"
USERS_DIR   = STORAGE_DIR / "users"
STATES_DIR  = STORAGE_DIR / "states"

for d in (THREADS_DIR, USERS_DIR, STATES_DIR):
    d.mkdir(parents=True, exist_ok=True)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════
# File-based Data Layer (enables chat history sidebar)
# ══════════════════════════════════════════════════════════════════════


class FileDataLayer(BaseDataLayer):
    """JSON-file backed data layer — no database required."""

    # ── Users ─────────────────────────────────────────────────────────
    async def get_user(self, identifier: str) -> Optional[PersistedUser]:
        p = USERS_DIR / f"{identifier}.json"
        if not p.exists():
            return None
        return PersistedUser(**json.loads(p.read_text("utf-8")))

    async def create_user(self, user: User) -> Optional[PersistedUser]:
        pu = PersistedUser(
            id=str(uuid.uuid4()),
            identifier=user.identifier,
            createdAt=_now_iso(),
            metadata=user.metadata or {},
        )
        (USERS_DIR / f"{user.identifier}.json").write_text(
            json.dumps({"id": pu.id, "identifier": pu.identifier,
                        "createdAt": pu.createdAt, "metadata": pu.metadata}, default=str),
            "utf-8",
        )
        return pu

    # ── Threads ───────────────────────────────────────────────────────
    def _tp(self, tid: str) -> Path:
        return THREADS_DIR / f"{tid}.json"

    def _load(self, tid: str) -> dict | None:
        p = self._tp(tid)
        return json.loads(p.read_text("utf-8")) if p.exists() else None

    def _save(self, d: dict) -> None:
        self._tp(d["id"]).write_text(json.dumps(d, default=str), "utf-8")

    async def get_thread(self, thread_id: str) -> Optional[ThreadDict]:
        d = self._load(thread_id)
        if not d:
            return None
        return ThreadDict(
            id=d["id"], createdAt=d.get("createdAt", ""),
            name=d.get("name"), userId=d.get("userId"),
            userIdentifier=d.get("userIdentifier"),
            tags=d.get("tags"), metadata=d.get("metadata"),
            steps=d.get("steps", []), elements=d.get("elements"),
        )

    async def get_thread_author(self, thread_id: str) -> str:
        d = self._load(thread_id)
        return d.get("userIdentifier", "") if d else ""

    def _resolve_user_identifier(self, user_id: str) -> str:
        """Look up userIdentifier from userId by scanning saved users."""
        for p in USERS_DIR.glob("*.json"):
            try:
                u = json.loads(p.read_text("utf-8"))
                if u.get("id") == user_id:
                    return u.get("identifier", "")
            except (json.JSONDecodeError, OSError):
                continue
        return ""

    async def update_thread(self, thread_id: str, name=None, user_id=None,
                            metadata=None, tags=None) -> None:
        d = self._load(thread_id) or {"id": thread_id, "createdAt": _now_iso(),
                                       "steps": [], "elements": []}
        if name is not None:     d["name"] = name
        if user_id is not None:
            d["userId"] = user_id
            identifier = self._resolve_user_identifier(user_id)
            if identifier:
                d["userIdentifier"] = identifier
        if metadata is not None: d["metadata"] = metadata
        if tags is not None:     d["tags"] = tags
        self._save(d)

    async def delete_thread(self, thread_id: str) -> None:
        p = self._tp(thread_id)
        if p.exists():
            p.unlink()

    async def list_threads(self, pagination: Pagination,
                           filters: ThreadFilter) -> PaginatedResponse[ThreadDict]:
        all_t: list[dict] = []
        for p in THREADS_DIR.glob("*.json"):
            try:
                d = json.loads(p.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if filters.userId and d.get("userId") != filters.userId:
                continue
            if filters.search and filters.search.lower() not in (d.get("name") or "").lower():
                continue
            all_t.append(d)
        all_t.sort(key=lambda t: t.get("createdAt", ""), reverse=True)

        start = 0
        if pagination.cursor:
            for i, t in enumerate(all_t):
                if t["id"] == pagination.cursor:
                    start = i + 1
                    break
        page = all_t[start:start + pagination.first]
        has_next = (start + pagination.first) < len(all_t)
        threads = [
            ThreadDict(id=d["id"], createdAt=d.get("createdAt", ""),
                       name=d.get("name"), userId=d.get("userId"),
                       userIdentifier=d.get("userIdentifier"),
                       tags=d.get("tags"), metadata=d.get("metadata"),
                       steps=d.get("steps", []), elements=d.get("elements"))
            for d in page
        ]
        return PaginatedResponse(
            pageInfo=PageInfo(hasNextPage=has_next,
                              startCursor=page[0]["id"] if page else None,
                              endCursor=page[-1]["id"] if page else None),
            data=threads,
        )

    # ── Steps ─────────────────────────────────────────────────────────
    async def create_step(self, step_dict: StepDict) -> None:
        tid = step_dict.get("threadId", "")
        if not tid:
            return
        d = self._load(tid) or {"id": tid, "createdAt": _now_iso(), "steps": [], "elements": []}
        d["steps"].append(dict(step_dict))
        self._save(d)

    async def update_step(self, step_dict: StepDict) -> None:
        tid = step_dict.get("threadId", "")
        if not tid:
            return
        d = self._load(tid)
        if not d:
            return
        sid = step_dict.get("id")
        for i, s in enumerate(d.get("steps", [])):
            if s.get("id") == sid:
                d["steps"][i] = dict(step_dict)
                break
        else:
            d["steps"].append(dict(step_dict))
        self._save(d)

    async def delete_step(self, step_id: str) -> None:
        for p in THREADS_DIR.glob("*.json"):
            try:
                d = json.loads(p.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            orig = len(d.get("steps", []))
            d["steps"] = [s for s in d.get("steps", []) if s.get("id") != step_id]
            if len(d["steps"]) < orig:
                self._save(d)
                return

    # ── Elements ──────────────────────────────────────────────────────
    async def create_element(self, element: Any) -> None:
        tid = getattr(element, "thread_id", None) or getattr(element, "threadId", "")
        if not tid:
            return
        d = self._load(tid)
        if not d:
            return
        if d.get("elements") is None:
            d["elements"] = []
        d["elements"].append({
            "id": getattr(element, "id", str(uuid.uuid4())),
            "type": getattr(element, "type", ""),
            "name": getattr(element, "name", ""),
            "threadId": tid,
        })
        self._save(d)

    async def get_element(self, thread_id: str, element_id: str) -> Optional[dict]:
        d = self._load(thread_id)
        if not d:
            return None
        for el in d.get("elements", []) or []:
            if el.get("id") == element_id:
                return el
        return None

    async def delete_element(self, element_id: str, thread_id=None) -> None:
        if not thread_id:
            return
        d = self._load(thread_id)
        if d and d.get("elements"):
            d["elements"] = [e for e in d["elements"] if e.get("id") != element_id]
            self._save(d)

    # ── Feedback ──────────────────────────────────────────────────────
    async def upsert_feedback(self, feedback: Feedback) -> str:
        return feedback.id or str(uuid.uuid4())

    async def delete_feedback(self, feedback_id: str) -> bool:
        return True

    async def get_favorite_steps(self, user_id: str) -> List[StepDict]:
        return []

    # ── Misc ──────────────────────────────────────────────────────────
    async def build_debug_url(self) -> str:
        return ""

    async def close(self) -> None:
        pass


# ══════════════════════════════════════════════════════════════════════
# Authentication (required for chat history sidebar)
# ══════════════════════════════════════════════════════════════════════


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    """Accept any credentials for local dev. Replace for production."""
    return cl.User(
        identifier=username,
        metadata={"role": "admin", "provider": "credentials"},
    )


@cl.data_layer
def get_data_layer():
    return FileDataLayer()


# ══════════════════════════════════════════════════════════════════════
# Session state persistence
# ══════════════════════════════════════════════════════════════════════


async def save_state(thread_id: str, state: dict) -> None:
    """Save serializable subset of analysis state."""
    safe = {}
    for k, v in state.items():
        if k == "messages":
            continue
        try:
            json.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            pass
    safe["thread_id"] = thread_id
    safe["saved_at"] = _now_iso()
    (STATES_DIR / f"{thread_id}.json").write_text(
        json.dumps(safe, indent=2), "utf-8"
    )


async def load_state(thread_id: str) -> dict | None:
    p = STATES_DIR / f"{thread_id}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else None


# ══════════════════════════════════════════════════════════════════════
# UI Helpers
# ══════════════════════════════════════════════════════════════════════

def _task_status(s: str) -> cl.TaskStatus:
    return {"in_progress": cl.TaskStatus.RUNNING,
            "done": cl.TaskStatus.DONE}.get(s, cl.TaskStatus.READY)

def _sub_title(a: dict) -> str:
    detail = a.get("detail", "")
    return f"  ↳ {a['title']}" + (f"  —  {detail}" if detail else "")


async def sync_task_list(tl: cl.TaskList | None, tasks: list[dict]) -> cl.TaskList:
    """Create or update the sidebar TaskList, flattening sub_agents as indented children.

    Each plan_task may include an optional ``sub_agents`` list::

        {"id": "3", "title": "Friction Analysis", "status": "in_progress",
         "sub_agents": [
             {"id": "f1", "title": "Digital Friction Agent", "status": "in_progress"},
             ...
         ]}

    Sub-agents are inserted right after their parent with an ↳ prefix.
    """
    if tl is None:
        tl = cl.TaskList()
        tl.status = "Running"
        for t in tasks:
            await tl.add_task(cl.Task(title=t["title"],
                                      status=_task_status(t.get("status", "todo"))))
            for a in t.get("sub_agents", []):
                await tl.add_task(cl.Task(title=_sub_title(a),
                                          status=_task_status(a.get("status", "todo"))))
        await tl.send()
    else:
        # Build lookup by display title (both parent and sub-items)
        by_title = {task.title: task for task in tl.tasks}
        for t in tasks:
            st = _task_status(t.get("status", "todo"))
            if t["title"] in by_title:
                by_title[t["title"]].status = st
            else:
                await tl.add_task(cl.Task(title=t["title"], status=st))
                by_title[t["title"]] = tl.tasks[-1]
            for a in t.get("sub_agents", []):
                sub_key = _sub_title(a)
                sub_st  = _task_status(a.get("status", "todo"))
                # Update title too (detail text may have been added)
                if any(task.title.startswith(f"  ↳ {a['title']}") for task in tl.tasks):
                    for task in tl.tasks:
                        if task.title.startswith(f"  ↳ {a['title']}"):
                            task.title  = sub_key
                            task.status = sub_st
                else:
                    await tl.add_task(cl.Task(title=sub_key, status=sub_st))
        await tl.send()
    return tl


async def send_awaiting_input(prompt: str) -> cl.Message:
    """Send a blinking prompt that can be removed later."""
    html = (
        f'<div class="awaiting-input">'
        f'<span class="pulse-dot"></span> '
        f'{prompt}'
        f'</div>'
    )
    m = cl.Message(content=html)
    await m.send()
    return m


async def send_downloads(report_path: str, data_path: str) -> None:
    tmp = tempfile.mkdtemp()
    rpt = os.path.join(tmp, os.path.basename(report_path))
    with open(rpt, "w") as f:
        f.write("[Placeholder] PPTX report content.")
    dat = os.path.join(tmp, os.path.basename(data_path))
    with open(dat, "w") as f:
        f.write("col_a,col_b,col_c\n1,2,3\n4,5,6\n")
    await cl.Message(
        content="📥 **Your files are ready for download:**",
        elements=[
            cl.File(name=os.path.basename(rpt), path=rpt, display="inline"),
            cl.File(name=os.path.basename(dat), path=dat, display="inline"),
        ],
    ).send()


# ══════════════════════════════════════════════════════════════════════
# Initial State
# ══════════════════════════════════════════════════════════════════════

def make_initial_state() -> dict[str, Any]:
    return {
        "messages": [],
        "critique_enabled": False,
        "plan_steps_total": 0,
        "plan_steps_completed": 0,
        "plan_tasks": [],
        "requires_user_input": False,
        "checkpoint_message": "",
        "phase": "analysis",
        "analysis_complete": False,
        "reasoning": [],
        "report_file_path": "",
        "data_file_path": "",
        "next_agent": "",
    }


# ══════════════════════════════════════════════════════════════════════
# Chainlit Lifecycle
# ══════════════════════════════════════════════════════════════════════


@cl.on_chat_start
async def on_chat_start():
    thread_id = str(uuid.uuid4())
    graph = build_graph()

    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("state", make_initial_state())
    cl.user_session.set("task_list", None)
    cl.user_session.set("squad_list", None)
    cl.user_session.set("awaiting_prompt", None)

    await cl.Message(
        content=(
            "## 👋 Welcome to AgenticAnalytics\n\n"
            "Upload a CSV or send a message to begin your analysis.\n\n"
            "The system will guide you through **data discovery → friction analysis → reporting** "
            "with checkpoints for your review at each stage."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    graph     = cl.user_session.get("graph")
    state     = cl.user_session.get("state")
    thread_id = cl.user_session.get("thread_id")

    # Handle file uploads
    if message.elements:
        for el in message.elements:
            if hasattr(el, "path") and el.path:
                state["dataset_path"] = el.path
                break
    user_text = message.content or "Proceed"

    # Remove previous blinking prompt if it exists
    prev_prompt: cl.Message | None = cl.user_session.get("awaiting_prompt")
    if prev_prompt:
        await prev_prompt.remove()
        cl.user_session.set("awaiting_prompt", None)

    state["messages"].append(HumanMessage(content=user_text))
    config = {"configurable": {"thread_id": thread_id}}
    task_list: cl.TaskList | None = cl.user_session.get("task_list")

    # Single collapsible Reasoning step
    reasoning_step = cl.Step(name="Reasoning", type="run")
    reasoning_step.output = ""
    await reasoning_step.send()

    try:
        try:
            async for event in graph.astream(state, config=config, stream_mode="updates"):
                for node_name, node_output in event.items():
                    if node_name == "__end__":
                        continue

                    # Append reasoning lines
                    for r in node_output.get("reasoning", []):
                        if r.get("verbose") and not VERBOSE:
                            continue
                        reasoning_step.output += f"**{r.get('step_name', node_name)}**: {r.get('step_text', '')}\n\n"
                    await reasoning_step.update()

                    # Sync plan task list (sub_agents embedded inside each task)
                    new_tasks = node_output.get("plan_tasks")
                    if new_tasks is not None:
                        task_list = await sync_task_list(task_list, new_tasks)
                        cl.user_session.set("task_list", task_list)

                    # Checkpoint: awaiting user input
                    if node_output.get("requires_user_input"):
                        info = node_output.get("checkpoint_message", "")
                        prompt = node_output.get("checkpoint_prompt", "Please provide input to continue.")
                        if info:
                            await cl.Message(content=info).send()
                        prompt_msg = await send_awaiting_input(prompt)
                        cl.user_session.set("awaiting_prompt", prompt_msg)

                    # Surface AI messages
                    for msg in node_output.get("messages", []):
                        if hasattr(msg, "content") and msg.content and getattr(msg, "type", "") == "ai":
                            content = msg.content
                            if isinstance(content, list):
                                content = " ".join(
                                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                                )
                            if content:
                                await cl.Message(content=content).send()

                    # Merge into local state
                    state.update(node_output)
        except GeneratorExit:
            pass  # Stream interrupted (e.g. disconnect) — safe to ignore

        # Finalise reasoning step
        reasoning_step.status = "success"
        await reasoning_step.update()

        # Post-analysis: downloads + Q&A transition
        if state.get("analysis_complete"):
            await send_downloads(
                state.get("report_file_path", "report.pptx"),
                state.get("data_file_path", "data.csv"),
            )
            if task_list:
                done = [{**t, "status": "done"} for t in state.get("plan_tasks", [])]
                task_list = await sync_task_list(task_list, done)
                task_list.status = "Done"
                await task_list.send()
                cl.user_session.set("task_list", task_list)

            state["phase"] = "qa"
            await cl.Message(
                content="---\n✅ **Analysis complete!** Ask follow-up questions or start a new chat."
            ).send()

    except Exception as exc:
        await cl.Message(content=f"⚠️ **Error**: {exc}", author="System").send()

    cl.user_session.set("state", state)
    await save_state(thread_id, state)


@cl.on_settings_update
async def on_settings_update(settings: dict):
    if "critique_enabled" in settings:
        cl.user_session.set("critique_enabled", settings["critique_enabled"])
        label = "enabled" if settings["critique_enabled"] else "disabled"
        await cl.Message(content=f"Critique mode **{label}**.", author="System").send()


@cl.on_chat_resume
async def on_chat_resume(thread: dict):
    thread_id = thread.get("id", "")
    saved = await load_state(thread_id)

    state = make_initial_state()
    graph = build_graph()
    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("task_list", None)
    cl.user_session.set("squad_list", None)
    cl.user_session.set("awaiting_prompt", None)

    if saved:
        state.update(saved)
        cl.user_session.set("state", state)

        phase = saved.get("phase", "analysis")
        completed = saved.get("plan_steps_completed", 0)
        total = saved.get("plan_steps_total", 0)
        parts = [f"**Phase:** {phase}"]
        if total > 0:
            parts.append(f"**Progress:** {completed}/{total} steps")

        await cl.Message(
            content="## Session Resumed\n\n" + " | ".join(parts) +
                    "\n\nContinue where you left off."
        ).send()
    else:
        cl.user_session.set("state", state)
        await cl.Message(content="Could not restore session. Starting fresh.", author="System").send()


@cl.on_chat_end
async def on_chat_end():
    pass

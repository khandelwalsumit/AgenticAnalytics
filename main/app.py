"""Chainlit application entry point.

Run with: chainlit run app.py

== GRAPH CONTRACT ==
Each node_output dict may contain:
  reasoning           : list[dict]  - [{step_name, step_text, verbose?}]
  plan_tasks          : list[dict]  - [{id, title, status, sub_agents?}]
  plan_steps_total     : int
  plan_steps_completed : int
  requires_user_input  : bool
  checkpoint_message   : str
  checkpoint_prompt    : str
  checkpoint_token     : str
  pending_input_for    : str
  node_io              : dict
  io_trace             : list[dict]
  messages             : list[AIMessage]
  analysis_complete    : bool
  report_file_path     : str
  data_file_path       : str
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

import chainlit as cl
from chainlit.input_widget import MultiSelect
from langchain_core.messages import HumanMessage

from agents.graph import build_graph
from config import AGENTS_DIR, CACHE_DIR, DATA_DIR, VERBOSE
from core.agent_factory import AgentFactory
from core.data_store import DataStore
from core.file_data_layer import FileDataLayer
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY, set_analysis_deps
from tools.data_tools import set_data_store as set_data_tools_store
from tools.report_tools import set_data_store as set_report_tools_store
from ui.chat_history import load_analysis_state, save_analysis_state
from ui.components import (
    clear_awaiting_prompt,
    send_awaiting_input,
    send_downloads,
    sync_task_list,
)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

FRICTION_AGENT_IDS = [
    "digital_friction_agent",
    "operations_agent",
    "communication_agent",
    "policy_agent",
]

AGENT_ID_TO_LABEL = {
    "digital_friction_agent": "Digital Friction Agent",
    "operations_agent": "Operations Agent",
    "communication_agent": "Communication Agent",
    "policy_agent": "Policy Agent",
    "critique": "Critique",
}
AGENT_ITEMS = {label: agent_id for agent_id, label in AGENT_ID_TO_LABEL.items()}
AGENT_LABEL_TO_ID = {label: agent_id for label, agent_id in AGENT_ITEMS.items()}

DEFAULT_SELECTED_AGENTS = list(FRICTION_AGENT_IDS)

# Ensure auth secret is long enough (32+ bytes)
if len(os.environ.get("CHAINLIT_AUTH_SECRET", "")) < 32:
    os.environ["CHAINLIT_AUTH_SECRET"] = os.environ.get("CHAINLIT_AUTH_SECRET", "dev").ljust(32, "0")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _active_chainlit_thread_id() -> str:
    """Best-effort access to the current Chainlit thread identifier."""
    try:
        thread_id = getattr(cl.context.session, "thread_id", "")
    except Exception:
        thread_id = ""
    return thread_id if isinstance(thread_id, str) else ""


def _normalize_selected_agents(raw: Any, *, default_if_missing: bool) -> list[str]:
    """Normalize selected_agents payload to internal agent IDs."""
    if raw is None:
        return list(DEFAULT_SELECTED_AGENTS) if default_if_missing else []
    if not isinstance(raw, list):
        return list(DEFAULT_SELECTED_AGENTS) if default_if_missing else []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            continue
        agent_id = value if value in AGENT_ID_TO_LABEL else AGENT_LABEL_TO_ID.get(value, "")
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            normalized.append(agent_id)

    if normalized:
        return normalized
    if not raw:
        return []
    return list(DEFAULT_SELECTED_AGENTS) if default_if_missing else []


async def _send_agent_settings(initial_selected: list[str]) -> None:
    normalized_initial = _normalize_selected_agents(initial_selected, default_if_missing=True)
    await cl.ChatSettings(
        [
            MultiSelect(
                id="selected_agents",
                label="Session Agents",
                initial=list(normalized_initial),
                items=AGENT_ITEMS,
                description="Only selected agents run in friction/critique subgraphs for this session.",
            )
        ]
    ).send()


def _apply_selection_to_state(state: dict[str, Any], selected_agents: list[str]) -> None:
    state["selected_agents"] = list(selected_agents)
    state["selected_friction_agents"] = [a for a in selected_agents if a in FRICTION_AGENT_IDS]
    state["critique_enabled"] = "critique" in selected_agents


def _clear_checkpoint_state(state: dict[str, Any]) -> None:
    state["checkpoint_message"] = ""
    state["checkpoint_prompt"] = ""
    state["checkpoint_token"] = ""
    state["pending_input_for"] = ""


def _message_text(msg: Any) -> str:
    if not hasattr(msg, "content") or not msg.content or getattr(msg, "type", "") != "ai":
        return ""
    content = msg.content
    if isinstance(content, list):
        return " ".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content)


async def _send_notification(message: str, level: str = "info") -> None:
    """Send an ephemeral UI toast (non-chat) with safe fallback."""
    try:
        result = cl.context.emitter.send_toast(message=message, type=level)
        if inspect.isawaitable(result):
            await result
    except Exception:
        await cl.Message(content=message, author="System").send()


def _should_restore_downloads(state: dict[str, Any]) -> bool:
    if state.get("analysis_complete"):
        return True
    if str(state.get("phase", "")).lower() == "qa":
        return True
    if state.get("report_file_path") or state.get("data_file_path"):
        return True
    return False


async def _send_resume_downloads_after_restore(state: dict[str, Any], delay_s: float = 0.8) -> None:
    """Send downloads after resume hydration to avoid message replacement."""
    try:
        await cl.sleep(delay_s)
        if not _should_restore_downloads(state):
            return
        await send_downloads(
            state.get("report_file_path") or "report.pptx",
            state.get("data_file_path") or "filtered_data.csv",
        )
    except Exception:
        await _send_notification("Could not re-render downloads on resume.", level="warning")


def _runtime_flags_from_text(text: str) -> dict[str, Any]:
    """Parse lightweight runtime controls from a user message.

    Supported:
    - /inject timeout
    - /inject auth
    - /inject token
    - /auto on
    - /auto off
    """
    flags: dict[str, Any] = {}
    parts = (text or "").strip().lower().split()
    if len(parts) >= 2 and parts[0] == "/inject":
        kind = parts[1]
        if kind in {"timeout", "auth", "token"}:
            flags["fault_injection"] = {
                "next_error": kind,
                "target": parts[2] if len(parts) >= 3 else "any",
            }
    if len(parts) >= 2 and parts[0] == "/auto":
        if parts[1] in {"on", "true", "1"}:
            flags["auto_approve_checkpoints"] = True
        elif parts[1] in {"off", "false", "0"}:
            flags["auto_approve_checkpoints"] = False
    return flags


# ------------------------------------------------------------------
# Runtime setup
# ------------------------------------------------------------------


def _create_runtime() -> tuple[str, DataStore, Any]:
    """Build per-session runtime dependencies."""
    session_id = str(uuid.uuid4())[:12]
    data_store = DataStore(session_id=session_id, cache_dir=str(CACHE_DIR))

    set_data_tools_store(data_store)
    set_report_tools_store(data_store)

    skill_loader = SkillLoader()
    set_analysis_deps(data_store, skill_loader)
    agent_factory = AgentFactory(definitions_dir=AGENTS_DIR, tool_registry=TOOL_REGISTRY)
    graph = build_graph(agent_factory=agent_factory, skill_loader=skill_loader)
    return session_id, data_store, graph


def make_initial_state() -> dict[str, Any]:
    return {
        "messages": [],
        "user_focus": "",
        "analysis_type": "",
        "selected_skills": [],
        "critique_enabled": False,
        "selected_agents": list(DEFAULT_SELECTED_AGENTS),
        "selected_friction_agents": list(DEFAULT_SELECTED_AGENTS),
        "auto_approve_checkpoints": False,
        "current_plan": {},
        "plan_steps_total": 0,
        "plan_steps_completed": 0,
        "plan_tasks": [],
        "requires_user_input": False,
        "checkpoint_message": "",
        "checkpoint_prompt": "",
        "checkpoint_token": "",
        "pending_input_for": "",
        "phase": "analysis",
        "analysis_complete": False,
        "execution_trace": [],
        "reasoning": [],
        "node_io": {},
        "io_trace": [],
        "last_completed_node": "",
        "dataset_path": "",
        "dataset_schema": {},
        "active_filters": {},
        "data_buckets": {},
        "findings": [],
        "domain_analysis": {},
        "operational_analysis": {},
        "digital_analysis": {},
        "operations_analysis": {},
        "communication_analysis": {},
        "policy_analysis": {},
        "synthesis_result": {},
        "narrative_output": {},
        "dataviz_output": {},
        "formatting_output": {},
        "report_markdown_key": "",
        "report_file_path": "",
        "data_file_path": "",
        "critique_feedback": {},
        "quality_score": 0.0,
        "next_agent": "",
        "analysis_scope": {
            "dataset_path": "",
            "filters": {},
            "skills_used": [],
            "buckets_created": [],
            "focus_column": "",
        },
        "error_count": 0,
        "recoverable_error": "",
        "fault_injection": {"next_error": "", "target": "any"},
    }


def _setup_runtime_session(thread_id: str, state: dict[str, Any]) -> None:
    """Store runtime objects/state in Chainlit user session."""
    session_id, data_store, graph = _create_runtime()
    cl.user_session.set("graph", graph)
    cl.user_session.set("data_store", data_store)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("state", state)
    cl.user_session.set("task_list", None)
    cl.user_session.set("awaiting_prompt", None)


# ------------------------------------------------------------------
# Authentication (required for chat history sidebar)
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# Chainlit Lifecycle
# ------------------------------------------------------------------


@cl.on_chat_start
async def on_chat_start():
    thread_id = _active_chainlit_thread_id() or str(uuid.uuid4())
    state = make_initial_state()
    _setup_runtime_session(thread_id, state)
    cl.user_session.set("selected_agents", list(DEFAULT_SELECTED_AGENTS))
    cl.user_session.set("critique_enabled", False)
    _apply_selection_to_state(state, list(DEFAULT_SELECTED_AGENTS))
    await _send_agent_settings(list(DEFAULT_SELECTED_AGENTS))

    await cl.Message(
        content=(
            "## Welcome to AgenticAnalytics\n\n"
            "Upload a CSV or send a message to begin your analysis.\n\n"
            "The system will guide you through **data discovery -> friction analysis -> reporting** "
            "with checkpoints for your review at each stage."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    graph = cl.user_session.get("graph")
    state = cl.user_session.get("state") or make_initial_state()
    thread_id = cl.user_session.get("thread_id") or _active_chainlit_thread_id()
    if thread_id:
        cl.user_session.set("thread_id", thread_id)

    # Handle file uploads
    if message.elements:
        for el in message.elements:
            if hasattr(el, "path") and el.path:
                file_path = el.path
                dest = Path(DATA_DIR) / f"{cl.user_session.get('session_id', 'x')}_{Path(file_path).name}"
                dest.parent.mkdir(parents=True, exist_ok=True)

                import shutil
                shutil.copy2(file_path, dest)

                state["dataset_path"] = str(dest)
                break

    user_text = message.content or "Proceed"

    # Runtime controls (fault injection + checkpoint auto-approve)
    runtime_flags = _runtime_flags_from_text(user_text)
    if runtime_flags:
        state.update(runtime_flags)
        notes = []
        if "fault_injection" in runtime_flags:
            fi = runtime_flags["fault_injection"]
            notes.append(f"fault injection armed: `{fi['next_error']}` on `{fi['target']}`")
        if "auto_approve_checkpoints" in runtime_flags:
            mode = "ON" if runtime_flags["auto_approve_checkpoints"] else "OFF"
            notes.append(f"auto checkpoint mode: `{mode}`")
        await cl.Message(content="System runtime updated - " + "; ".join(notes), author="System").send()

    selected_agents = _normalize_selected_agents(
        cl.user_session.get("selected_agents"),
        default_if_missing=True,
    )
    _apply_selection_to_state(state, selected_agents)

    # Remove previous blinking prompt if it exists
    await clear_awaiting_prompt()

    state["messages"].append(HumanMessage(content=user_text))
    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
    task_list: cl.TaskList | None = cl.user_session.get("task_list")

    # Single collapsible Reasoning step
    reasoning_step = cl.Step(name="Reasoning", type="run")
    reasoning_step.output = ""
    await reasoning_step.send()

    try:
        async for event in graph.astream(state, config=config, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "__end__":
                    continue

                # Append reasoning lines to the collapsible step
                for r in node_output.get("reasoning", []):
                    if r.get("verbose") and not VERBOSE:
                        continue
                    reasoning_step.output += f"**{r.get('step_name', node_name)}**: {r.get('step_text', '')}\n\n"

                # Optional node I/O trace for contract debugging
                if VERBOSE and node_output.get("node_io"):
                    io = node_output["node_io"]
                    in_json = json.dumps(io.get("input", {}), default=str)
                    out_json = json.dumps(io.get("output", {}), default=str)
                    reasoning_step.output += (
                        f"`[I/O] {io.get('node', node_name)}` "
                        f"in={in_json} out={out_json}\n\n"
                    )

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
                else:
                    # Ensure stale checkpoint state does not leak into later nodes.
                    await clear_awaiting_prompt()
                    _clear_checkpoint_state(state)

                # Surface AI messages
                for msg in node_output.get("messages", []):
                    text = _message_text(msg)
                    if text:
                        await cl.Message(content=text).send()

                # Merge node delta into local state
                state.update(node_output)

        # Finalize reasoning step
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
                content="---\nAnalysis complete. Ask follow-up questions or start a new chat."
            ).send()

    except Exception as exc:
        reasoning_step.status = "failed"
        await reasoning_step.update()
        await cl.Message(content=f"System error: {exc}", author="System").send()

    cl.user_session.set("state", state)
    await save_analysis_state(thread_id or config["configurable"]["thread_id"], state)


@cl.on_settings_update
async def on_settings_update(settings: dict):
    if "selected_agents" in settings:
        selected = _normalize_selected_agents(
            settings.get("selected_agents"),
            default_if_missing=False,
        )
        cl.user_session.set("selected_agents", selected)
        cl.user_session.set("critique_enabled", "critique" in selected)
        state = cl.user_session.get("state") or {}
        _apply_selection_to_state(state, selected)
        cl.user_session.set("state", state)
        selected_labels = [AGENT_ID_TO_LABEL.get(agent_id, agent_id) for agent_id in selected]
        summary = ", ".join(selected_labels) if selected_labels else "none"
        await cl.Message(
            content=f"Session agents updated: **{summary}**.",
            author="System",
        ).send()


@cl.on_chat_resume
async def on_chat_resume(thread: dict):
    thread_id = thread.get("id", "") or _active_chainlit_thread_id()
    saved = await load_analysis_state(thread_id)

    legacy_thread_id = ""
    metadata = thread.get("metadata", {}) if isinstance(thread, dict) else {}
    if isinstance(metadata, dict):
        candidate = metadata.get("thread_id", "")
        if isinstance(candidate, str):
            legacy_thread_id = candidate

    if not saved and legacy_thread_id and legacy_thread_id != thread_id:
        saved = await load_analysis_state(legacy_thread_id)

    state = make_initial_state()
    _setup_runtime_session(thread_id, state)

    if saved:
        state.update(saved)
        state["thread_id"] = thread_id
        selected = _normalize_selected_agents(
            state.get("selected_agents"),
            default_if_missing=True,
        )
        _apply_selection_to_state(state, selected)
        cl.user_session.set("selected_agents", selected)
        cl.user_session.set("critique_enabled", "critique" in selected)
        await _send_agent_settings(selected)
        cl.user_session.set("state", state)
        await save_analysis_state(thread_id, state)

        phase = saved.get("phase", "analysis")
        completed = saved.get("plan_steps_completed", 0)
        total = saved.get("plan_steps_total", 0)
        parts = [f"**Phase:** {phase}"]
        if total > 0:
            parts.append(f"**Progress:** {completed}/{total} steps")

        toast_text = "Session resumed: " + " | ".join(parts) + " | Continue where you left off."
        await _send_notification(toast_text, level="success")

        # Re-surface downloads after resume hydration settles in the UI.
        if _should_restore_downloads(state):
            asyncio.create_task(_send_resume_downloads_after_restore(dict(state)))
    else:
        cl.user_session.set("selected_agents", list(DEFAULT_SELECTED_AGENTS))
        cl.user_session.set("critique_enabled", False)
        await _send_agent_settings(list(DEFAULT_SELECTED_AGENTS))
        cl.user_session.set("state", state)
        await _send_notification("Could not restore session. Starting fresh.", level="warning")


@cl.on_chat_end
async def on_chat_end():
    data_store: DataStore | None = cl.user_session.get("data_store")
    if data_store:
        data_store.cleanup()

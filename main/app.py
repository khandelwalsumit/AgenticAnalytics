"""Chainlit application entry point.

Run with: uv run chainlit run main/app.py
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
load_dotenv()

import chainlit as cl
from chainlit.input_widget import MultiSelect
from langchain_core.messages import AIMessage, HumanMessage

from agents.graph import build_graph
from config import AGENTS_DIR, CACHE_DIR, DATA_DIR, DEFAULT_CSV_PATH, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, VERBOSE
from core.agent_factory import AgentFactory
from core.data_store import DataStore
from core.file_data_layer import FileDataLayer
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY, set_analysis_deps
from tools.data_tools import set_data_store as set_data_tools_store
from tools.report_tools import set_data_store as set_report_tools_store
from ui.chat_history import load_analysis_state, save_analysis_state
from ui.components import clear_awaiting_prompt, send_awaiting_input, send_downloads, sync_task_list

# -- Logging setup ---
log = logging.getLogger("app")
logging.basicConfig(
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

FRICTION_AGENT_IDS = [
    "digital_friction_agent", "operations_agent",
    "communication_agent", "policy_agent",
]

AGENT_ID_TO_LABEL = {
    "digital_friction_agent": "Digital Friction Agent",
    "operations_agent": "Operations Agent",
    "communication_agent": "Communication Agent",
    "policy_agent": "Policy Agent",
    "critique": "Critique",
}
AGENT_LABEL_TO_ID = {v: k for k, v in AGENT_ID_TO_LABEL.items()}
DEFAULT_SELECTED_AGENTS = list(FRICTION_AGENT_IDS)

# Ensure auth secret is long enough
if len(os.environ.get("CHAINLIT_AUTH_SECRET", "")) < 32:
    os.environ["CHAINLIT_AUTH_SECRET"] = os.environ.get("CHAINLIT_AUTH_SECRET", "dev").ljust(32, "0")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _message_text(msg: Any) -> str:
    """Extract display text from an AI message. Skips raw JSON blobs."""
    if not hasattr(msg, "content") or not msg.content or getattr(msg, "type", "") != "ai":
        return ""
    content = msg.content
    if isinstance(content, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    text = str(content).strip()
    # Don't surface raw JSON from structured output agents (planner, supervisor)
    if text.startswith("{") or text.startswith("["):
        return ""
    return text


def _create_runtime() -> tuple[str, DataStore, Any]:
    """Build per-session runtime: DataStore, tools, graph."""
    session_id = str(uuid.uuid4())[:12]
    log.info("Creating runtime session=%s", session_id)
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
        "user_focus": "", "analysis_type": "", "selected_skills": [],
        "critique_enabled": False,
        "selected_agents": list(DEFAULT_SELECTED_AGENTS),
        "selected_friction_agents": list(DEFAULT_SELECTED_AGENTS),
        "auto_approve_checkpoints": False,
        "plan_steps_total": 0, "plan_steps_completed": 0, "plan_tasks": [],
        "requires_user_input": False,
        "checkpoint_message": "", "checkpoint_prompt": "",
        "checkpoint_token": "", "pending_input_for": "",
        "execution_trace": [], "reasoning": [],
        "node_io": {}, "io_trace": [], "last_completed_node": "",
        "dataset_path": "", "dataset_schema": {},
        "active_filters": {}, "data_buckets": {},
        "findings": [],
        "domain_analysis": {}, "operational_analysis": {},
        "digital_analysis": {}, "operations_analysis": {},
        "communication_analysis": {}, "policy_analysis": {},
        "synthesis_result": {},
        "narrative_output": {}, "dataviz_output": {}, "formatting_output": {},
        "report_markdown_key": "", "report_file_path": "", "data_file_path": "",
        "critique_feedback": {}, "quality_score": 0.0,
        "next_agent": "", "supervisor_decision": "",
        "analysis_complete": False, "phase": "analysis",
        "filters_applied": {}, "themes_for_analysis": [],
        "navigation_log": [], "analysis_objective": "",
        "error_count": 0, "recoverable_error": "",
        "fault_injection": {"next_error": "", "target": "any"},
    }


def _setup_session(thread_id: str, state: dict[str, Any]) -> None:
    """Store runtime objects in Chainlit user session."""
    session_id, data_store, graph = _create_runtime()
    cl.user_session.set("graph", graph)
    cl.user_session.set("data_store", data_store)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("state", state)
    cl.user_session.set("task_list", None)
    cl.user_session.set("awaiting_prompt", None)


def _apply_agent_selection(state: dict[str, Any], selected: list[str]) -> None:
    state["selected_agents"] = list(selected)
    state["selected_friction_agents"] = [a for a in selected if a in FRICTION_AGENT_IDS]
    state["critique_enabled"] = "critique" in selected


async def _send_agent_settings(selected: list[str]) -> None:
    await cl.ChatSettings([
        MultiSelect(
            id="selected_agents", label="Session Agents",
            initial=list(selected),
            items={v: k for k, v in AGENT_ID_TO_LABEL.items()},
            description="Select agents for friction analysis.",
        )
    ]).send()


# ------------------------------------------------------------------
# Auth + Data Layer
# ------------------------------------------------------------------


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    return cl.User(identifier=username, metadata={"role": "admin", "provider": "credentials"})


@cl.data_layer
def get_data_layer():
    return FileDataLayer()


# ------------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------------


@cl.on_chat_start
async def on_chat_start():
    thread_id = getattr(cl.context.session, "thread_id", "") or str(uuid.uuid4())
    log.info("Chat start thread=%s", thread_id)
    state = make_initial_state()
    _setup_session(thread_id, state)
    _apply_agent_selection(state, DEFAULT_SELECTED_AGENTS)
    await _send_agent_settings(DEFAULT_SELECTED_AGENTS)

    # Auto-load CSV into DataStore
    csv_path = Path(DEFAULT_CSV_PATH)
    if csv_path.exists():
        data_store: DataStore = cl.user_session.get("data_store")
        df = pd.read_csv(str(csv_path))
        data_store.store_dataframe("main_dataset", df, metadata={
            "source": str(csv_path), "row_count": len(df), "columns": list(df.columns),
        })
        state["dataset_path"] = str(csv_path)
        cl.user_session.set("state", state)
        log.info("Loaded CSV: %s (%d rows)", csv_path.name, len(df))


@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="ATT Promotion Issues",
            message="Can you check what promotion related issues ATT customers are facing?",
            icon="https://img.icons8.com/fluency/96/discount.png",
        ),
        cl.Starter(
            label="Rewards Friction Analysis",
            message="Analyze the key friction points ATT card customers face regarding rewards redemption",
            icon="https://img.icons8.com/fluency/96/gift.png",
        ),
        cl.Starter(
            label="Top Call Drivers",
            message="What are the top call drivers and digital friction themes across all products?",
            icon="https://img.icons8.com/fluency/96/phone.png",
        ),
    ]


@cl.on_message
async def on_message(message: cl.Message):
    graph = cl.user_session.get("graph")
    state = cl.user_session.get("state") or make_initial_state()
    thread_id = cl.user_session.get("thread_id") or getattr(cl.context.session, "thread_id", "") or str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)

    # Handle file uploads
    if message.elements:
        for el in message.elements:
            if hasattr(el, "path") and el.path:
                dest = Path(DATA_DIR) / f"{cl.user_session.get('session_id', 'x')}_{Path(el.path).name}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(el.path, dest)
                state["dataset_path"] = str(dest)
                log.info("File uploaded: %s", dest)
                break

    user_text = message.content or "Proceed"
    log.info("User message: %s", user_text[:80])
    _apply_agent_selection(state, cl.user_session.get("selected_agents") or DEFAULT_SELECTED_AGENTS)
    await clear_awaiting_prompt()

    config = {"configurable": {"thread_id": thread_id}}
    task_list: cl.TaskList | None = cl.user_session.get("task_list")

    # Resume from checkpoint interrupt or start fresh
    snapshot = graph.get_state(config)
    is_resuming = bool(snapshot and snapshot.next)
    if is_resuming:
        graph_input = {"messages": [HumanMessage(content=user_text)]}
        log.info("Resuming from checkpoint (next=%s)", snapshot.next)
    else:
        state["messages"].append(HumanMessage(content=user_text))
        graph_input = state
        log.info("Fresh graph run (messages=%d)", len(state["messages"]))

    # Collapsible reasoning step
    reasoning_step = cl.Step(name="Reasoning", type="run")
    reasoning_step.output = ""
    await reasoning_step.send()

    try:
        stream = graph.astream(graph_input, config=config, stream_mode="updates")
        async for event in stream:
            for node_name, node_output in event.items():
                if node_name == "__end__" or not isinstance(node_output, dict):
                    continue

                # Log what this node returned
                output_keys = [k for k in node_output if node_output[k]]
                msg_count = len(node_output.get("messages", []))
                decision = node_output.get("supervisor_decision", "")
                next_agent = node_output.get("next_agent", "")
                log.info(
                    "Node [%s] → keys=%s msgs=%d decision=%s next=%s",
                    node_name, output_keys, msg_count, decision or "-", next_agent or "-",
                )

                # Append reasoning
                for r in node_output.get("reasoning", []):
                    if r.get("verbose") and not VERBOSE:
                        continue
                    reasoning_step.output += f"**{r.get('step_name', node_name)}**: {r.get('step_text', '')}\n\n"
                await reasoning_step.update()

                # Sync task list
                new_tasks = node_output.get("plan_tasks")
                if new_tasks is not None:
                    statuses = {t.get('status', '?') for t in new_tasks}
                    log.info("TaskList updated: %d tasks, statuses=%s", len(new_tasks), statuses)
                    task_list = await sync_task_list(task_list, new_tasks)
                    cl.user_session.set("task_list", task_list)

                # Checkpoint: awaiting user input
                if node_output.get("requires_user_input"):
                    prompt = node_output.get("checkpoint_prompt", "Please provide input to continue.")
                    log.info("Checkpoint: awaiting user input (%s)", node_output.get("pending_input_for", "?"))
                    info = node_output.get("checkpoint_message", "")
                    if info:
                        await cl.Message(content=info).send()
                    prompt_msg = await send_awaiting_input(prompt)
                    cl.user_session.set("awaiting_prompt", prompt_msg)
                else:
                    await clear_awaiting_prompt()

                # Surface AI messages
                for msg in node_output.get("messages", []):
                    text = _message_text(msg)
                    if text:
                        await cl.Message(content=text).send()

                # Merge node output into local state
                state.update(node_output)

        reasoning_step.status = "success"
        await reasoning_step.update()
        log.info("Graph stream complete. plan=%d/%d",
                 state.get("plan_steps_completed", 0), state.get("plan_steps_total", 0))

        # Send downloads if analysis complete
        if state.get("report_file_path") or state.get("data_file_path"):
            await send_downloads(
                state.get("report_file_path", ""),
                state.get("data_file_path", ""),
            )
        if state.get("analysis_complete") and task_list:
            done = [{**t, "status": "done"} for t in state.get("plan_tasks", [])]
            task_list = await sync_task_list(task_list, done)
            task_list.status = "Done"
            await task_list.send()
            cl.user_session.set("task_list", task_list)

    except Exception as exc:
        log.error("Graph error: %s", exc, exc_info=True)
        reasoning_step.status = "failed"
        await reasoning_step.update()
        await cl.Message(content=f"System error: {exc}", author="System").send()
    finally:
        await stream.aclose()

    cl.user_session.set("state", state)
    await save_analysis_state(thread_id, state)
    log.info("State saved for thread=%s", thread_id)


@cl.on_settings_update
async def on_settings_update(settings: dict):
    if "selected_agents" not in settings:
        return
    selected = [v if v in AGENT_ID_TO_LABEL else AGENT_LABEL_TO_ID.get(v, "") for v in (settings.get("selected_agents") or [])]
    selected = [s for s in selected if s]
    cl.user_session.set("selected_agents", selected)
    state = cl.user_session.get("state") or {}
    _apply_agent_selection(state, selected)
    cl.user_session.set("state", state)
    labels = [AGENT_ID_TO_LABEL.get(a, a) for a in selected]
    await cl.Message(content=f"Session agents updated: **{', '.join(labels) or 'none'}**.", author="System").send()


@cl.on_chat_resume
async def on_chat_resume(thread: dict):
    thread_id = thread.get("id", "") or str(uuid.uuid4())
    log.info("Chat resume thread=%s", thread_id)
    saved = await load_analysis_state(thread_id)

    state = make_initial_state()
    _setup_session(thread_id, state)

    if saved:
        raw_msgs = saved.pop("messages", [])
        state.update(saved)
        state["messages"] = [
            HumanMessage(content=m["content"]) if m.get("role") == "human"
            else AIMessage(content=m["content"])
            for m in raw_msgs if m.get("content")
        ]
        log.info("Restored %d messages from saved state", len(state["messages"]))
        # Re-load CSV into DataStore if path is saved
        csv_path = state.get("dataset_path", "")
        if csv_path and Path(csv_path).exists():
            data_store: DataStore = cl.user_session.get("data_store")
            df = pd.read_csv(csv_path)
            data_store.store_dataframe("main_dataset", df, metadata={})
            log.info("Re-loaded CSV: %s (%d rows)", csv_path, len(df))
    else:
        log.warning("No saved state found for thread=%s", thread_id)

    selected = state.get("selected_agents") or DEFAULT_SELECTED_AGENTS
    _apply_agent_selection(state, selected)
    await _send_agent_settings(selected)
    cl.user_session.set("state", state)


@cl.on_chat_end
async def on_chat_end():
    log.info("Chat end, cleaning up DataStore")
    data_store: DataStore | None = cl.user_session.get("data_store")
    if data_store:
        data_store.cleanup()

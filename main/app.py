"""Chainlit application entry point.

Run with: uv run chainlit run main/app.py
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import chainlit as cl
from chainlit.input_widget import MultiSelect
from langchain_core.messages import AIMessage, HumanMessage

from agents.graph import build_graph
from config import (
    AGENTS_DIR,
    CACHE_DIR,
    DATA_INPUT_DIR,
    DATA_OUTPUT_DIR,
    DEFAULT_CSV_PATH,
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    VERBOSE,
)
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

# Ensure runtime directories exist.
Path(".files").mkdir(parents=True, exist_ok=True)
Path(DATA_INPUT_DIR).mkdir(parents=True, exist_ok=True)
Path(DATA_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

# Nodes whose AI messages render as collapsible Steps, not chat messages.
# The first line becomes the step title; full text is the expanded body.
STEP_NODES = {"data_analyst", "planner", "report_analyst"}

STEP_NODE_LABELS = {
    "data_analyst": "Data Extraction",
    "planner": "Planning",
    "report_analyst": "Report Review",
}

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
FRICTION_STATE_FIELDS = {
    "digital_friction_agent": "digital_analysis",
    "operations_agent": "operations_analysis",
    "communication_agent": "communication_analysis",
    "policy_agent": "policy_analysis",
}

# Ensure auth secret is long enough
if len(os.environ.get("CHAINLIT_AUTH_SECRET", "")) < 32:
    os.environ["CHAINLIT_AUTH_SECRET"] = os.environ.get("CHAINLIT_AUTH_SECRET", "dev").ljust(32, "0")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _message_text(msg: Any) -> str:
    """Extract display text from an AI message. Skips raw JSON blobs and tool noise."""
    if not hasattr(msg, "content") or not msg.content or getattr(msg, "type", "") != "ai":
        return ""
    # Skip messages that are tool calls (no text content, only tool_calls)
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        return ""
    content = msg.content
    if isinstance(content, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    text = str(content).strip()
    # Don't surface raw JSON from structured output agents (planner, supervisor)
    if text.startswith("{") or text.startswith("["):
        return ""
    # Don't surface messages containing large JSON blocks (agent dumps)
    if "```json" in text or (text.count("{") > 5 and text.count("}") > 5):
        return ""

    # Hide local filesystem path lines from chat UI (downloads are shown via buttons/elements).
    # Example: "The report is here: D:\\Workspace\\...\\report_xxx.pptx"
    path_line_re = re.compile(r"[A-Za-z]:\\")
    filtered_lines = [ln for ln in text.splitlines() if not path_line_re.search(ln)]
    text = "\n".join(filtered_lines).strip()
    if not text:
        return ""
    return text


def _build_filter_catalog(df: pd.DataFrame, max_unique: int = 50) -> dict[str, list[str]]:
    """Build a catalog of filterable columns with their unique values.

    Only includes columns with <= max_unique unique non-null values
    (free-text columns are excluded automatically).
    """
    catalog: dict[str, list[str]] = {}
    for col in df.columns:
        nunique = df[col].dropna().nunique()
        if 1 < nunique <= max_unique:
            values = sorted(df[col].dropna().unique().astype(str).tolist())
            catalog[col] = values
    return catalog


def _safe_thread_id(raw: str) -> str:
    value = str(raw or "").strip() or "unknown_thread"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)[:80]


def _find_input_csv() -> Path | None:
    """Resolve input CSV from explicit path or data/input/*.csv."""
    explicit = Path(DEFAULT_CSV_PATH)
    if explicit.exists() and explicit.is_file():
        return explicit

    candidates = sorted(
        [p for p in Path(DATA_INPUT_DIR).glob("*.csv") if p.is_file()],
        key=lambda p: p.name.lower(),
    )
    return candidates[0] if candidates else None


def _unique_input_destination(filename: str) -> Path:
    """Create a non-colliding path under data/input for uploaded files."""
    base = Path(DATA_INPUT_DIR)
    candidate = base / Path(filename).name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    idx = 1
    while True:
        alt = base / f"{stem}_{idx}{suffix}"
        if not alt.exists():
            return alt
        idx += 1


def _collect_output_files(thread_id: str) -> list[str]:
    """Collect final output files from data/output/<thread_id>."""
    output_dir = Path(DATA_OUTPUT_DIR) / _safe_thread_id(thread_id)
    if not output_dir.exists() or not output_dir.is_dir():
        return []

    preferred_order = [
        output_dir / "complete_analysis.md",
        output_dir / "report.pptx",
        output_dir / "filtered_data.csv",
    ]
    files: list[str] = [str(p.resolve()) for p in preferred_order if p.exists() and p.is_file()]

    known = {Path(p) for p in files}
    extras = sorted(
        [p for p in output_dir.iterdir() if p.is_file() and p not in known],
        key=lambda p: p.name.lower(),
    )
    files.extend([str(p.resolve()) for p in extras])
    return files


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
        "expected_friction_lenses": list(DEFAULT_SELECTED_AGENTS),
        "missing_friction_lenses": [],
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
        "friction_output_files": {},
        "synthesis_result": {},
        "narrative_output": {}, "dataviz_output": {}, "formatting_output": {},
        "report_markdown_key": "", "report_file_path": "", "data_file_path": "", "markdown_file_path": "",
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
    cl.user_session.set("resume_from_saved_state", False)


def _rehydrate_friction_outputs(state: dict[str, Any]) -> None:
    """Recreate friction output files in the current session DataStore from saved state."""
    data_store: DataStore | None = cl.user_session.get("data_store")
    if not data_store:
        return

    rebuilt: dict[str, str] = {}
    for agent_id, field in FRICTION_STATE_FIELDS.items():
        payload = state.get(field, {})
        if not isinstance(payload, dict):
            continue
        full_response = str(payload.get("full_response", "")).strip()
        if not full_response:
            continue
        key = f"{agent_id}_output"
        data_store.store_text(key, full_response, {"agent": agent_id, "type": "friction_output"})
        rebuilt[agent_id] = key

    if rebuilt:
        state["friction_output_files"] = rebuilt
        log.info("Rehydrated friction outputs into DataStore: %s", list(rebuilt.keys()))


def _apply_agent_selection(state: dict[str, Any], selected: list[str]) -> None:
    state["selected_agents"] = list(selected)
    state["selected_friction_agents"] = [a for a in selected if a in FRICTION_AGENT_IDS]
    state["expected_friction_lenses"] = list(state["selected_friction_agents"])
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

    # Auto-load CSV from configured path or data/input.
    csv_path = _find_input_csv()
    if csv_path:
        data_store: DataStore = cl.user_session.get("data_store")
        df = pd.read_csv(str(csv_path))
        data_store.store_dataframe("main_dataset", df, metadata={
            "source": str(csv_path), "row_count": len(df), "columns": list(df.columns),
        })
        state["dataset_path"] = str(csv_path)
        state["dataset_schema"] = _build_filter_catalog(df)
        cl.user_session.set("state", state)
        log.info("Loaded CSV: %s (%d rows), filter catalog built (%d columns)",
                 csv_path.name, len(df), len(state["dataset_schema"]))


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
                dest = _unique_input_destination(Path(el.path).name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(el.path, dest)
                state["dataset_path"] = str(dest)
                # Rebuild filter catalog for uploaded file
                try:
                    uploaded_df = pd.read_csv(str(dest))
                    data_store: DataStore = cl.user_session.get("data_store")
                    data_store.store_dataframe("main_dataset", uploaded_df, metadata={
                        "source": str(dest), "row_count": len(uploaded_df),
                        "columns": list(uploaded_df.columns),
                    })
                    state["dataset_schema"] = _build_filter_catalog(uploaded_df)
                    log.info("File uploaded: %s, filter catalog built (%d columns)",
                             dest, len(state["dataset_schema"]))
                except Exception as e:
                    log.warning("Could not build filter catalog for upload: %s", e)
                break

    user_text = message.content or "Proceed"
    log.info("User message: %s", user_text[:80])
    _apply_agent_selection(state, cl.user_session.get("selected_agents") or DEFAULT_SELECTED_AGENTS)
    await clear_awaiting_prompt()

    config = {"configurable": {"thread_id": thread_id}}
    task_list: cl.TaskList | None = cl.user_session.get("task_list")
    displayed_msg_ids: set[str] = set()  # Dedup safety net

    # Resume from checkpoint interrupt or start fresh
    snapshot = graph.get_state(config)
    is_resuming = bool(snapshot and snapshot.next)
    resume_from_saved_state = bool(cl.user_session.get("resume_from_saved_state"))
    if is_resuming and resume_from_saved_state and not state.get("requires_user_input"):
        graph_input = {}
        cl.user_session.set("resume_from_saved_state", False)
        log.info("Continuing from restored checkpoint without appending a new user message (next=%s)", snapshot.next)
    elif is_resuming:
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
                    "=== Stream [%s] -> msgs=%d decision=%s next=%s keys=%s",
                    node_name, msg_count, decision or "-", next_agent or "-", output_keys,
                )
                # Log message previews for debugging
                for i, msg in enumerate(node_output.get("messages", [])):
                    mtype = getattr(msg, "type", "?")
                    mid = getattr(msg, "id", "?")[:12] if getattr(msg, "id", None) else "no-id"
                    content = str(msg.content)[:120] if hasattr(msg, "content") and msg.content else ""
                    log.debug("  msg[%d] id=%s type=%s -> %s", i, mid, mtype, content)

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

                # Surface AI messages (deduplicated)
                for msg in node_output.get("messages", []):
                    msg_id = getattr(msg, "id", None) or str(id(msg))
                    if msg_id in displayed_msg_ids:
                        continue
                    displayed_msg_ids.add(msg_id)
                    text = _message_text(msg)
                    if text:
                        if node_name in STEP_NODES:
                            # Render as collapsible step bar
                            label = STEP_NODE_LABELS.get(node_name, node_name)
                            first_line = text.split("\n")[0].strip()
                            step = cl.Step(name=f"{label}: {first_line[:80]}", type="tool")
                            step.output = text
                            await step.send()
                        else:
                            await cl.Message(content=text).send()

                # Merge node output into local state (append lists, replace scalars)
                for k, v in node_output.items():
                    if k == "messages":
                        state.setdefault("messages", []).extend(v if isinstance(v, list) else [v])
                    elif k in ("reasoning", "execution_trace", "io_trace") and isinstance(v, list):
                        state.setdefault(k, []).extend(v)
                    else:
                        state[k] = v

        reasoning_step.status = "success"
        await reasoning_step.update()
        log.info("Graph stream complete. plan=%d/%d",
                 state.get("plan_steps_completed", 0), state.get("plan_steps_total", 0))

        # --- Downloads ---
        output_files = _collect_output_files(thread_id)
        log.info(
            "Download check: output_dir=%r files=%d analysis_complete=%s",
            str(Path(DATA_OUTPUT_DIR) / _safe_thread_id(thread_id)),
            len(output_files),
            state.get("analysis_complete"),
        )

        if output_files:
            await send_downloads(file_paths=output_files)
        else:
            log.warning("No download files found in data/output/%s.", _safe_thread_id(thread_id))

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
            state["dataset_schema"] = _build_filter_catalog(df)
            log.info("Re-loaded CSV: %s (%d rows), filter catalog rebuilt", csv_path, len(df))

        # Rehydrate friction outputs so synthesizer/reporting can continue without re-running prior agents.
        _rehydrate_friction_outputs(state)

        # Seed graph checkpoint state from restored state so next run continues from checkpoint.
        graph = cl.user_session.get("graph")
        cfg = {"configurable": {"thread_id": thread_id}}
        graph.update_state(cfg, state)
        snap = graph.get_state(cfg)
        log.info(
            "Checkpoint restored for thread=%s (next=%s, plan=%d/%d, complete=%s)",
            thread_id,
            snap.next if snap else (),
            state.get("plan_steps_completed", 0),
            state.get("plan_steps_total", 0),
            state.get("analysis_complete"),
        )
        if not state.get("analysis_complete"):
            cl.user_session.set("resume_from_saved_state", True)
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

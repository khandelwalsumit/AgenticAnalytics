"""Chainlit application entry point.

Run with: uv run chainlit run main/app.py
"""
from __future__ import annotations

import json
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
    DATA_CACHE_DIR,
    DATA_INPUT_DIR,
    DATA_OUTPUT_DIR,
    DEFAULT_PARQUET_PATH,
    LLM_ANALYSIS_CONTEXT,
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


def _normalize_message_for_dedupe(text: str) -> str:
    """Normalize text for lightweight semantic dedupe."""
    normalized = text.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)
    return normalized


def _should_surface_message(node_name: str, text: str) -> bool:
    """Hide internal/repetitive orchestration chatter from chat UI."""
    if not text:
        return False

    # Report analyst is a delivery checkpoint; download elements already convey output.
    # Data analyst output is internal extraction confirmation.
    if node_name in {"report_analyst", "data_analyst"}:
        return False

    t = text.lower()
    orchestration_markers = (
        "i'm starting",
        "i am starting",
        "starting multi-dimensional friction analysis",
        "friction analysis is complete",
        "now generating the detailed analysis report",
        "preparing to deliver the report",
        "all report artifacts are complete and ready for delivery",
        "the following files were already present",
        "analysis report focusing on",
        "ready for your review",
        "you can find the full report",
        "here are the file paths",
        "let me know if you'd like to dive into any specific findings",
    )
    if any(marker in t for marker in orchestration_markers):
        return False

    return True


def _should_surface_reasoning(step_name: str, text: str) -> bool:
    """Suppress repetitive orchestration reasoning while keeping core analysis."""
    if not text:
        return False
    s = str(step_name or "").strip().lower()
    t = text.lower()

    if s == "supervisor":
        supervisor_noise_markers = (
            "next step in the plan",
            "executing this task",
            "the previous step",
            "all plan tasks are complete",
            "falls under the 'answer' decision",
            "including report generation and delivery",
        )
        if any(marker in t for marker in supervisor_noise_markers):
            return False

    if s == "report analyst":
        return False

    return True



def _safe_thread_id(raw: str) -> str:
    value = str(raw or "").strip() or "unknown_thread"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)[:80]


def _find_input_parquet() -> Path | None:
    """Resolve input parquet from configured path or data/input/*.parquet."""
    explicit = Path(DEFAULT_PARQUET_PATH)
    if explicit.exists() and explicit.is_file():
        return explicit
    candidates = sorted(
        [p for p in Path(DATA_INPUT_DIR).glob("*.parquet") if p.is_file()],
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

    known = {Path(p).resolve() for p in files}
    extras = sorted(
        [p for p in output_dir.iterdir() if p.is_file() and p.resolve() not in known],
        key=lambda p: p.name.lower(),
    )
    files.extend([str(p.resolve()) for p in extras])
    return files


def _mark_tasks_done(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of plan tasks with all rows marked done."""
    done_tasks: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        row = dict(task)
        row["status"] = "done"
        sub_agents = row.get("sub_agents", [])
        if isinstance(sub_agents, list):
            normalized_sub_agents: list[dict[str, Any]] = []
            for sub in sub_agents:
                if not isinstance(sub, dict):
                    continue
                sub_row = dict(sub)
                sub_row["status"] = "done"
                normalized_sub_agents.append(sub_row)
            row["sub_agents"] = normalized_sub_agents
        done_tasks.append(row)
    return done_tasks


async def _restore_resume_ui(thread_id: str, state: dict[str, Any]) -> None:
    """Rehydrate TaskList and download buttons during chat resume."""
    task_list: cl.TaskList | None = cl.user_session.get("task_list")
    tasks = state.get("plan_tasks", [])
    if isinstance(tasks, list) and tasks:
        ui_tasks = _mark_tasks_done(tasks) if state.get("analysis_complete") else tasks
        task_list = await sync_task_list(task_list, ui_tasks)
        task_list.status = "Done" if state.get("analysis_complete") else "Running"
        await task_list.send()
        cl.user_session.set("task_list", task_list)
        log.info(
            "Resume UI: restored task list (%d rows, complete=%s)",
            len(tasks),
            state.get("analysis_complete"),
        )

    await _maybe_send_downloads(thread_id, state)


async def _maybe_send_downloads(thread_id: str, state: dict[str, Any]) -> bool:
    """Send download elements once per thread state."""
    if state.get("downloads_sent"):
        log.info("Download check: skipped (already sent for this thread)")
        return False

    output_files = _collect_output_files(thread_id)
    log.info(
        "Download check: output_dir=%r files=%d analysis_complete=%s",
        str(Path(DATA_OUTPUT_DIR) / _safe_thread_id(thread_id)),
        len(output_files),
        state.get("analysis_complete"),
    )
    if not output_files:
        return False

    await send_downloads(file_paths=output_files)
    state["downloads_sent"] = True
    cl.user_session.set("state", state)
    log.info("Download check: sent %d file(s)", len(output_files))
    return True


def _is_new_analysis_plan(tasks: list[dict[str, Any]]) -> bool:
    """Detect whether plan tasks indicate a fresh analysis run is underway."""
    if not tasks:
        return False
    statuses = {str(t.get("status", "")).strip().lower() for t in tasks if isinstance(t, dict)}
    if not statuses:
        return False
    # Fresh/active runs have at least one actionable task and are not fully done.
    has_actionable = bool(statuses & {"in_progress", "ready", "todo"})
    all_done = all(s in {"done", ""} for s in statuses)
    return has_actionable and not all_done


def _create_runtime(thread_id: str) -> tuple[str, DataStore, Any]:
    """Build per-session runtime: DataStore, tools, graph.

    Uses thread_id as the DataStore session key so all cache files land in
    data/.cache/<thread_id>/ — stable across resumes of the same conversation.
    """
    safe_tid = _safe_thread_id(thread_id)
    log.info("Creating runtime thread=%s", safe_tid)
    data_store = DataStore(session_id=safe_tid, DATA_CACHE_DIR=str(DATA_CACHE_DIR))
    set_data_tools_store(data_store)
    set_report_tools_store(data_store)
    skill_loader = SkillLoader()
    set_analysis_deps(data_store, skill_loader)
    agent_factory = AgentFactory(definitions_dir=AGENTS_DIR, tool_registry=TOOL_REGISTRY)
    graph = build_graph(agent_factory=agent_factory, skill_loader=skill_loader)
    return safe_tid, data_store, graph


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
        "filtered_parquet_path": "", "bucket_paths": {},
        "top_themes": [], "analytics_insights": {},
        "findings": [],
        "domain_analysis": {}, "operational_analysis": {},
        "digital_analysis": {}, "operations_analysis": {},
        "communication_analysis": {}, "policy_analysis": {},
        "friction_output_files": {}, "friction_md_paths": {},
        "synthesis_result": {}, "synthesis_path": "",
        "narrative_output": {}, "narrative_path": "",
        "dataviz_output": {}, "formatting_output": {},
        "report_markdown_key": "", "report_file_path": "", "data_file_path": "", "markdown_file_path": "",
        "critique_feedback": {}, "quality_score": 0.0,
        "next_agent": "", "supervisor_decision": "",
        "analysis_complete": False, "phase": "analysis",
        "downloads_sent": False,
        "filters_applied": {}, "themes_for_analysis": [],
        "navigation_log": [], "analysis_objective": "",
        "error_count": 0, "recoverable_error": "",
        "fault_injection": {"next_error": "", "target": "any"},
    }


def _setup_session(thread_id: str, state: dict[str, Any]) -> None:
    """Store runtime objects in Chainlit user session."""
    session_id, data_store, graph = _create_runtime(thread_id)
    cl.user_session.set("graph", graph)
    cl.user_session.set("data_store", data_store)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("state", state)
    cl.user_session.set("task_list", None)
    cl.user_session.set("awaiting_prompt", None)


def _rehydrate_friction_outputs(state: dict[str, Any]) -> None:
    """Re-register friction/synthesis markdown files into the DataStore on resume.

    On resume the DataStore is a fresh instance but the .md files already exist
    in data/.cache/<thread_id>/ (because DataStore uses thread_id as session key).
    We just need to update friction_md_paths / synthesis_path in state if the
    files are on disk — the DataStore registry will be rebuilt from the files.
    """
    data_store: DataStore | None = cl.user_session.get("data_store")
    if not data_store:
        return

    # Restore friction markdown paths from disk — files are already there.
    md_paths = state.get("friction_md_paths", {})
    rebuilt_md: dict[str, str] = {}
    rebuilt_ds: dict[str, str] = {}
    for agent_id, md_path in md_paths.items():
        if md_path and Path(md_path).exists():
            rebuilt_md[agent_id] = md_path
            # Also register in DataStore so legacy code using friction_output_files works.
            key = f"{agent_id}_output"
            content = Path(md_path).read_text(encoding="utf-8")
            data_store.store_text(key, content, {"agent": agent_id, "type": "friction_output"})
            rebuilt_ds[agent_id] = key

    if not rebuilt_md:
        # Legacy path: rebuild from state dict full_response fields
        for agent_id, field in FRICTION_STATE_FIELDS.items():
            payload = state.get(field, {})
            if not isinstance(payload, dict):
                continue
            full_response = str(payload.get("full_response", "")).strip()
            if not full_response:
                continue
            _key, path = data_store.store_versioned_md(
                agent_id, full_response, {"agent": agent_id, "type": "friction_output"}
            )
            rebuilt_md[agent_id] = path
            rebuilt_ds[agent_id] = _key

    if rebuilt_md:
        state["friction_md_paths"] = rebuilt_md
        state["friction_output_files"] = rebuilt_ds
        log.info("Rehydrated friction md_paths: %s", list(rebuilt_md.keys()))

    # Restore synthesis path / DataStore entry
    synthesis_path = state.get("synthesis_path", "")
    if synthesis_path and Path(synthesis_path).exists():
        content = Path(synthesis_path).read_text(encoding="utf-8")
        key = data_store.store_text("synthesis_output", content, {"agent": "synthesizer_agent", "type": "synthesis_output"})
        state["synthesis_output_file"] = key
        log.info("Rehydrated synthesis from %s", synthesis_path)
    elif state.get("synthesis_result"):
        content = json.dumps(state["synthesis_result"])
        key = data_store.store_text("synthesis_output", content, {"agent": "synthesizer_agent", "type": "synthesis_output"})
        state["synthesis_output_file"] = key


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

    # Auto-load parquet path from configured location — read in-place by load_dataset tool.
    parquet_path = _find_input_parquet()
    if parquet_path:
        state["dataset_path"] = str(parquet_path)
        state["dataset_schema"] = LLM_ANALYSIS_CONTEXT
        cl.user_session.set("state", state)
        log.info("Auto-loaded parquet path: %s", parquet_path.name)


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

    # Handle file uploads — parquet preferred; CSV uploads are converted automatically.
    if message.elements:
        for el in message.elements:
            if hasattr(el, "path") and el.path:
                src = Path(el.path)
                # Normalise destination to .parquet
                dest_name = src.stem + ".parquet"
                dest = _unique_input_destination(dest_name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.suffix.lower() == ".parquet":
                    shutil.copy2(src, dest)
                else:
                    # Convert CSV → parquet on upload so the rest of the pipeline is uniform
                    pd.read_csv(str(src)).to_parquet(str(dest), index=False)
                state["dataset_path"] = str(dest)
                state["dataset_schema"] = LLM_ANALYSIS_CONTEXT
                log.info("File uploaded and saved as parquet: %s", dest)
                break

    user_text = message.content or "Proceed"
    log.info("User message: %s", user_text[:80])
    _apply_agent_selection(state, cl.user_session.get("selected_agents") or DEFAULT_SELECTED_AGENTS)
    await clear_awaiting_prompt()

    config = {"configurable": {"thread_id": thread_id}}
    task_list: cl.TaskList | None = cl.user_session.get("task_list")
    displayed_msg_ids: set[str] = set()  # ID-level dedupe safety net
    displayed_msg_norms: set[str] = set()  # text-level dedupe safety net
    was_complete_before_run = bool(state.get("analysis_complete"))
    downloads_reset_for_run = False

    # Resume from checkpoint interrupt or start fresh
    snapshot = graph.get_state(config)
    is_resuming = bool(snapshot and snapshot.next)
    human_msg = HumanMessage(content=user_text)
    state["messages"].append(human_msg)
    if is_resuming:
        graph_input = {"messages": [human_msg]}
        log.info("Resuming from checkpoint with user message (next=%s)", snapshot.next)
    else:
        graph_input = state
        log.info("Fresh graph run (messages=%d)", len(state["messages"]))

    # Collapsible reasoning step
    reasoning_step = cl.Step(name="Reasoning", type="run")
    reasoning_step.output = ""
    await reasoning_step.send()

    # Blinking placeholder message
    active_node_msg = cl.Message(content="Analyzing...", author="System")
    await active_node_msg.send()

    stream = None
    try:
        stream = graph.astream(graph_input, config=config, stream_mode="updates")
        async for event in stream:
            for node_name, node_output in event.items():
                if node_name == "__end__" or not isinstance(node_output, dict):
                    continue

                # Update blinking placeholder with current node
                active_node_msg.content = f"Running: **{node_name}**..."
                await active_node_msg.update()

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
                    step_name = r.get("step_name", node_name)
                    step_text = r.get("step_text", "")
                    if not _should_surface_reasoning(step_name, step_text):
                        continue
                    reasoning_step.output += f"- {step_text}\n\n"
                await reasoning_step.update()

                # Sync task list
                new_tasks = node_output.get("plan_tasks")
                if new_tasks is not None:
                    if (
                        was_complete_before_run
                        and not downloads_reset_for_run
                        and _is_new_analysis_plan(new_tasks)
                    ):
                        state["downloads_sent"] = False
                        state["analysis_complete"] = False
                        state["phase"] = "analysis"
                        cl.user_session.set("state", state)
                        downloads_reset_for_run = True
                        log.info("Detected fresh analysis run in same thread; reset downloads_sent flag.")
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
                    if not _should_surface_message(node_name, text):
                        continue

                    norm = _normalize_message_for_dedupe(text)
                    if norm and norm in displayed_msg_norms:
                        continue
                    if norm:
                        displayed_msg_norms.add(norm)

                    if node_name in STEP_NODES:
                        # Render as collapsible step bar
                        label = STEP_NODE_LABELS.get(node_name, node_name)
                        first_line = text.split("\n")[0].strip()
                        step = cl.Step(name=f"- {first_line}", type="tool")
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

        # Check if input is required after all nodes
        final_snapshot = graph.get_state(config)
        is_interrupted = bool(final_snapshot and final_snapshot.next)
        
        if state.get("requires_user_input") or is_interrupted:
            active_node_msg.content = "Waiting for your input..."
            await active_node_msg.update()
        else:
            await active_node_msg.remove()

        # --- Downloads ---
        sent = await _maybe_send_downloads(thread_id, state)
        if not sent:
            log.warning("No new download elements rendered for thread=%s.", _safe_thread_id(thread_id))

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
        active_node_msg.content = "Error occurred."
        await active_node_msg.update()
        await cl.Message(content=f"System error: {exc}", author="System").send()
    finally:
        if stream is not None:
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
        state["messages"] = []
        for m in raw_msgs:
            role = str(m.get("role", "")).strip().lower()
            if role not in {"human", "ai"}:
                continue
            content = m.get("content")
            if content is None or content == "":
                continue
            state["messages"].append(
                HumanMessage(content=content) if role == "human" else AIMessage(content=content)
            )
        log.info("Restored %d messages from saved state", len(state["messages"]))
        # Restore dataset_schema from config — always current, no file read needed.
        if state.get("dataset_path"):
            state["dataset_schema"] = LLM_ANALYSIS_CONTEXT
            log.info("Resume: dataset_schema restored from config")

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
    else:
        log.warning("No saved state found for thread=%s", thread_id)

    selected = state.get("selected_agents") or DEFAULT_SELECTED_AGENTS
    _apply_agent_selection(state, selected)
    await _send_agent_settings(selected)
    cl.user_session.set("state", state)
    if saved:
        await _restore_resume_ui(thread_id, state)


@cl.on_chat_end
async def on_chat_end():
    log.info("Chat end, cleaning up DataStore")
    data_store: DataStore | None = cl.user_session.get("data_store")
    if data_store:
        data_store.cleanup()

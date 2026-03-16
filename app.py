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
from chainlit.input_widget import MultiSelect,Switch
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

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
from ui.components import send_downloads, sync_task_list

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
STEP_NODES = {"planner", "report_analyst"}

STEP_NODE_LABELS = {
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
    # Data analyst summary is shown via lens_confirmation interrupt; surfacing it
    # separately causes the supervisor to re-present the same information.
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
        output_dir / "report.docx",
        output_dir / "report.pptx",
        output_dir / "filtered_data.csv",
        output_dir / "complete_analysis.md",
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

    # Send download buttons immediately on resume if analysis is complete
    if state.get("analysis_complete"):
        output_files = _collect_output_files(thread_id)
        if output_files:
            state["downloads_sent"] = False
            await _maybe_send_downloads(thread_id, state)
            log.info("Resume UI: sent download buttons (%d files)", len(output_files))


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
        "critique_enabled": False,
        "selected_agents": list(DEFAULT_SELECTED_AGENTS),
        "auto_approve_checkpoints": False,
        "plan_steps_total": 0, "plan_steps_completed": 0, "plan_tasks": [],
        "checkpoint_message": "", "checkpoint_prompt": "",
        "pending_input_for": "",
        "analysis_scope_reply": "",
        "execution_trace": [], "reasoning": [],
        "last_completed_node": "",
        "dataset_path": "", "dataset_schema": {},
        "filtered_parquet_path": "",
        "bucket_manifest_path": "",
        "themes_for_analysis": [],
        "lens_outputs_dir": "",
        "synthesis_path": "",
        "classified_solutions_path": "",
        "narrative_path": "",
        "blueprint_path": "",
        "artifacts_dir": "",
        "critique_feedback": {}, "quality_score": 0.0,
        "next_agent": "", "supervisor_decision": "",
        "analysis_complete": False, "phase": "analysis",
        "downloads_sent": False,
        "proposed_filters": {},
        "filters_applied": {},
        "analysis_objective": "",
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





def _apply_agent_selection(state: dict[str, Any], selected: list[str]) -> None:
    state["selected_agents"] = list(selected)
    state["critique_enabled"] = "critique" in selected


async def _send_agent_settings(selected: list[str]) -> None:
    settings = await cl.ChatSettings(
        [
            Switch(id="critique_enabled", label="Enable Deep Analysis", initial=False),
        ]
    ).send()


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
            label="ATT X Promotion Issues",
            message="Can you check what promotion related issues ATT customers are facing?",
            icon="https://img.icons8.com/fluency/96/discount.png",
        ),
        cl.Starter(
            label="ATT X Rewards Friction Analysis",
            message="Analyze the key friction points ATT card customers face regarding rewards realted activities",
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

    # Send deferred download buttons from chat resume (must happen after UI settles)
    if state.get("_downloads_pending_resume"):
        state.pop("_downloads_pending_resume", None)
        await _maybe_send_downloads(thread_id, state)

    user_text = message.content or "Proceed"
    log.info("User message: %s", user_text[:80])
    _apply_agent_selection(state, cl.user_session.get("selected_agents") or DEFAULT_SELECTED_AGENTS)
    state["thread_id"] = thread_id

    config = {"configurable": {"thread_id": thread_id}}
    task_list: cl.TaskList | None = cl.user_session.get("task_list")
    displayed_msg_ids: set[str] = set()  # ID-level dedupe safety net
    displayed_msg_norms: set[str] = set()  # text-level dedupe safety net
    was_complete_before_run = bool(state.get("analysis_complete"))
    downloads_reset_for_run = False

    # Resume from checkpoint or start fresh
    snapshot = graph.get_state(config)
    waiting_for_resume = bool(snapshot and snapshot.next)
    human_msg = HumanMessage(content=user_text)

    if waiting_for_resume:
        graph_input = Command(resume=user_text, update={"messages": [human_msg]})
        log.info("Resuming graph (next=%s)", snapshot.next)
    else:
        state["messages"].append(human_msg)
        graph_input = state
        log.info("Fresh graph run (messages=%d)", len(state["messages"]))

    # Collapsible reasoning step
    reasoning_step = cl.Step(name="Reasoning", type="run")
    reasoning_step.output = ""
    # await reasoning_step.send()

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
                    if not reasoning_step.output:
                        await reasoning_step.send()
                    step_name = r.get("step_name", node_name)
                    step_text = r.get("step_text", "")
                    if not _should_surface_reasoning(step_name, step_text):
                        continue
                    reasoning_step.output += f"**{step_name}** - {step_text}\n\n"
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
                    elif k == "reasoning" and isinstance(v, list):
                        state.setdefault(k, []).extend(v)
                    elif k == "execution_trace" and isinstance(v, list):
                        state.setdefault(k, []).extend(v)
                    else:
                        state[k] = v

                # Mid-stream checkpoint: persist state after key nodes so
                # a crash during later stages doesn't lose prior work.
                if node_name in {"data_analyst", "friction_analysis", "report_drafts", "artifact_writer"}:
                    cl.user_session.set("state", state)
                    await save_analysis_state(thread_id, state)
                    log.info("Mid-stream checkpoint saved after %s", node_name)

        reasoning_step.status = "success"
        await reasoning_step.update()
        log.info("Graph stream complete. plan=%d/%d",
                 state.get("plan_steps_completed", 0), state.get("plan_steps_total", 0))

        # Check if input is required after all nodes
        final_snapshot = graph.get_state(config)
        is_interrupted = bool(final_snapshot and final_snapshot.next)

        # Surface pending checkpoint prompt to the user.
        if is_interrupted and final_snapshot.tasks:
            for task in final_snapshot.tasks:
                for intr in getattr(task, "interrupts", ()):
                    payload = getattr(intr, "value", None)
                    if isinstance(payload, dict):
                        info = payload.get("message", "")
                        prompt = payload.get("prompt", "")
                        # Show interrupt info + prompt as a single message
                        combined = "\n\n".join(p for p in [info, prompt] if p)
                        if combined:
                            await cl.Message(content=combined).send()
                        log.info("Checkpoint prompt displayed (type=%s)", payload.get("type", "?"))
                        break
                else:
                    continue
                break

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
        # Save whatever state we have so user can resume from last good point
        cl.user_session.set("state", state)
        await save_analysis_state(thread_id, state)
        log.info("State saved on error for recovery (thread=%s)", thread_id)
        reasoning_step.status = "failed"
        await reasoning_step.update()
        active_node_msg.content = "Error occurred."
        await active_node_msg.update()
        await cl.Message(content=f"System error: {exc}", author="System").send()
        raise  # re-raise so the full traceback is visible
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
    log.info("Chat end")

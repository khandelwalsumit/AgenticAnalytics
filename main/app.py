"""Chainlit application entry point.

Run with: chainlit run app.py

When ``VERBOSE`` is enabled in config/settings.py every graph node renders
its full tool calls, AI messages, and timing as nested Chainlit Steps.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import chainlit as cl
from langchain_core.messages import HumanMessage

from agents.graph import build_graph
from agents.state import AnalyticsState
from config.settings import AGENTS_DIR, CACHE_DIR, DATA_DIR, THREAD_STATES_DIR, VERBOSE
from core.agent_factory import AgentFactory
from core.data_store import DataStore
from core.file_data_layer import FileDataLayer
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY, set_analysis_deps
from tools.data_tools import set_data_store as set_data_tools_store
from tools.report_tools import set_data_store as set_report_tools_store
from ui.chat_history import (
    load_analysis_state,
    save_analysis_state,
)
from ui.components import (
    create_task_list,
    hide_awaiting_input,
    hide_thinking,
    send_agent_step,
    send_download_buttons,
    send_plan_banner,
    send_verbose_node_step,
    show_awaiting_input,
    show_thinking,
    update_plan_progress,
    update_task_list,
)


# ------------------------------------------------------------------
# Authentication (required for chat history sidebar)
# ------------------------------------------------------------------


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    """Simple auth — accepts any credentials for local development.

    Replace with real validation for production.
    """
    return cl.User(
        identifier=username,
        metadata={"role": "admin", "provider": "credentials"},
    )


# ------------------------------------------------------------------
# Data layer (required for chat history sidebar)
# ------------------------------------------------------------------


@cl.data_layer
def get_data_layer():
    """Provide a file-based data layer for thread persistence."""
    return FileDataLayer()


# ------------------------------------------------------------------
# Chat start
# ------------------------------------------------------------------


@cl.on_chat_start
async def on_chat_start():
    """Initialize session: build graph, create DataStore, set up state."""
    session_id = str(uuid.uuid4())[:12]

    # Create session-scoped DataStore
    data_store = DataStore(session_id=session_id, cache_dir=str(CACHE_DIR))

    # Bind DataStore to tools
    set_data_tools_store(data_store)
    set_report_tools_store(data_store)

    # Create SkillLoader
    skill_loader = SkillLoader()
    set_analysis_deps(data_store, skill_loader)

    # Create AgentFactory with tool registry
    agent_factory = AgentFactory(
        definitions_dir=AGENTS_DIR,
        tool_registry=TOOL_REGISTRY,
    )

    # Build the graph
    graph = build_graph(
        agent_factory=agent_factory,
        skill_loader=skill_loader,
    )

    # Store in session
    cl.user_session.set("graph", graph)
    cl.user_session.set("data_store", data_store)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("thread_id", str(uuid.uuid4()))
    cl.user_session.set("critique_enabled", False)

    # Initial state
    initial_state: dict[str, Any] = {
        "messages": [],
        "user_focus": "",
        "analysis_type": "",
        "selected_skills": [],
        "critique_enabled": False,
        "current_plan": {},
        "plan_steps_total": 0,
        "plan_steps_completed": 0,
        "plan_tasks": [],
        "execution_trace": [],
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
        "requires_user_input": False,
        "checkpoint_message": "",
        "phase": "analysis",
        "analysis_complete": False,
        "analysis_scope": {
            "dataset_path": "",
            "filters": {},
            "skills_used": [],
            "buckets_created": [],
            "focus_column": "",
        },
        "agent_reasoning": [],
    }
    cl.user_session.set("state", initial_state)

    # Welcome message
    verbose_note = " (`VERBOSE` mode is **ON** — you'll see detailed agent steps.)" if VERBOSE else ""
    await cl.Message(
        content=(
            "## Welcome to AgenticAnalytics\n\n"
            "I'm a multi-agent analytics system that helps you explore "
            "customer experience data, identify friction points, and generate "
            "actionable reports.\n\n"
            "**To get started:**\n"
            "1. Upload a CSV file with your call data\n"
            "2. Tell me what you'd like to focus on\n\n"
            "You can toggle **Critique Mode** in settings for QA validation "
            f"of analysis outputs.{verbose_note}"
        ),
    ).send()


# ------------------------------------------------------------------
# Message handler
# ------------------------------------------------------------------


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages and file uploads."""
    graph = cl.user_session.get("graph")
    state = cl.user_session.get("state")
    data_store: DataStore = cl.user_session.get("data_store")
    session_id = cl.user_session.get("session_id")
    thread_id = cl.user_session.get("thread_id")

    # Handle file uploads
    if message.elements:
        for element in message.elements:
            if hasattr(element, "path") and element.path:
                file_path = element.path
                dest = Path(DATA_DIR) / f"{session_id}_{Path(file_path).name}"
                dest.parent.mkdir(parents=True, exist_ok=True)

                import shutil
                shutil.copy2(file_path, dest)

                state["dataset_path"] = str(dest)
                user_text = message.content or f"I've uploaded a dataset: {dest.name}. Please load and analyze it."
                break
    else:
        user_text = message.content

    # Remove awaiting-input indicator if it exists
    awaiting_indicator: cl.Message | None = cl.user_session.get("awaiting_indicator")
    if awaiting_indicator:
        await hide_awaiting_input(awaiting_indicator)
        cl.user_session.set("awaiting_indicator", None)

    # Add user message to state
    state["messages"].append(HumanMessage(content=user_text))

    # Update critique setting from session
    state["critique_enabled"] = cl.user_session.get("critique_enabled", False)

    # Show thinking indicator
    thinking_step = await show_thinking("Processing")

    # Invoke graph
    config = {"configurable": {"thread_id": thread_id}}
    task_list_widget: cl.TaskList | None = cl.user_session.get("task_list_widget")

    try:
        async for event in graph.astream(state, config=config, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "__end__":
                    continue

                # -- Verbose mode: show full node details ------------------
                reasoning = node_output.get("agent_reasoning", [])
                if reasoning:
                    latest = reasoning[-1]

                    if VERBOSE and latest.get("verbose"):
                        await send_verbose_node_step(node_name, latest)
                    else:
                        await send_agent_step(
                            agent_name=latest.get("step_name", node_name),
                            step_text=latest.get("step_text", ""),
                        )

                # -- Live task list updates --------------------------------
                new_tasks = node_output.get("plan_tasks")
                if new_tasks is not None:
                    if task_list_widget is None and new_tasks:
                        task_list_widget = await create_task_list(new_tasks)
                        cl.user_session.set("task_list_widget", task_list_widget)
                    elif task_list_widget is not None:
                        await update_task_list(task_list_widget, new_tasks)

                # Update plan progress
                if node_output.get("plan_steps_total", 0) > 0:
                    await update_plan_progress(node_output)

                # Handle checkpoint messages — show blinking indicator
                if node_output.get("requires_user_input"):
                    # Hide thinking while waiting for user
                    await hide_thinking(thinking_step)
                    thinking_step = None

                    checkpoint_msg = node_output.get(
                        "checkpoint_message", "Please review and provide your input."
                    )
                    indicator = await show_awaiting_input(checkpoint_msg)
                    cl.user_session.set("awaiting_indicator", indicator)

                # Check for final messages from agents
                new_messages = node_output.get("messages", [])
                for msg in new_messages:
                    if hasattr(msg, "content") and msg.content and msg.type == "ai":
                        content = msg.content
                        if isinstance(content, list):
                            text_blocks = []
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text_blocks.append(block.get("text", ""))
                                elif isinstance(block, str):
                                    text_blocks.append(block)
                            content = " ".join(text_blocks)
                        if content:
                            await cl.Message(content=content).send()

                # Update state
                state.update(node_output)

        # Hide thinking indicator when graph finishes
        await hide_thinking(thinking_step)

        # Check if analysis is complete — offer downloads
        if state.get("analysis_complete") and state.get("report_file_path"):
            await send_download_buttons(
                report_path=state.get("report_file_path"),
                data_path=state.get("data_file_path"),
            )

            # Mark all tasks as done in the task list
            if task_list_widget is not None:
                final_tasks = state.get("plan_tasks", [])
                done_tasks = [
                    {**t, "status": "done"} for t in final_tasks
                ]
                await update_task_list(task_list_widget, done_tasks)

            # Transition to Q&A mode
            state["phase"] = "qa"
            await cl.Message(
                content=(
                    "---\n"
                    "**Analysis complete!** You can now ask follow-up questions "
                    "about the findings. I'll answer using the existing analysis data.\n\n"
                    "For a completely new analysis, start a **New Chat**."
                ),
            ).send()

    except Exception as e:
        await hide_thinking(thinking_step)
        await cl.Message(
            content=f"An error occurred: {str(e)}",
            author="System",
        ).send()

    # Persist state
    cl.user_session.set("state", state)
    await save_analysis_state(thread_id, state)


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------


@cl.on_settings_update
async def on_settings_update(settings: dict):
    """Handle settings changes (critique toggle)."""
    if "critique_enabled" in settings:
        cl.user_session.set("critique_enabled", settings["critique_enabled"])
        status = "enabled" if settings["critique_enabled"] else "disabled"
        await cl.Message(
            content=f"Critique mode **{status}**.",
            author="System",
        ).send()


# ------------------------------------------------------------------
# Chat resume (pick up where you left off)
# ------------------------------------------------------------------


@cl.on_chat_resume
async def on_chat_resume(thread: dict):
    """Resume a previous chat session.

    Chainlit calls this when a user clicks on a past thread in the sidebar.
    We reload the saved analysis state so the graph continues from where
    the user left off.
    """
    thread_id = thread.get("id", "")

    saved = await load_analysis_state(thread_id)
    if saved:
        cl.user_session.set("thread_id", thread_id)
        cl.user_session.set("critique_enabled", saved.get("critique_enabled", False))

        phase = saved.get("phase", "analysis")
        findings_count = saved.get("findings_count", 0)
        completed = saved.get("plan_steps_completed", 0)
        total = saved.get("plan_steps_total", 0)

        status_parts = [f"**Phase:** {phase}"]
        if total > 0:
            status_parts.append(f"**Progress:** {completed}/{total} steps")
        if findings_count > 0:
            status_parts.append(f"**Findings:** {findings_count}")

        await cl.Message(
            content=(
                "## Session Resumed\n\n"
                + " | ".join(status_parts) + "\n\n"
                "Continue where you left off — ask a question or provide the next input."
            ),
        ).send()
    else:
        await cl.Message(
            content="Could not restore previous session state. Starting fresh.",
            author="System",
        ).send()


# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------


@cl.on_chat_end
async def on_chat_end():
    """Clean up session resources."""
    data_store: DataStore | None = cl.user_session.get("data_store")
    if data_store:
        data_store.cleanup()

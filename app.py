"""Chainlit application entry point.

Run with: chainlit run app.py
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import chainlit as cl
from langchain_core.messages import HumanMessage

from agents.graph import build_graph
from agents.state import AnalyticsState
from config.settings import AGENTS_DIR, CACHE_DIR, DATA_DIR
from core.agent_factory import AgentFactory
from core.data_store import DataStore
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY, set_analysis_deps
from tools.data_tools import set_data_store as set_data_tools_store
from tools.report_tools import set_data_store as set_report_tools_store
from ui.chat_history import save_analysis_state
from ui.components import (
    send_agent_step,
    send_download_buttons,
    send_plan_banner,
    send_waiting_indicator,
    update_plan_progress,
)


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
        "execution_trace": [],
        "dataset_path": "",
        "dataset_schema": {},
        "active_filters": {},
        "data_buckets": {},
        "findings": [],
        "domain_analysis": {},
        "operational_analysis": {},
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
            "of analysis outputs."
        ),
    ).send()


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
                # Copy to data dir for persistence
                dest = Path(DATA_DIR) / f"{session_id}_{Path(file_path).name}"
                dest.parent.mkdir(parents=True, exist_ok=True)

                import shutil
                shutil.copy2(file_path, dest)

                state["dataset_path"] = str(dest)
                user_text = message.content or f"I've uploaded a dataset: {dest.name}. Please load and analyze it."
                break
    else:
        user_text = message.content

    # Add user message to state
    state["messages"].append(HumanMessage(content=user_text))

    # Update critique setting from session
    state["critique_enabled"] = cl.user_session.get("critique_enabled", False)

    # Invoke graph
    config = {"configurable": {"thread_id": thread_id}}

    try:
        # Stream graph execution
        async for event in graph.astream(state, config=config, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "__end__":
                    continue

                # Show agent reasoning step
                reasoning = node_output.get("agent_reasoning", [])
                if reasoning:
                    latest = reasoning[-1]
                    await send_agent_step(
                        agent_name=latest.get("step_name", node_name),
                        step_text=latest.get("step_text", ""),
                    )

                # Update plan progress
                if node_output.get("plan_steps_total", 0) > 0:
                    await update_plan_progress(node_output)

                # Handle checkpoint messages
                if node_output.get("requires_user_input"):
                    checkpoint_msg = node_output.get(
                        "checkpoint_message", "Please review and provide your input."
                    )
                    await send_waiting_indicator(checkpoint_msg)

                # Check for final messages from agents
                new_messages = node_output.get("messages", [])
                for msg in new_messages:
                    if hasattr(msg, "content") and msg.content and msg.type == "ai":
                        await cl.Message(content=msg.content).send()

                # Update state
                state.update(node_output)

        # Check if analysis is complete — offer downloads
        if state.get("analysis_complete") and state.get("report_file_path"):
            await send_download_buttons(
                report_path=state.get("report_file_path"),
                data_path=state.get("data_file_path"),
            )

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
        await cl.Message(
            content=f"An error occurred: {str(e)}",
            author="System",
        ).send()

    # Persist state
    cl.user_session.set("state", state)
    await save_analysis_state(thread_id, state)


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


@cl.on_chat_end
async def on_chat_end():
    """Clean up session resources."""
    data_store: DataStore | None = cl.user_session.get("data_store")
    if data_store:
        data_store.cleanup()

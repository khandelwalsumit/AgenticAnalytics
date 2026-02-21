"""Chainlit UI components: banner, reasoning steps, indicators, live task list.

When ``VERBOSE`` is enabled, additional nested Steps are rendered showing
tool calls (with arguments and results), full AI responses, and timing.
"""

from __future__ import annotations

from typing import Any

import chainlit as cl

from config.settings import (
    MAX_DISPLAY_LENGTH,
    SHOW_NODE_IO,
    SHOW_SUPERVISOR_REASONING,
    SHOW_TOOL_CALLS,
    VERBOSE,
)


# ------------------------------------------------------------------
# Thinking indicator
# ------------------------------------------------------------------


async def show_thinking(label: str = "Thinking") -> cl.Step:
    """Show a spinning/thinking indicator while the system is processing.

    Returns the Step so the caller can close it when processing finishes.
    """
    step = cl.Step(name=f"⏳ {label}...", type="run")
    step.show_input = False
    await step.send()
    return step


async def hide_thinking(step: cl.Step | None) -> None:
    """Remove / finalize a thinking indicator."""
    if step is None:
        return
    step.name = f"✅ {step.name.replace('⏳ ', '').replace('...', '')} — done"
    await step.update()


# ------------------------------------------------------------------
# Blinking awaiting indicator
# ------------------------------------------------------------------


async def show_awaiting_input(message: str = "Your input is needed") -> cl.Message:
    """Show a highly-visible blinking/pulsing indicator when the system
    needs user input.

    The message uses prominent formatting so it stands out.

    Returns the Message so the caller can remove it later.
    """
    indicator = cl.Message(
        content=(
            "---\n"
            "### 🔴  Awaiting Your Response\n\n"
            f"**{message}**\n\n"
            "_Reply below to continue the analysis..._\n"
            "---"
        ),
        author="System",
    )
    await indicator.send()
    return indicator


async def hide_awaiting_input(indicator: cl.Message | None) -> None:
    """Remove the awaiting-input indicator."""
    if indicator is None:
        return
    await indicator.remove()


# ------------------------------------------------------------------
# Live Task List (Chainlit TaskList)
# ------------------------------------------------------------------


async def create_task_list(tasks: list[dict[str, str]]) -> cl.TaskList:
    """Create and send a live-updating task list from plan tasks.

    Args:
        tasks: List of dicts with ``title``, ``agent``, ``status``.
               Status: ready | running | done | failed

    Returns:
        The TaskList object for subsequent updates.
    """
    task_list = cl.TaskList()
    task_list.status = "Running..."

    for t in tasks:
        status = _map_status(t.get("status", "ready"))
        task = cl.Task(title=t["title"], status=status)
        await task_list.add_task(task)

    await task_list.send()
    return task_list


async def update_task_list(
    task_list: cl.TaskList,
    tasks: list[dict[str, str]],
) -> None:
    """Update an existing task list with new statuses.

    Matches tasks by title and updates their status.

    Args:
        task_list: The existing Chainlit TaskList.
        tasks: Updated task list from state.
    """
    # Build a lookup by title from new state
    status_by_title = {t["title"]: t.get("status", "ready") for t in tasks}

    for cl_task in task_list.tasks:
        new_status = status_by_title.get(cl_task.title)
        if new_status:
            cl_task.status = _map_status(new_status)

    # Determine overall status
    statuses = [t.get("status", "ready") for t in tasks]
    if all(s == "done" for s in statuses):
        task_list.status = "Done ✅"
    elif any(s == "failed" for s in statuses):
        task_list.status = "Failed ❌"
    elif any(s == "running" for s in statuses):
        task_list.status = "Running..."
    else:
        task_list.status = "Ready"

    await task_list.send()


def _map_status(status: str) -> cl.TaskStatus:
    """Map string status to Chainlit TaskStatus enum."""
    return {
        "ready": cl.TaskStatus.READY,
        "running": cl.TaskStatus.RUNNING,
        "done": cl.TaskStatus.DONE,
        "failed": cl.TaskStatus.FAILED,
    }.get(status, cl.TaskStatus.READY)


# ------------------------------------------------------------------
# Plan banner
# ------------------------------------------------------------------


async def send_plan_banner(
    current_step: str,
    step_number: int,
    total_steps: int,
    completed_steps: list[str] | None = None,
) -> None:
    """Display a plan progress banner at the top of the chat."""
    completed_steps = completed_steps or []
    progress_pct = int((step_number - 1) / max(total_steps, 1) * 100)

    lines = [f"**Analysis Pipeline** — Step {step_number} of {total_steps}"]

    filled = int(progress_pct / 5)
    bar = "█" * filled + "░" * (20 - filled)
    lines.append(f"`[{bar}]` {progress_pct}%")

    for step in completed_steps:
        lines.append(f"  ✅ {step}")

    lines.append(f"  🔄 **{current_step}**")

    content = "\n".join(lines)

    banner_msg = cl.user_session.get("plan_banner_msg")
    if not banner_msg:
        banner_msg = cl.Message(content=content, author="Pipeline")
        await banner_msg.send()
        cl.user_session.set("plan_banner_msg", banner_msg)
    else:
        banner_msg.content = content
        await banner_msg.update()


# ------------------------------------------------------------------
# Agent reasoning step (basic)
# ------------------------------------------------------------------


async def send_agent_step(
    agent_name: str,
    step_text: str,
) -> cl.Step:
    """Render an agent execution step as a collapsible Chainlit Step."""
    async with cl.Step(name=agent_name, type="tool") as step:
        step.output = step_text
    return step


# ------------------------------------------------------------------
# Verbose node step — full details
# ------------------------------------------------------------------


async def send_verbose_node_step(
    node_name: str,
    reasoning_entry: dict[str, Any],
) -> None:
    """Render a detailed, verbose node step with nested sub-steps."""
    agent_name = reasoning_entry.get("step_name", node_name)
    step_text = reasoning_entry.get("step_text", "")
    verbose = reasoning_entry.get("verbose", {})

    elapsed_ms = verbose.get("elapsed_ms", 0)
    tool_calls = verbose.get("tool_calls", [])
    ai_messages = verbose.get("ai_messages", [])
    msg_count = verbose.get("message_count", 0)

    header = f"{agent_name}  ({elapsed_ms}ms, {msg_count} messages)"

    async with cl.Step(name=header, type="tool") as parent_step:
        if SHOW_NODE_IO and step_text:
            parent_step.output = _truncate(step_text, MAX_DISPLAY_LENGTH)

        if SHOW_TOOL_CALLS and tool_calls:
            for tc in tool_calls:
                tool_label = f"🔧 {tc['name']}"
                async with cl.Step(name=tool_label, type="tool") as tool_step:
                    body = f"**Args:**\n```json\n{tc['args_preview']}\n```"
                    if tc.get("result_preview"):
                        body += f"\n\n**Result:**\n```\n{tc['result_preview']}\n```"
                    tool_step.output = body

        if ai_messages:
            for i, ai_text in enumerate(ai_messages):
                label = "💬 AI Response" if len(ai_messages) == 1 else f"💬 AI Response {i + 1}"
                async with cl.Step(name=label, type="llm") as ai_step:
                    ai_step.output = _truncate(ai_text, MAX_DISPLAY_LENGTH)

        if SHOW_SUPERVISOR_REASONING and node_name == "supervisor":
            if step_text:
                async with cl.Step(name="🧠 Supervisor Reasoning", type="llm") as reason_step:
                    reason_step.output = _truncate(step_text, MAX_DISPLAY_LENGTH)


# ------------------------------------------------------------------
# Waiting indicator (legacy — kept for backward compat)
# ------------------------------------------------------------------


async def send_waiting_indicator(message: str = "Awaiting your input...") -> cl.Message:
    """Show a waiting indicator. Prefer ``show_awaiting_input`` for new code."""
    return await show_awaiting_input(message)


# ------------------------------------------------------------------
# Download buttons
# ------------------------------------------------------------------


async def send_download_buttons(
    report_path: str | None = None,
    data_path: str | None = None,
) -> None:
    """Render download action buttons for report and data files."""
    elements = []

    if report_path:
        elements.append(
            cl.File(name="report.pptx", path=report_path, display="inline")
        )

    if data_path:
        elements.append(
            cl.File(name="data.csv", path=data_path, display="inline")
        )

    if elements:
        await cl.Message(
            content="📥 **Downloads ready:**",
            elements=elements,
        ).send()


# ------------------------------------------------------------------
# Critique toggle
# ------------------------------------------------------------------


async def send_critique_toggle(enabled: bool) -> None:
    """Display the current critique toggle state."""
    status = "ON ✅" if enabled else "OFF ⬜"
    await cl.Message(
        content=f"**Critique Mode:** {status}\n\nUse the settings panel to toggle.",
        author="System",
    ).send()


# ------------------------------------------------------------------
# Plan progress
# ------------------------------------------------------------------


async def update_plan_progress(state: dict[str, Any]) -> None:
    """Update the plan banner based on current state."""
    plan = state.get("current_plan", {})
    completed = state.get("plan_steps_completed", 0)
    total = state.get("plan_steps_total", 0)

    if total > 0:
        reasoning = state.get("agent_reasoning", [])
        completed_names = [r["step_name"] for r in reasoning]
        current_step = plan.get("task_description", "Processing...")

        await send_plan_banner(
            current_step=current_step,
            step_number=completed + 1,
            total_steps=total,
            completed_steps=completed_names[-5:],
        )


# ------------------------------------------------------------------
# Chat history sidebar helpers
# ------------------------------------------------------------------


async def send_chat_history_actions(sessions: list[dict[str, Any]]) -> None:
    """Render past sessions as resumable actions in a message."""
    if not sessions:
        return

    lines = ["**Previous Sessions:**\n"]
    for s in sessions[:10]:
        label = s.get("label", s["thread_id"][:8])
        summary = s.get("summary", "")
        lines.append(f"- **{label}** — {summary}")

    await cl.Message(content="\n".join(lines), author="System").send()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _truncate(text: str, limit: int = MAX_DISPLAY_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... (truncated, {len(text)} chars total)"


def _pretty(node_name: str) -> str:
    """Human-readable agent name."""
    return node_name.replace("_", " ").title()

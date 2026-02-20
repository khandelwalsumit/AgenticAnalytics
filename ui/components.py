"""Chainlit UI components: banner, reasoning steps, waiting indicator, download buttons."""

from __future__ import annotations

from typing import Any

import chainlit as cl


async def send_plan_banner(
    current_step: str,
    step_number: int,
    total_steps: int,
    completed_steps: list[str] | None = None,
) -> None:
    """Display a plan progress banner at the top of the chat.

    Args:
        current_step: Description of the current step.
        step_number: Current step number (1-indexed).
        total_steps: Total planned steps.
        completed_steps: List of completed step descriptions.
    """
    completed_steps = completed_steps or []
    progress_pct = int((step_number - 1) / max(total_steps, 1) * 100)

    # Build progress display
    lines = [f"**Analysis Pipeline** — Step {step_number} of {total_steps}"]

    # Progress bar
    filled = int(progress_pct / 5)
    bar = "█" * filled + "░" * (20 - filled)
    lines.append(f"`[{bar}]` {progress_pct}%")

    # Completed steps
    for step in completed_steps:
        lines.append(f"  ✅ {step}")

    # Current step
    lines.append(f"  🔄 **{current_step}**")

    content = "\n".join(lines)

    # Send as a system message element
    await cl.Message(
        content=content,
        author="Pipeline",
    ).send()


async def send_agent_step(
    agent_name: str,
    step_text: str,
) -> cl.Step:
    """Render an agent execution step as a collapsible Chainlit Step.

    Args:
        agent_name: Display name for the agent.
        step_text: The reasoning/output text.

    Returns:
        The created Step for potential updates.
    """
    async with cl.Step(name=agent_name, type="tool") as step:
        step.output = step_text
    return step


async def send_waiting_indicator(message: str = "Awaiting your input...") -> cl.Message:
    """Show a pulsing waiting indicator when awaiting user confirmation.

    Args:
        message: The message to display.

    Returns:
        The message object (can be removed later).
    """
    indicator = cl.Message(
        content=f"⏳ **{message}**",
        author="System",
    )
    await indicator.send()
    return indicator


async def send_download_buttons(
    report_path: str | None = None,
    data_path: str | None = None,
) -> None:
    """Render download action buttons for report and data files.

    Args:
        report_path: Path to the .pptx report file.
        data_path: Path to the CSV data file.
    """
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


async def send_critique_toggle(enabled: bool) -> None:
    """Display the current critique toggle state.

    Args:
        enabled: Whether critique is currently enabled.
    """
    status = "ON ✅" if enabled else "OFF ⬜"
    await cl.Message(
        content=f"**Critique Mode:** {status}\n\nUse the settings panel to toggle.",
        author="System",
    ).send()


async def update_plan_progress(state: dict[str, Any]) -> None:
    """Update the plan banner based on current state."""
    plan = state.get("current_plan", {})
    completed = state.get("plan_steps_completed", 0)
    total = state.get("plan_steps_total", 0)

    if total > 0:
        # Gather completed step names from reasoning
        reasoning = state.get("agent_reasoning", [])
        completed_names = [r["step_name"] for r in reasoning]
        current_step = plan.get("task_description", "Processing...")

        await send_plan_banner(
            current_step=current_step,
            step_number=completed + 1,
            total_steps=total,
            completed_steps=completed_names[-5:],  # Last 5
        )

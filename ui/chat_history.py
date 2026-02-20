"""Chat history persistence using Chainlit's built-in thread management."""

from __future__ import annotations

from typing import Any


async def get_thread_history(thread_id: str) -> list[dict[str, Any]]:
    """Retrieve conversation history for a thread.

    Chainlit handles thread persistence internally via its data layer.
    This module provides helper utilities for working with thread data.

    Args:
        thread_id: The Chainlit thread ID.

    Returns:
        List of message dicts from the thread.
    """
    # Chainlit's built-in persistence handles this via config.
    # This function is a placeholder for custom history logic if needed.
    return []


async def save_analysis_state(thread_id: str, state: dict[str, Any]) -> None:
    """Persist analysis state metadata alongside the chat thread.

    Args:
        thread_id: The Chainlit thread ID.
        state: The AnalyticsState snapshot to persist.
    """
    import json
    from pathlib import Path

    state_dir = Path(".cache") / "thread_states"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Save serializable subset of state
    serializable = {
        "user_focus": state.get("user_focus", ""),
        "analysis_type": state.get("analysis_type", ""),
        "selected_skills": state.get("selected_skills", []),
        "phase": state.get("phase", "analysis"),
        "analysis_complete": state.get("analysis_complete", False),
        "plan_steps_completed": state.get("plan_steps_completed", 0),
        "plan_steps_total": state.get("plan_steps_total", 0),
        "findings_count": len(state.get("findings", [])),
    }

    state_path = state_dir / f"{thread_id}.json"
    state_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


async def load_analysis_state(thread_id: str) -> dict[str, Any] | None:
    """Load persisted analysis state for a thread.

    Args:
        thread_id: The Chainlit thread ID.

    Returns:
        The saved state dict, or None if not found.
    """
    import json
    from pathlib import Path

    state_path = Path(".cache") / "thread_states" / f"{thread_id}.json"
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return None

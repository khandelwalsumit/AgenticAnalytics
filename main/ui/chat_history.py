"""Chat history persistence for session resume.

Saves a lightweight metadata snapshot of each analysis session to disk.
On the next ``on_chat_start`` the sidebar lists past sessions so the user
can pick up where they left off.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import THREAD_STATES_DIR


# ------------------------------------------------------------------
# Save
# ------------------------------------------------------------------


async def save_analysis_state(thread_id: str, state: dict[str, Any]) -> None:
    """Persist analysis state metadata alongside the chat thread.

    Only a serialisable subset is stored — no DataFrames, no raw messages.

    Args:
        thread_id: The Chainlit thread ID.
        state: The AnalyticsState snapshot to persist.
    """
    THREAD_STATES_DIR.mkdir(parents=True, exist_ok=True)

    serializable: dict[str, Any] = {}
    for key, value in state.items():
        if key == "messages":
            continue
        try:
            json.dumps(value)
            serializable[key] = value
        except (TypeError, ValueError):
            continue

    serializable["thread_id"] = thread_id
    serializable["saved_at"] = datetime.now(timezone.utc).isoformat()
    serializable["findings_count"] = len(state.get("findings", []))

    state_path = THREAD_STATES_DIR / f"{thread_id}.json"
    state_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


# ------------------------------------------------------------------
# Load single session
# ------------------------------------------------------------------


async def load_analysis_state(thread_id: str) -> dict[str, Any] | None:
    """Load persisted analysis state for a thread.

    Args:
        thread_id: The Chainlit thread ID.

    Returns:
        The saved state dict, or None if not found.
    """
    state_path = THREAD_STATES_DIR / f"{thread_id}.json"
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return None


# ------------------------------------------------------------------
# List all saved sessions
# ------------------------------------------------------------------


async def list_saved_sessions(limit: int = 10) -> list[dict[str, Any]]:
    """Return most recent saved sessions for the chat history sidebar.

    Each entry contains enough metadata to display a summary line.

    Args:
        limit: Maximum number of sessions to return.

    Returns:
        List of session dicts sorted by saved_at (newest first),
        each containing: thread_id, label, summary.
    """
    if not THREAD_STATES_DIR.exists():
        return []

    sessions: list[dict[str, Any]] = []

    for path in THREAD_STATES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        thread_id = data.get("thread_id", path.stem)
        phase = data.get("phase", "analysis")
        focus = data.get("user_focus", "")
        findings_count = data.get("findings_count", len(data.get("findings", [])))
        completed = data.get("plan_steps_completed", 0)
        total = data.get("plan_steps_total", 0)
        saved_at = data.get("saved_at", "")
        dataset = data.get("dataset_path", "")

        # Build human-readable label
        if focus:
            label = focus[:40]
        elif dataset:
            label = Path(dataset).stem[:30]
        else:
            label = thread_id[:8]

        # Build summary line
        parts = [f"Phase: {phase}"]
        if total > 0:
            parts.append(f"{completed}/{total} steps")
        if findings_count > 0:
            parts.append(f"{findings_count} findings")
        if saved_at:
            # Show just date
            try:
                dt = datetime.fromisoformat(saved_at)
                parts.append(dt.strftime("%b %d %H:%M"))
            except ValueError:
                pass

        sessions.append({
            "thread_id": thread_id,
            "label": label,
            "summary": " · ".join(parts),
            "saved_at": saved_at,
        })

    # Sort by saved_at descending (newest first)
    sessions.sort(key=lambda s: s.get("saved_at", ""), reverse=True)
    return sessions[:limit]


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------


async def delete_session(thread_id: str) -> bool:
    """Remove a saved session state file.

    Args:
        thread_id: The Chainlit thread ID.

    Returns:
        True if deleted, False if not found.
    """
    state_path = THREAD_STATES_DIR / f"{thread_id}.json"
    if state_path.exists():
        state_path.unlink()
        return True
    return False

"""Chat history persistence — save/load analysis state to disk as JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import THREAD_STATES_DIR


async def save_analysis_state(thread_id: str, state: dict[str, Any]) -> None:
    """Persist analysis state to disk."""
    THREAD_STATES_DIR.mkdir(parents=True, exist_ok=True)

    # Serialize messages as plain dicts
    messages = []
    for m in state.get("messages", []):
        role = str(getattr(m, "type", "") or "").strip().lower()
        if role not in {"human", "ai"}:
            continue
        content = getattr(m, "content", None)
        if content is None or content == "":
            continue
        messages.append({"role": role, "content": content})

    # Keep only JSON-safe values
    out: dict[str, Any] = {"messages": messages}
    for k, v in state.items():
        if k == "messages":
            continue
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            pass

    out["thread_id"] = thread_id
    out["saved_at"] = datetime.now(timezone.utc).isoformat()

    path = THREAD_STATES_DIR / f"{thread_id}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")


async def load_analysis_state(thread_id: str) -> dict[str, Any] | None:
    """Load persisted state for a thread, or None if not found."""
    path = THREAD_STATES_DIR / f"{thread_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None

"""Chainlit UI components: task list, awaiting indicator, downloads.

Matches the test blueprint graph contract:
  reasoning           : list[dict]  - [{step_name, step_text, verbose?}]
  plan_tasks          : list[dict]  - [{id, title, status, sub_agents?}]
  requires_user_input : bool
  checkpoint_message  : str
  checkpoint_prompt   : str
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import chainlit as cl

from config import DATA_DIR


# ------------------------------------------------------------------
# Task list helpers (hierarchical: parent tasks + sub_agents)
# ------------------------------------------------------------------


def _task_status(s: str) -> cl.TaskStatus:
    return {
        "in_progress": cl.TaskStatus.RUNNING,
        "done": cl.TaskStatus.DONE,
        "failed": cl.TaskStatus.FAILED,
        "blocked": cl.TaskStatus.FAILED,
    }.get(s, cl.TaskStatus.READY)


def _sub_title(a: dict) -> str:
    detail = a.get("detail", "")
    return f"  -> {a['title']}" + (f"  -  {detail}" if detail else "")


def _flatten_task_entries(tasks: list[dict]) -> list[dict]:
    """Expand parent tasks and sub-agents into a single ordered list.

    Sub-agent rows are placed immediately after their parent task.
    """
    rows: list[dict] = []
    for t in tasks:
        rows.append({
            "title": t["title"],
            "status": _task_status(t.get("status", "todo")),
        })
        for a in t.get("sub_agents", []):
            rows.append({
                "title": _sub_title(a),
                "status": _task_status(a.get("status", "todo")),
            })
    return rows


async def sync_task_list(
    tl: cl.TaskList | None,
    tasks: list[dict],
) -> cl.TaskList:
    """Create/update TaskList with stable ordering.

    Parent task is always followed immediately by its sub-agent rows.
    """
    desired_rows = _flatten_task_entries(tasks)

    if tl is None:
        tl = cl.TaskList()
        tl.status = "Running"
        for row in desired_rows:
            await tl.add_task(cl.Task(title=row["title"], status=row["status"]))
        await tl.send()
        return tl

    # Expand if needed
    while len(tl.tasks) < len(desired_rows):
        await tl.add_task(cl.Task(title="", status=cl.TaskStatus.READY))

    for idx, row in enumerate(desired_rows):
        tl.tasks[idx].title = row["title"]
        tl.tasks[idx].status = row["status"]

    # Trim if needed
    if len(tl.tasks) > len(desired_rows):
        tl.tasks = tl.tasks[:len(desired_rows)]

    await tl.send()
    return tl


# ------------------------------------------------------------------
# Awaiting input indicator (HTML pulse dot with custom CSS)
# ------------------------------------------------------------------


async def send_awaiting_input(prompt: str) -> cl.Message:
    """Send a blinking prompt that can be removed later."""
    html = (
        f'<div class="awaiting-input">'
        f'<span class="pulse-dot"></span> '
        f'{prompt}'
        f'</div>'
    )
    m = cl.Message(content=html)
    await m.send()
    return m


async def clear_awaiting_prompt() -> None:
    """Remove the stored awaiting prompt message if it exists."""
    prompt: cl.Message | None = cl.user_session.get("awaiting_prompt")
    if prompt:
        await prompt.remove()
        cl.user_session.set("awaiting_prompt", None)


# ------------------------------------------------------------------
# Download buttons
# ------------------------------------------------------------------


async def send_downloads(
    file_paths: list[str] | None = None,
    report_path: str = "",
    data_path: str = "",
    markdown_path: str = "",
) -> None:
    """Render download action buttons by looping over resolved files.

    Serves the actual generated files when they exist on disk.
    Falls back to a notification if files are missing.
    """
    def _resolve(path: str) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        p = Path(raw)
        if p.exists() and p.is_file():
            return str(p.resolve())
        if not p.is_absolute():
            alt = Path(DATA_DIR) / p.name
            if alt.exists() and alt.is_file():
                return str(alt.resolve())
        return ""

    source_paths = list(file_paths or [])
    if not source_paths:
        source_paths = [markdown_path, report_path, data_path]

    elements: list[Any] = []
    seen: set[str] = set()
    for raw_path in source_paths:
        resolved = _resolve(raw_path)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        if os.path.isfile(resolved):
            elements.append(
                cl.File(name=os.path.basename(resolved), path=resolved, display="inline")
            )

    if not elements:
        await cl.Message(
            content="Report generation complete but download files are not yet available.",
        ).send()
        return

    await cl.Message(
        content="**Your files are ready for download:**",
        elements=elements,
    ).send()

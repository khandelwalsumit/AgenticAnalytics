"""File-based Chainlit data layer for local chat history persistence.

Implements ``BaseDataLayer`` using JSON files on disk so the sidebar
shows past threads and users can resume conversations — no external
database required.

Register with ``@cl.data_layer`` in app.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chainlit.data import BaseDataLayer
from chainlit.step import StepDict
from chainlit.types import (
    Feedback,
    PageInfo,
    PaginatedResponse,
    Pagination,
    ThreadDict,
    ThreadFilter,
)
from chainlit.user import PersistedUser, User

from config import CACHE_DIR

# Storage root
_STORAGE_DIR = CACHE_DIR / "data_layer"
_THREADS_DIR = _STORAGE_DIR / "threads"
_USERS_DIR = _STORAGE_DIR / "users"


def _ensure_dirs() -> None:
    _THREADS_DIR.mkdir(parents=True, exist_ok=True)
    _USERS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# File-backed Data Layer
# ------------------------------------------------------------------


class FileDataLayer(BaseDataLayer):
    """Stores threads, steps, and users as JSON files under ``.cache/data_layer/``."""

    def __init__(self) -> None:
        _ensure_dirs()

    # -- Users --------------------------------------------------------------

    async def get_user(self, identifier: str) -> Optional[PersistedUser]:
        path = _USERS_DIR / f"{identifier}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return PersistedUser(**data)

    async def create_user(self, user: User) -> Optional[PersistedUser]:
        path = _USERS_DIR / f"{user.identifier}.json"
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                metadata = user.metadata or existing.get("metadata", {})
                if metadata != existing.get("metadata", {}):
                    existing["metadata"] = metadata
                    path.write_text(json.dumps(existing, default=str), encoding="utf-8")
                return PersistedUser(**existing)
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                pass

        persisted = PersistedUser(
            id=str(uuid.uuid4()),
            identifier=user.identifier,
            createdAt=_now_iso(),
            metadata=user.metadata or {},
        )
        path.write_text(
            json.dumps({
                "id": persisted.id,
                "identifier": persisted.identifier,
                "createdAt": persisted.createdAt,
                "metadata": persisted.metadata,
            }, default=str),
            encoding="utf-8",
        )
        return persisted

    # -- Threads ------------------------------------------------------------

    def _thread_path(self, thread_id: str) -> Path:
        return _THREADS_DIR / f"{thread_id}.json"

    def _load_thread(self, thread_id: str) -> dict | None:
        path = self._thread_path(thread_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_thread(self, thread_data: dict) -> None:
        path = self._thread_path(thread_data["id"])
        path.write_text(json.dumps(thread_data, default=str), encoding="utf-8")

    async def get_thread(self, thread_id: str) -> Optional[ThreadDict]:
        data = self._load_thread(thread_id)
        if data is None:
            return None
        return ThreadDict(
            id=data["id"],
            createdAt=data.get("createdAt", ""),
            name=data.get("name"),
            userId=data.get("userId"),
            userIdentifier=data.get("userIdentifier"),
            tags=data.get("tags"),
            metadata=data.get("metadata"),
            steps=data.get("steps", []),
            elements=data.get("elements"),
        )

    async def get_thread_author(self, thread_id: str) -> str:
        data = self._load_thread(thread_id)
        if data:
            return data.get("userIdentifier", "")
        return ""

    def _resolve_user_identifier(self, user_id: str) -> str:
        """Look up identifier from persisted user ID."""
        for path in _USERS_DIR.glob("*.json"):
            try:
                user_data = json.loads(path.read_text(encoding="utf-8"))
                if user_data.get("id") == user_id:
                    return user_data.get("identifier", "")
            except (json.JSONDecodeError, OSError):
                continue
        return ""

    async def update_thread(
        self,
        thread_id: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        data = self._load_thread(thread_id)
        if data is None:
            data = {
                "id": thread_id,
                "createdAt": _now_iso(),
                "steps": [],
                "elements": [],
            }
        if name is not None:
            data["name"] = name
        if user_id is not None:
            data["userId"] = user_id
            identifier = self._resolve_user_identifier(user_id)
            if identifier:
                data["userIdentifier"] = identifier
        if metadata is not None:
            data["metadata"] = metadata
        if tags is not None:
            data["tags"] = tags
        self._save_thread(data)

    async def delete_thread(self, thread_id: str) -> None:
        path = self._thread_path(thread_id)
        if path.exists():
            path.unlink()

    async def list_threads(
        self, pagination: Pagination, filters: ThreadFilter
    ) -> PaginatedResponse[ThreadDict]:
        """List threads for the sidebar, newest first."""
        filter_identifier = self._resolve_user_identifier(filters.userId) if filters.userId else ""
        all_threads: list[dict] = []
        for path in _THREADS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            # Apply user filter
            if filters.userId:
                same_user_id = data.get("userId") == filters.userId
                same_identifier = bool(filter_identifier) and data.get("userIdentifier") == filter_identifier
                if not (same_user_id or same_identifier):
                    continue

            # Apply search filter
            if filters.search:
                name = (data.get("name") or "").lower()
                if filters.search.lower() not in name:
                    continue

            all_threads.append(data)

        # Sort newest first
        all_threads.sort(key=lambda t: t.get("createdAt", ""), reverse=True)

        # Pagination
        start = 0
        if pagination.cursor:
            for i, t in enumerate(all_threads):
                if t["id"] == pagination.cursor:
                    start = i + 1
                    break

        page = all_threads[start : start + pagination.first]
        has_next = (start + pagination.first) < len(all_threads)

        threads: list[ThreadDict] = []
        for data in page:
            threads.append(ThreadDict(
                id=data["id"],
                createdAt=data.get("createdAt", ""),
                name=data.get("name"),
                userId=data.get("userId"),
                userIdentifier=data.get("userIdentifier"),
                tags=data.get("tags"),
                metadata=data.get("metadata"),
                steps=data.get("steps", []),
                elements=data.get("elements"),
            ))

        return PaginatedResponse(
            pageInfo=PageInfo(
                hasNextPage=has_next,
                startCursor=page[0]["id"] if page else None,
                endCursor=page[-1]["id"] if page else None,
            ),
            data=threads,
        )

    # -- Steps --------------------------------------------------------------

    async def create_step(self, step_dict: StepDict) -> None:
        thread_id = step_dict.get("threadId", "")
        if not thread_id:
            return
        data = self._load_thread(thread_id)
        if data is None:
            data = {
                "id": thread_id,
                "createdAt": _now_iso(),
                "steps": [],
                "elements": [],
            }
        data["steps"].append(dict(step_dict))
        self._save_thread(data)

    async def update_step(self, step_dict: StepDict) -> None:
        thread_id = step_dict.get("threadId", "")
        if not thread_id:
            return
        data = self._load_thread(thread_id)
        if data is None:
            return
        step_id = step_dict.get("id")
        for i, existing in enumerate(data.get("steps", [])):
            if existing.get("id") == step_id:
                data["steps"][i] = dict(step_dict)
                break
        else:
            data["steps"].append(dict(step_dict))
        self._save_thread(data)

    async def delete_step(self, step_id: str) -> None:
        for path in _THREADS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            original_len = len(data.get("steps", []))
            data["steps"] = [s for s in data.get("steps", []) if s.get("id") != step_id]
            if len(data["steps"]) < original_len:
                self._save_thread(data)
                return

    # -- Elements -----------------------------------------------------------

    async def create_element(self, element: Any) -> None:
        # Elements are stored with their thread
        thread_id = getattr(element, "thread_id", None) or getattr(element, "threadId", "")
        if not thread_id:
            return
        data = self._load_thread(thread_id)
        if data is None:
            return
        if "elements" not in data or data["elements"] is None:
            data["elements"] = []
        el_dict = {
            "id": getattr(element, "id", str(uuid.uuid4())),
            "type": getattr(element, "type", ""),
            "name": getattr(element, "name", ""),
            "threadId": thread_id,
        }
        data["elements"].append(el_dict)
        self._save_thread(data)

    async def get_element(
        self, thread_id: str, element_id: str
    ) -> Optional[dict]:
        data = self._load_thread(thread_id)
        if data is None:
            return None
        for el in data.get("elements", []) or []:
            if el.get("id") == element_id:
                return el
        return None

    async def delete_element(self, element_id: str, thread_id: Optional[str] = None) -> None:
        if thread_id:
            data = self._load_thread(thread_id)
            if data and data.get("elements"):
                data["elements"] = [e for e in data["elements"] if e.get("id") != element_id]
                self._save_thread(data)

    # -- Feedback -----------------------------------------------------------

    async def upsert_feedback(self, feedback: Feedback) -> str:
        feedback_id = feedback.id or str(uuid.uuid4())
        # Store feedback inline with the step if possible
        return feedback_id

    async def delete_feedback(self, feedback_id: str) -> bool:
        return True

    async def get_favorite_steps(self, user_id: str) -> List[StepDict]:
        return []

    # -- Misc ---------------------------------------------------------------

    async def build_debug_url(self) -> str:
        return ""

    async def close(self) -> None:
        pass

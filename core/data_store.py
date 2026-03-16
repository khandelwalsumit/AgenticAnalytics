"""DataStore: session-scoped file-backed cache for large data payloads.

Keeps raw DataFrames, report markdown, and bucket data OUT of
the conversational context / LangGraph state. State only holds
metadata references (e.g., bucket_id, row_count, top_issue).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_CACHE_DIR


class DataStore:
    """Session-scoped file-backed cache for large data payloads."""

    def __init__(self, session_id: str, DATA_CACHE_DIR: str | Path = DATA_CACHE_DIR):
        self.session_id = session_id
        self.base_dir = Path(DATA_CACHE_DIR) / session_id
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._registry: dict[str, dict] = {}
        self._load_registry()

    @property
    def _registry_path(self) -> Path:
        return self.base_dir / "_registry.json"

    def _load_registry(self) -> None:
        if self._registry_path.exists():
            self._registry = json.loads(
                self._registry_path.read_text(encoding="utf-8")
            )

    def _save_registry(self) -> None:
        self._registry_path.write_text(
            json.dumps(self._registry, indent=2, default=str), encoding="utf-8"
        )

    def store_dataframe(self, key: str, df: pd.DataFrame, metadata: dict | None = None) -> str:
        """Store DataFrame to parquet, return reference key."""
        path = self.base_dir / f"{key}.parquet"
        df.to_parquet(path, index=False)
        self._registry[key] = {
            "type": "dataframe",
            "path": str(path),
            "metadata": metadata or {},
        }
        self._save_registry()
        return key

    def get_dataframe(self, key: str) -> pd.DataFrame:
        """Retrieve DataFrame by key."""
        entry = self._registry.get(key)
        if not entry or entry["type"] != "dataframe":
            raise KeyError(f"DataFrame '{key}' not found in DataStore")
        return pd.read_parquet(entry["path"])

    def store_json(self, key: str, obj: Any, metadata: dict | None = None) -> str:
        """Store a JSON-serialisable object to ``{key}.json`` and register it.

        Returns the absolute file path (use as completion flag).
        """
        path = self.base_dir / f"{key}.json"
        path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
        self._registry[key] = {
            "type": "json",
            "path": str(path),
            "metadata": metadata or {},
        }
        self._save_registry()
        return str(path)

    def get_json(self, key: str) -> Any:
        """Retrieve a JSON object by key."""
        entry = self._registry.get(key)
        if not entry or entry["type"] != "json":
            raise KeyError(f"JSON '{key}' not found in DataStore")
        return json.loads(Path(entry["path"]).read_text(encoding="utf-8"))

    def store_md(self, key: str, content: str, metadata: dict | None = None) -> str:
        """Store markdown/text content to ``{key}.md`` and register it.

        Returns the registry key (use with get_md).
        """
        path = self.base_dir / f"{key}.md"
        path.write_text(content, encoding="utf-8")
        self._registry[key] = {
            "type": "md",
            "path": str(path),
            "metadata": metadata or {},
        }
        self._save_registry()
        return key

    def get_md(self, key: str) -> str:
        """Retrieve markdown/text content by key."""
        entry = self._registry.get(key)
        if not entry or entry["type"] != "md":
            raise KeyError(f"Markdown '{key}' not found in DataStore")
        return Path(entry["path"]).read_text(encoding="utf-8")

    def next_version(self, base_name: str) -> int:
        """Return the next version number for a versioned file.

        Scans base_dir for ``{base_name}_v*.*`` and returns max_existing + 1.
        Returns 1 if no versions exist yet.
        """
        existing = sorted(self.base_dir.glob(f"{base_name}_v*.*"))
        if not existing:
            return 1
        versions: list[int] = []
        for p in existing:
            stem = p.stem  # e.g. "synthesis_v2"
            try:
                versions.append(int(stem.split("_v")[-1]))
            except (ValueError, IndexError):
                pass
        return (max(versions) + 1) if versions else 1

    def store_versioned(
        self,
        base_name: str,
        content: str,
        metadata: dict,
        ext: str = "md",
        version: int | None = None,
    ) -> tuple[str, str]:
        """Write content to ``{base_name}_v{n}.{ext}`` and register it.

        Args:
            base_name: Logical name (e.g. ``"synthesis"``, ``"narrative"``).
            content:   Text content to write (pre-serialised JSON or markdown).
            metadata:  Arbitrary metadata dict stored in registry.
            ext:       File extension — ``"md"`` for markdown, ``"json"`` for JSON data.
            version:   Explicit version number. Auto-increments from existing files if None.

        Returns:
            ``(registry_key, absolute_path_str)`` — use the path as the completion flag.
        """
        v = version if version is not None else self.next_version(base_name)
        key = f"{base_name}_v{v}"
        path = self.base_dir / f"{key}.{ext}"
        path.write_text(content, encoding="utf-8")
        self._registry[key] = {
            "type": ext,
            "path": str(path),
            "version": v,
            "metadata": metadata,
        }
        self._save_registry()
        return key, str(path)

    def get_path(self, key: str) -> str:
        """Return the absolute file path for any registered key."""
        entry = self._registry.get(key)
        if not entry:
            raise KeyError(f"Key '{key}' not found in DataStore")
        return entry["path"]

    def get_metadata(self, key: str) -> dict:
        """Return metadata only (for state storage)."""
        entry = self._registry.get(key)
        if not entry:
            raise KeyError(f"Key '{key}' not found in DataStore")
        return entry["metadata"]

    def list_keys(self) -> list[str]:
        """List all stored keys for this session."""
        return list(self._registry.keys())

    def cleanup(self) -> None:
        """Remove all cached files for this session."""
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir)
        self._registry.clear()

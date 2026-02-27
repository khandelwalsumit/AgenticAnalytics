"""DataStore: session-scoped file-backed cache for large data payloads.

Keeps raw DataFrames, report markdown, and bucket data OUT of
the conversational context / LangGraph state. State only holds
metadata references (e.g., bucket_id, row_count, top_issue).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

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

    def store_dataframe(self, key: str, df: pd.DataFrame, metadata: dict) -> str:
        """Store DataFrame to parquet, return reference key."""
        path = self.base_dir / f"{key}.parquet"
        df.to_parquet(path, index=False)
        self._registry[key] = {
            "type": "dataframe",
            "path": str(path),
            "metadata": metadata,
        }
        self._save_registry()
        return key

    def get_dataframe(self, key: str) -> pd.DataFrame:
        """Retrieve DataFrame by key."""
        entry = self._registry.get(key)
        if not entry or entry["type"] != "dataframe":
            raise KeyError(f"DataFrame '{key}' not found in DataStore")
        return pd.read_parquet(entry["path"])

    def store_text(self, key: str, content: str, metadata: dict) -> str:
        """Store large text to file (.txt extension, legacy)."""
        path = self.base_dir / f"{key}.txt"
        path.write_text(content, encoding="utf-8")
        self._registry[key] = {
            "type": "text",
            "path": str(path),
            "metadata": metadata,
        }
        self._save_registry()
        return key

    def get_text(self, key: str) -> str:
        """Retrieve text content by key."""
        entry = self._registry.get(key)
        if not entry or entry["type"] not in ("text", "markdown"):
            raise KeyError(f"Text '{key}' not found in DataStore")
        return Path(entry["path"]).read_text(encoding="utf-8")

    def next_version(self, base_name: str) -> int:
        """Return the next version number for a versioned markdown file.

        Scans base_dir for ``{base_name}_v*.md`` and returns max_existing + 1.
        Returns 1 if no versions exist yet.
        """
        existing = sorted(self.base_dir.glob(f"{base_name}_v*.md"))
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

    def store_versioned_md(
        self,
        base_name: str,
        content: str,
        metadata: dict,
        version: int | None = None,
    ) -> tuple[str, str]:
        """Write content to ``{base_name}_v{n}.md`` and register it.

        Args:
            base_name: Logical name (e.g. ``"synthesis"``, ``"digital_friction_agent"``).
            content:   Markdown text to write.
            metadata:  Arbitrary metadata dict stored in registry.
            version:   Explicit version number. Auto-increments from existing files if None.

        Returns:
            ``(registry_key, absolute_path_str)`` — use the path as the completion flag.
        """
        v = version if version is not None else self.next_version(base_name)
        key = f"{base_name}_v{v}"
        path = self.base_dir / f"{key}.md"
        path.write_text(content, encoding="utf-8")
        self._registry[key] = {
            "type": "markdown",
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

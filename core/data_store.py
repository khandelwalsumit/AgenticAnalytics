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

from config.settings import CACHE_DIR


class DataStore:
    """Session-scoped file-backed cache for large data payloads."""

    def __init__(self, session_id: str, cache_dir: str | Path = CACHE_DIR):
        self.session_id = session_id
        self.base_dir = Path(cache_dir) / session_id
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
        """Store large text (report markdown, etc.) to file."""
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
        if not entry or entry["type"] != "text":
            raise KeyError(f"Text '{key}' not found in DataStore")
        return Path(entry["path"]).read_text(encoding="utf-8")

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

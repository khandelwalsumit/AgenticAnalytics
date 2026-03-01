"""Data tools for the Data Analyst agent.

Pipeline:
  load_dataset  → reads input parquet in-place (no copy)
  filter_data   → writes data/.cache/<thread_id>/filtered.parquet
  bucket_data   → writes data/.cache/<thread_id>/bucket_*.parquet
  analyze_bucket → reads bucket parquets for LLM analysis

File paths returned in every tool response double as completion flags:
if the path exists on disk, that step is done.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.tools import tool

from config import (
    CALL_REASONS_TO_SKILLS,
    DATA_FILTER_COLUMNS,
    GROUP_BY_COLUMNS,
    LLM_ANALYSIS_FOCUS,
    MAX_BUCKET_SIZE,
    MAX_SAMPLE_SIZE,
    MIN_BUCKET_SIZE,
    TAIL_BUCKET_ENABLED,
    DEFAULT_PARQUET_PATH,
)
from core.data_store import DataStore
from tools.metrics import MetricsEngine

# Module-level references — set by the graph at session init
_data_store: DataStore | None = None
# Path to the input parquet file — set by load_dataset; never written, only read.
_input_parquet_path: Path | None = None


def set_data_store(store: DataStore) -> None:
    """Bind the session DataStore for tool access."""
    global _data_store, _input_parquet_path
    _data_store = store
    _input_parquet_path = None  # reset on new session



def _get_store() -> DataStore:
    if _data_store is None:
        raise RuntimeError("DataStore not initialized. Call set_data_store() first.")
    return _data_store


def _safe_key(name: str) -> str:
    """Convert a bucket name to a safe DataStore key."""
    return re.sub(r"[^a-z0-9_]", "_", str(name).lower().strip())[:80]


@tool
def load_dataset(path: str = "") -> str:
    """Read the input parquet file and return schema + basic stats.

    The file is read in-place — no copy is created in the cache.
    The path is registered so filter_data can read the raw data.

    Args:
        path: Optional path to the input .parquet file. If empty,
              DEFAULT_PARQUET_PATH is used.

    Returns:
        JSON string with schema info, row count, column types, sample values,
        and the registered parquet path.
    """

    df = pd.read_parquet(DEFAULT_PARQUET_PATH)

    stats = MetricsEngine.summary_stats(df)
    samples: dict[str, list[str]] = {}
    for col in df.columns:
        non_null = df[col].dropna()
        samples[col] = [str(v) for v in non_null.head(3).tolist()] if len(non_null) > 0 else []
    stats["sample_values"] = samples
    stats["data_filter_columns"] = [c for c in DATA_FILTER_COLUMNS if c in df.columns]
    stats["llm_analysis_focus"] = [c for c in LLM_ANALYSIS_FOCUS if c in df.columns]
    stats["group_by_columns"] = [c for c in GROUP_BY_COLUMNS if c in df.columns]
    stats["input_parquet_path"] = str(DEFAULT_PARQUET_PATH)

    return json.dumps(stats, indent=2)


@tool
def filter_data(filters: dict[str, Any]) -> str:
    """Apply column-value filters to the input dataset and cache the result.

    Reads the input parquet registered by load_dataset (no copy of the source).
    Writes the filtered result to data/.cache/<thread_id>/filtered.parquet.

    Args:
        filters: Dictionary of {column_name: value_or_list} to filter on.
                 Use a list for multiple values (OR logic within column).

    Returns:
        JSON string with filtered row count, filter summary, and filtered_parquet_path.
    """
    store = _get_store()
    df = pd.read_parquet(DEFAULT_PARQUET_PATH)

    mask = pd.Series(True, index=df.index)
    applied = {}
    skipped = {}

    for col, val in filters.items():
        if col not in df.columns:
            # Find close matches to suggest
            from difflib import get_close_matches
            close = get_close_matches(col, list(df.columns), n=3, cutoff=0.4)
            skipped[col] = {
                "reason": f"Column '{col}' not found in dataset",
                "suggestions": close,
                "available_columns": sorted(df.columns.tolist()),
            }
            continue
        if isinstance(val, list):
            # Check which values actually exist in the column
            existing = set(df[col].dropna().unique().astype(str))
            missing_vals = [v for v in val if str(v) not in existing]
            mask &= df[col].isin(val)
            applied[col] = val
            if missing_vals:
                skipped[f"{col}_values"] = {
                    "reason": f"Some values not found in column '{col}'",
                    "missing": missing_vals,
                    "available": sorted(list(existing))[:30],
                }
        else:
            mask &= df[col] == val
            applied[col] = val

    filtered = df[mask]

    metadata: dict[str, Any] = {
        "original_rows": len(df),
        "filtered_rows": len(filtered),
        "filters_applied": applied,
        "reduction_pct": round((1 - len(filtered) / max(len(df), 1)) * 100, 2),
    }

    if skipped:
        metadata["skipped_filters"] = skipped

    if not applied:
        metadata["warning"] = (
            "No filters were applied. All requested columns were not found. "
            "Check the 'skipped_filters' field for suggestions."
        )

    store.store_dataframe("filter_data", filtered, metadata=metadata)

    return json.dumps(metadata, indent=2)


@tool
def bucket_data(group_by: str = "", focus: str = "") -> str:
    """Intelligently group data into analysis buckets.

    Uses the GROUP_BY_COLUMNS hierarchy from config. Groups by each column
    in sequence, enforcing MIN_BUCKET_SIZE and MAX_BUCKET_SIZE. Small
    buckets are merged into an "Other" tail bucket when TAIL_BUCKET_ENABLED.

    Buckets larger than MAX_BUCKET_SIZE are automatically sub-bucketed by
    the next column in the hierarchy.

    Args:
        group_by: Column name to group by. If empty, uses the first
                  available column from GROUP_BY_COLUMNS config.
        focus: Optional column to compute top-N values within each bucket.

    Returns:
        JSON string with bucket names, sizes, config used, and top values.
    """
    store = _get_store()

    if "filter_data" not in store.list_keys():
        return json.dumps({
            "error": "No filtered data available. You MUST call filter_data before bucket_data.",
            "hint": "Call filter_data with appropriate filters first, then retry bucket_data.",
        })

    df = store.get_dataframe("filter_data")

    # Determine which column to group by
    if not group_by:
        available = [c for c in GROUP_BY_COLUMNS if c in df.columns]
        if not available:
            return json.dumps({
                "error": "No GROUP_BY_COLUMNS found in dataset",
                "configured": GROUP_BY_COLUMNS,
                "available": list(df.columns),
            })
        group_by = available[0]

    if group_by not in df.columns:
        return json.dumps({
            "error": f"Column '{group_by}' not found",
            "available": list(df.columns),
        })

    # Determine the next column in hierarchy for sub-bucketing oversized groups
    available_cols = [c for c in GROUP_BY_COLUMNS if c in df.columns]
    current_idx = available_cols.index(group_by) if group_by in available_cols else -1
    next_col = available_cols[current_idx + 1] if current_idx + 1 < len(available_cols) else None

    # --- Group and apply min/max logic ---
    grouped = df.groupby(group_by, dropna=False)
    regular_buckets: dict[str, pd.DataFrame] = {}
    tail_rows: list[pd.DataFrame] = []

    for name, group_df in grouped:
        bucket_name = str(name) if pd.notna(name) else "Unknown"
        count = len(group_df)

        if TAIL_BUCKET_ENABLED and count < MIN_BUCKET_SIZE:
            # Collect into tail
            tail_rows.append(group_df)
        elif count > MAX_BUCKET_SIZE and next_col:
            # Sub-bucket by next column in hierarchy
            sub_grouped = group_df.groupby(next_col, dropna=False)
            sub_tail: list[pd.DataFrame] = []
            for sub_name, sub_df in sub_grouped:
                sub_bucket_name = f"{bucket_name} > {sub_name}" if pd.notna(sub_name) else f"{bucket_name} > Unknown"
                if TAIL_BUCKET_ENABLED and len(sub_df) < MIN_BUCKET_SIZE:
                    sub_tail.append(sub_df)
                else:
                    regular_buckets[sub_bucket_name] = sub_df

            # Merge sub-tails into parent-level tail
            if sub_tail:
                merged_sub_tail = pd.concat(sub_tail, ignore_index=True)
                if len(merged_sub_tail) >= MIN_BUCKET_SIZE:
                    regular_buckets[f"{bucket_name} > Other"] = merged_sub_tail
                else:
                    tail_rows.append(merged_sub_tail)
        else:
            regular_buckets[bucket_name] = group_df

    # Merge all tail rows into "Other" bucket
    if tail_rows:
        other_df = pd.concat(tail_rows, ignore_index=True)
        regular_buckets["Other"] = other_df

    # --- Build per-bucket metadata and combine into one parquet ---
    buckets_info: dict[str, Any] = {}
    frames: list[pd.DataFrame] = []
    for bucket_name, bucket_df in regular_buckets.items():
        bucket_key = f"bucket_{_safe_key(bucket_name)}"

        # Build LLM-relevant summary (only LLM_ANALYSIS_FOCUS)
        llm_cols = [c for c in LLM_ANALYSIS_FOCUS if c in bucket_df.columns]
        llm_summary: dict[str, Any] = {}
        for col in llm_cols:
            top = MetricsEngine.top_n(bucket_df, col, n=5)
            llm_summary[col] = top

        # Resolve skills for this bucket from the CALL_REASONS_TO_SKILLS mapping.
        # For sub-buckets ("Parent > Sub"), use only the parent part for lookup.
        parent_reason = bucket_name.split(" > ")[0].strip()
        assigned_skills: list[str] = (
            CALL_REASONS_TO_SKILLS.get(parent_reason)
            or CALL_REASONS_TO_SKILLS.get(bucket_name)
            or []
        )

        meta: dict[str, Any] = {
            "bucket_name": bucket_name,
            "row_count": len(bucket_df),
            "group_by": group_by,
            "llm_field_summary": llm_summary,
            "assigned_skills": assigned_skills,
        }

        if len(bucket_df) < MIN_BUCKET_SIZE:
            meta["warning"] = f"Small bucket ({len(bucket_df)} rows)"

        if focus and focus in bucket_df.columns:
            meta["top_values"] = MetricsEngine.top_n(bucket_df, focus, n=5)

        tagged = bucket_df.copy()
        tagged["_bucket_key"] = bucket_key
        frames.append(tagged)
        buckets_info[bucket_key] = meta

    # Store all buckets in one combined parquet
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    store.store_dataframe("bucketed_data", combined, metadata={"buckets": buckets_info})

    return json.dumps(
        {
            "group_by": group_by,
            "bucket_count": len(buckets_info),
            "total_rows": len(df),
            "config": {
                "min_bucket_size": MIN_BUCKET_SIZE,
                "max_bucket_size": MAX_BUCKET_SIZE,
                "tail_enabled": TAIL_BUCKET_ENABLED,
                "group_by_columns": GROUP_BY_COLUMNS,
                "llm_analysis_focus": LLM_ANALYSIS_FOCUS,
            },
            "buckets": buckets_info,
        },
        indent=2,
    )


@tool
def sample_data(bucket: str, n: int = 5) -> str:
    """Get a sample of rows from a data bucket — only LLM-relevant columns.

    Returns only the LLM_ANALYSIS_COLUMNS plus grouping columns to keep
    context small for downstream LLM agents.

    Args:
        bucket: DataStore key for the bucket (e.g., 'bucket_payments').
        n: Number of rows to sample (max 50).

    Returns:
        JSON string with sampled rows (LLM columns only).
    """
    store = _get_store()
    n = min(n, MAX_SAMPLE_SIZE)

    df_all = store.get_dataframe("bucketed_data")
    df = df_all[df_all["_bucket_key"] == bucket] if bucket else df_all

    # Only include LLM_ANALYSIS_FOCUS columns + grouping columns for context
    relevant_cols = list(dict.fromkeys(
        LLM_ANALYSIS_FOCUS + GROUP_BY_COLUMNS
    ))
    available_cols = [c for c in relevant_cols if c in df.columns]
    df_slim = df[available_cols] if available_cols else df.drop(columns=["_bucket_key"], errors="ignore")

    sample = df_slim.sample(n=min(n, len(df_slim)), random_state=42)

    rows = []
    for _, row in sample.iterrows():
        row_dict = {}
        for col, val in row.items():
            s = str(val)
            row_dict[col] = s[:200] + "..." if len(s) > 200 else s
        rows.append(row_dict)

    return json.dumps({
        "bucket": bucket,
        "sampled_rows": len(rows),
        "columns_included": available_cols,
        "rows": rows,
    }, indent=2)


@tool
def get_distribution(column: str, bucket: str = "") -> str:
    """Get value distribution for a column.

    Args:
        column: Column name to analyze.
        bucket: Optional DataStore key. If empty, uses filtered/main dataset.

    Returns:
        JSON string with value counts and percentages.
    """
    store = _get_store()

    if bucket:
        df_all = store.get_dataframe("bucketed_data")
        df = df_all[df_all["_bucket_key"] == bucket]
    else:
        df = store.get_dataframe("filter_data")

    result = MetricsEngine.get_distribution(df, column)
    return json.dumps(result, indent=2)


# Registry of all data tools
DATA_TOOLS = [load_dataset, filter_data, bucket_data, sample_data, get_distribution]

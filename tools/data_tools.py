"""Data tools for the Data Analyst agent.

Pipeline:
  load_dataset  → reads input parquet in-place (no copy)
  filter_data   → writes data/.cache/<thread_id>/filtered.parquet
  bucket_data   → writes data/.cache/<thread_id>/buckets/*.parquet
                  + data/.cache/<thread_id>/bucket_manifest.json
  analyze_bucket → reads bucket parquets from manifest
  sample_data   → returns sample rows for LLM context
  get_distribution → returns value counts for a column

File paths returned in every tool response double as completion flags:
if the path exists on disk, that step is done.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.tools import tool

from config import (
    BUCKETING_MODE,
    CALL_REASONS_TO_SKILLS,
    DATA_FILTER_COLUMNS,
    GROUP_BY_COLUMNS,
    LLM_ANALYSIS_FOCUS,
    MAX_BUCKET_SIZE,
    MAX_SAMPLE_SIZE,
    MIN_BUCKET_SIZE,
    SPECIALIST_DOMAIN_TRIGGERS,
    SPECIALIST_MIN_BUCKET_SIZE,
    TAIL_BUCKET_ENABLED,
    DEFAULT_PARQUET_PATH,
)
from core.data_store import DataStore
from tools.metrics import MetricsEngine

# Module-level references — set by the graph at session init
_data_store: DataStore | None = None
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
    """Convert a bucket name to a safe DataStore key / file stem."""
    return re.sub(r"[^a-z0-9_]", "_", str(name).lower().strip())[:80]


def _bucket_id_from_name(name: str, existing_ids: list[str] | None = None) -> str:
    """Generate a short uppercase bucket ID from a name, e.g. 'PAY-POST-001'.

    Ensures uniqueness vs existing_ids by appending a counter if needed.
    """
    parts = re.split(r"[^a-zA-Z0-9]+", name.strip())
    parts = [p[:4].upper() for p in parts if p][:3]
    base = "-".join(parts) if parts else _safe_key(name).upper()[:12]
    if not existing_ids or base not in existing_ids:
        return base
    counter = 1
    while f"{base}-{counter:03d}" in existing_ids:
        counter += 1
    return f"{base}-{counter:03d}"


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
            from difflib import get_close_matches
            close = get_close_matches(col, list(df.columns), n=3, cutoff=0.4)
            skipped[col] = {
                "reason": f"Column '{col}' not found in dataset",
                "suggestions": close,
                "available_columns": sorted(df.columns.tolist()),
            }
            continue
        if isinstance(val, list):
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

    # Write filtered parquet to a stable named path so bucket_data can read it
    filtered_path = store.base_dir / "filtered.parquet"
    filtered.to_parquet(filtered_path, index=False)
    metadata["filtered_parquet_path"] = str(filtered_path)

    return json.dumps(metadata, indent=2)


@tool
def bucket_data(group_by: str = "", focus: str = "") -> str:
    """Intelligently group data into analysis buckets using tree partitioning.

    Uses the GROUP_BY_COLUMNS hierarchy from config. Groups by each column
    in sequence, enforcing MIN_BUCKET_SIZE and MAX_BUCKET_SIZE. Small
    buckets are merged into a tail bucket when TAIL_BUCKET_ENABLED.

    Writes individual bucket parquets to data/.cache/<thread_id>/buckets/ and
    a bucket_manifest.json that replaces all legacy data_buckets state.
    Assigns skills and specialist_skill from config mappings.

    Args:
        group_by: Column name to group by. If empty, uses the first
                  available column from GROUP_BY_COLUMNS config.
        focus: Optional column to compute top-N values within each bucket.

    Returns:
        JSON string with bucket_manifest_path, bucket_count, and bucket summary.
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

    # Determine hierarchy columns available for recursive sub-bucketing
    available_cols = [c for c in GROUP_BY_COLUMNS if c in df.columns]
    current_idx = available_cols.index(group_by) if group_by in available_cols else -1

    # --- Tree partitioning algorithm (greedy top-down) ---
    grouped = df.groupby(group_by, dropna=False)
    regular_buckets: dict[str, pd.DataFrame] = {}
    tail_rows: list[pd.DataFrame] = []

    def _sub_bucket(
        parent_name: str,
        parent_df: pd.DataFrame,
        remaining_cols: list[str],
    ) -> None:
        """Recursively split oversized buckets by the next column in hierarchy."""
        count = len(parent_df)

        if TAIL_BUCKET_ENABLED and count < MIN_BUCKET_SIZE:
            tail_rows.append(parent_df)
            return

        if count > MAX_BUCKET_SIZE and remaining_cols:
            split_col = remaining_cols[0]
            deeper_cols = remaining_cols[1:]
            sub_grouped = parent_df.groupby(split_col, dropna=False)
            sub_tail: list[pd.DataFrame] = []

            for sub_name, sub_df in sub_grouped:
                sub_bucket_name = (
                    f"{parent_name} > {sub_name}" if pd.notna(sub_name)
                    else f"{parent_name} > Unknown"
                )
                if TAIL_BUCKET_ENABLED and len(sub_df) < MIN_BUCKET_SIZE:
                    sub_tail.append(sub_df)
                elif len(sub_df) > MAX_BUCKET_SIZE and deeper_cols:
                    _sub_bucket(sub_bucket_name, sub_df, deeper_cols)
                else:
                    regular_buckets[sub_bucket_name] = sub_df

            if sub_tail:
                merged_sub_tail = pd.concat(sub_tail, ignore_index=True)
                if len(merged_sub_tail) >= MIN_BUCKET_SIZE:
                    regular_buckets[f"{parent_name} > Other"] = merged_sub_tail
                else:
                    tail_rows.append(merged_sub_tail)
        else:
            regular_buckets[parent_name] = parent_df

    deeper_cols = available_cols[current_idx + 1:] if current_idx >= 0 else []

    for name, group_df in grouped:
        bucket_name = str(name) if pd.notna(name) else "Unknown"
        _sub_bucket(bucket_name, group_df, deeper_cols)

    # Merge all tail rows into "Other" bucket
    if tail_rows:
        other_df = pd.concat(tail_rows, ignore_index=True)
        regular_buckets["Other"] = other_df

    # --- Write individual bucket parquets + build manifest ---
    buckets_dir = store.base_dir / "buckets"
    buckets_dir.mkdir(parents=True, exist_ok=True)

    manifest_buckets: list[dict[str, Any]] = []
    existing_ids: list[str] = []
    total_rows = len(df)

    for bucket_name, bucket_df in regular_buckets.items():
        # Determine primary_domain and sub_theme from the bucket name
        parts_split = bucket_name.split(" > ")
        primary_domain = parts_split[0].strip()
        sub_theme = parts_split[1].strip() if len(parts_split) > 1 else primary_domain
        is_tail = bucket_name == "Other"

        # Generate stable bucket_id (unique)
        bucket_id = _bucket_id_from_name(bucket_name, existing_ids)
        existing_ids.append(bucket_id)

        # Write individual parquet
        bucket_parquet_path = buckets_dir / f"{bucket_id}.parquet"
        bucket_df.to_parquet(bucket_parquet_path, index=False)

        # Resolve skills from CALL_REASONS_TO_SKILLS
        assigned_skills: list[str] = (
            CALL_REASONS_TO_SKILLS.get(primary_domain)
            or CALL_REASONS_TO_SKILLS.get(bucket_name)
            or ["general_inquiry"]
        )

        # Resolve specialist skill
        specialist_skill: str | None = None
        if (
            primary_domain in SPECIALIST_DOMAIN_TRIGGERS
            and len(bucket_df) >= SPECIALIST_MIN_BUCKET_SIZE
        ):
            specialist_skill = SPECIALIST_DOMAIN_TRIGGERS[primary_domain]

        # LLM-relevant summary
        llm_cols = [c for c in LLM_ANALYSIS_FOCUS if c in bucket_df.columns]
        llm_summary: dict[str, Any] = {}
        for col in llm_cols:
            top = MetricsEngine.top_n(bucket_df, col, n=5)
            llm_summary[col] = top

        if focus and focus in bucket_df.columns:
            llm_summary[f"top_{focus}"] = MetricsEngine.top_n(bucket_df, focus, n=5)

        manifest_buckets.append({
            "bucket_id": bucket_id,
            "bucket_name": bucket_name,
            "primary_domain": primary_domain,
            "sub_theme": sub_theme,
            "row_count": len(bucket_df),
            "bucket_path": str(bucket_parquet_path),
            "skills": assigned_skills,
            "specialist_skill": specialist_skill,
            "is_tail": is_tail,
            "llm_field_summary": llm_summary,
        })

    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_calls": total_rows,
        "filtered_calls": total_rows,
        "bucketing_mode": BUCKETING_MODE,
        "group_by": group_by,
        "bucket_count": len(manifest_buckets),
        "config": {
            "min_bucket_size": MIN_BUCKET_SIZE,
            "max_bucket_size": MAX_BUCKET_SIZE,
            "tail_enabled": TAIL_BUCKET_ENABLED,
            "group_by_columns": GROUP_BY_COLUMNS,
        },
        "buckets": manifest_buckets,
    }

    # Write manifest JSON and register in DataStore
    manifest_path = store.store_json("bucket_manifest", manifest)

    # Also store the combined bucketed dataframe for analyze_bucket / sample_data tools
    frames = []
    for bucket_entry in manifest_buckets:
        bdf = pd.read_parquet(bucket_entry["bucket_path"])
        bdf = bdf.copy()
        bdf["_bucket_id"] = bucket_entry["bucket_id"]
        bdf["_bucket_key"] = _safe_key(bucket_entry["bucket_name"])
        frames.append(bdf)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    store.store_dataframe("bucketed_data", combined, metadata={"manifest_path": manifest_path})

    # Build compact bucket summary for LLM context (no parquet paths)
    bucket_summary = {
        b["bucket_id"]: {
            "bucket_name": b["bucket_name"],
            "primary_domain": b["primary_domain"],
            "sub_theme": b["sub_theme"],
            "row_count": b["row_count"],
            "skills": b["skills"],
            "specialist_skill": b["specialist_skill"],
            "is_tail": b["is_tail"],
        }
        for b in manifest_buckets
    }

    return json.dumps(
        {
            "bucket_manifest_path": manifest_path,
            "bucket_count": len(manifest_buckets),
            "total_rows": total_rows,
            "buckets": bucket_summary,
        },
        indent=2,
    )


@tool
def sample_data(bucket: str, n: int = 5) -> str:
    """Get a sample of rows from a data bucket — only LLM-relevant columns.

    Args:
        bucket: Bucket ID (e.g., 'PAY-POST-001') or legacy bucket key.
        n: Number of rows to sample (max 50).

    Returns:
        JSON string with sampled rows (LLM columns only).
    """
    store = _get_store()
    n = min(n, MAX_SAMPLE_SIZE)

    df_all = store.get_dataframe("bucketed_data")
    # Support both bucket_id and legacy bucket_key
    if "_bucket_id" in df_all.columns:
        df = df_all[df_all["_bucket_id"] == bucket]
        if df.empty and "_bucket_key" in df_all.columns:
            df = df_all[df_all["_bucket_key"] == bucket]
    elif "_bucket_key" in df_all.columns:
        df = df_all[df_all["_bucket_key"] == bucket]
    else:
        df = df_all

    relevant_cols = list(dict.fromkeys(LLM_ANALYSIS_FOCUS + GROUP_BY_COLUMNS))
    available_cols = [c for c in relevant_cols if c in df.columns]
    df_slim = df[available_cols] if available_cols else df.drop(
        columns=[c for c in ["_bucket_key", "_bucket_id"] if c in df.columns], errors="ignore"
    )

    sample = df_slim.sample(n=min(n, len(df_slim)), random_state=42) if len(df_slim) > 0 else df_slim

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
        bucket: Optional bucket ID or key. If empty, uses filtered/main dataset.

    Returns:
        JSON string with value counts and percentages.
    """
    store = _get_store()

    if bucket:
        df_all = store.get_dataframe("bucketed_data")
        if "_bucket_id" in df_all.columns:
            df = df_all[df_all["_bucket_id"] == bucket]
            if df.empty and "_bucket_key" in df_all.columns:
                df = df_all[df_all["_bucket_key"] == bucket]
        elif "_bucket_key" in df_all.columns:
            df = df_all[df_all["_bucket_key"] == bucket]
        else:
            df = df_all
    else:
        df = store.get_dataframe("filter_data")

    result = MetricsEngine.get_distribution(df, column)
    return json.dumps(result, indent=2)


# Registry of all data tools
DATA_TOOLS = [load_dataset, filter_data, bucket_data, sample_data, get_distribution]

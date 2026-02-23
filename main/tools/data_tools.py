"""Data tools for the Data Analyst agent.

Each tool is a LangChain tool function that operates on DataFrames
stored in the session DataStore.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from langchain_core.tools import tool

from config import MAX_SAMPLE_SIZE, MIN_BUCKET_SIZE
from core.data_store import DataStore
from tools.metrics import MetricsEngine

# Module-level DataStore reference — set by the graph at session init
_data_store: DataStore | None = None


def set_data_store(store: DataStore) -> None:
    """Bind the session DataStore for tool access."""
    global _data_store
    _data_store = store


def _get_store() -> DataStore:
    if _data_store is None:
        raise RuntimeError("DataStore not initialized. Call set_data_store() first.")
    return _data_store


@tool
def load_dataset(path: str) -> str:
    """Load a CSV dataset, store it, and return schema + basic stats.

    Args:
        path: Path to the CSV file to load.

    Returns:
        JSON string with schema info, row count, column types, and sample values.
    """
    store = _get_store()
    df = pd.read_csv(path)

    stats = MetricsEngine.summary_stats(df)
    # Add sample values for each column
    samples = {}
    for col in df.columns:
        non_null = df[col].dropna()
        if len(non_null) > 0:
            samples[col] = [str(v) for v in non_null.head(3).tolist()]
        else:
            samples[col] = []
    stats["sample_values"] = samples

    store.store_dataframe("main_dataset", df, metadata=stats)
    return json.dumps(stats, indent=2)


@tool
def filter_data(filters: dict[str, Any]) -> str:
    """Apply column-value filters to the dataset and store the filtered result.

    Args:
        filters: Dictionary of {column_name: value_or_list} to filter on.
                 Use a list for multiple values (OR logic within column).

    Returns:
        JSON string with filtered row count and filter summary.
    """
    store = _get_store()
    df = store.get_dataframe("main_dataset")

    mask = pd.Series(True, index=df.index)
    applied = {}

    for col, val in filters.items():
        if col not in df.columns:
            continue
        if isinstance(val, list):
            mask &= df[col].isin(val)
            applied[col] = val
        else:
            mask &= df[col] == val
            applied[col] = val

    filtered = df[mask]
    metadata = {
        "original_rows": len(df),
        "filtered_rows": len(filtered),
        "filters_applied": applied,
        "reduction_pct": round((1 - len(filtered) / max(len(df), 1)) * 100, 2),
    }

    store.store_dataframe("filtered_dataset", filtered, metadata=metadata)
    return json.dumps(metadata, indent=2)


@tool
def bucket_data(group_by: str, focus: str = "") -> str:
    """Group data into named buckets based on a column.

    Args:
        group_by: Column name to group by.
        focus: Optional column to analyze within each bucket.

    Returns:
        JSON string with bucket names, sizes, and top values.
    """
    store = _get_store()

    # Use filtered dataset if available, else main
    try:
        df = store.get_dataframe("filtered_dataset")
    except KeyError:
        df = store.get_dataframe("main_dataset")

    if group_by not in df.columns:
        return json.dumps({"error": f"Column '{group_by}' not found", "available": list(df.columns)})

    buckets_info = {}
    for name, group_df in df.groupby(group_by, dropna=False):
        bucket_key = f"bucket_{str(name).replace(' ', '_').lower()}"
        bucket_name = str(name)

        meta: dict[str, Any] = {
            "bucket_name": bucket_name,
            "row_count": len(group_df),
            "columns": list(group_df.columns),
        }

        if len(group_df) < MIN_BUCKET_SIZE:
            meta["warning"] = f"Small bucket ({len(group_df)} rows < {MIN_BUCKET_SIZE} minimum)"

        if focus and focus in group_df.columns:
            top = MetricsEngine.top_n(group_df, focus, n=5)
            meta["top_values"] = top

        store.store_dataframe(bucket_key, group_df, metadata=meta)
        buckets_info[bucket_key] = meta

    return json.dumps(
        {"group_by": group_by, "bucket_count": len(buckets_info), "buckets": buckets_info},
        indent=2,
    )


@tool
def sample_data(bucket: str, n: int = 5) -> str:
    """Get a random sample of rows from a data bucket.

    Args:
        bucket: DataStore key for the bucket (e.g., 'bucket_payments').
        n: Number of rows to sample (max 50).

    Returns:
        JSON string with sampled rows.
    """
    store = _get_store()
    n = min(n, MAX_SAMPLE_SIZE)

    df = store.get_dataframe(bucket)
    sample = df.sample(n=min(n, len(df)), random_state=42)

    # Convert to list of dicts, truncating long values
    rows = []
    for _, row in sample.iterrows():
        row_dict = {}
        for col, val in row.items():
            s = str(val)
            row_dict[col] = s[:200] + "..." if len(s) > 200 else s
        rows.append(row_dict)

    return json.dumps({"bucket": bucket, "sampled_rows": len(rows), "rows": rows}, indent=2)


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
        df = store.get_dataframe(bucket)
    else:
        try:
            df = store.get_dataframe("filtered_dataset")
        except KeyError:
            df = store.get_dataframe("main_dataset")

    result = MetricsEngine.get_distribution(df, column)
    return json.dumps(result, indent=2)


# Registry of all data tools
DATA_TOOLS = [load_dataset, filter_data, bucket_data, sample_data, get_distribution]

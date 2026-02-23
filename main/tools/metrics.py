"""MetricsEngine: deterministic Python computations.

All quantitative operations (distributions, rankings, comparisons,
impact scores) are computed here. LLM interprets results, never computes.
"""

from __future__ import annotations

import pandas as pd

from config import TOP_N_DEFAULT


class MetricsEngine:
    """Deterministic Python computations — keeps math out of LLM."""

    @staticmethod
    def get_distribution(df: pd.DataFrame, column: str) -> dict:
        """Value counts with percentages."""
        if column not in df.columns:
            return {"error": f"Column '{column}' not found", "available": list(df.columns)}

        counts = df[column].value_counts(dropna=False)
        total = len(df)
        return {
            "column": column,
            "total_rows": total,
            "unique_values": int(counts.nunique()),
            "distribution": [
                {
                    "value": str(val),
                    "count": int(cnt),
                    "percentage": round(cnt / total * 100, 2),
                }
                for val, cnt in counts.items()
            ],
        }

    @staticmethod
    def compute_impact_score(volume_pct: float, friction_severity: float) -> float:
        """impact = volume × friction_severity (both normalized 0-1)."""
        return round(
            min(volume_pct / 100, 1.0) * max(0.0, min(friction_severity, 1.0)), 4
        )

    @staticmethod
    def compute_ease_score(complexity: float) -> float:
        """ease = 1 - complexity (normalized 0-1)."""
        return round(1.0 - max(0.0, min(complexity, 1.0)), 4)

    @staticmethod
    def rank_findings(
        findings: list[dict], sort_by: str = "impact_score"
    ) -> list[dict]:
        """Sort findings by score, add rank field."""
        sorted_findings = sorted(
            findings, key=lambda f: f.get(sort_by, 0), reverse=True
        )
        for i, f in enumerate(sorted_findings, 1):
            f["rank"] = i
        return sorted_findings

    @staticmethod
    def compare_buckets(
        df_a: pd.DataFrame, df_b: pd.DataFrame, column: str
    ) -> dict:
        """Cross-bucket comparison ratios."""
        if column not in df_a.columns or column not in df_b.columns:
            return {"error": f"Column '{column}' missing from one or both buckets"}

        dist_a = df_a[column].value_counts(normalize=True)
        dist_b = df_b[column].value_counts(normalize=True)
        all_values = sorted(set(dist_a.index) | set(dist_b.index), key=str)

        comparisons = []
        for val in all_values:
            pct_a = round(dist_a.get(val, 0) * 100, 2)
            pct_b = round(dist_b.get(val, 0) * 100, 2)
            diff = round(pct_a - pct_b, 2)
            comparisons.append(
                {"value": str(val), "bucket_a_pct": pct_a, "bucket_b_pct": pct_b, "difference": diff}
            )

        return {
            "column": column,
            "bucket_a_rows": len(df_a),
            "bucket_b_rows": len(df_b),
            "comparisons": comparisons,
        }

    @staticmethod
    def top_n(df: pd.DataFrame, column: str, n: int = TOP_N_DEFAULT) -> list[dict]:
        """Top N values by frequency."""
        if column not in df.columns:
            return [{"error": f"Column '{column}' not found"}]

        counts = df[column].value_counts(dropna=False).head(n)
        total = len(df)
        return [
            {
                "rank": i,
                "value": str(val),
                "count": int(cnt),
                "percentage": round(cnt / total * 100, 2),
            }
            for i, (val, cnt) in enumerate(counts.items(), 1)
        ]

    @staticmethod
    def summary_stats(df: pd.DataFrame) -> dict:
        """Basic summary statistics for a DataFrame."""
        return {
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "null_counts": {
                col: int(df[col].isna().sum())
                for col in df.columns
                if df[col].isna().sum() > 0
            },
        }

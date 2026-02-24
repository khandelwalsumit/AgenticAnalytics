"""Tool registry — aggregates all tools by agent name."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from langchain_core.tools import tool

from pathlib import Path

from config import DATA_DIR, TOP_N_DEFAULT
from core.data_store import DataStore
from core.skill_loader import SkillLoader
from tools.data_tools import (
    DATA_TOOLS,
    bucket_data,
    filter_data,
    get_distribution,
    load_dataset,
    sample_data,
)
from tools.metrics import MetricsEngine
from tools.report_tools import REPORT_TOOLS, export_filtered_csv, export_to_pptx, generate_markdown_report

# ------------------------------------------------------------------
# Shared references — set by the graph at session init
# ------------------------------------------------------------------

_data_store_ref: DataStore | None = None
_skill_loader_ref: SkillLoader | None = None
_findings_accumulator: list[dict] = []


def set_analysis_deps(store: DataStore, skill_loader: SkillLoader) -> None:
    """Bind session dependencies for analysis tools."""
    global _data_store_ref, _skill_loader_ref
    _data_store_ref = store
    _skill_loader_ref = skill_loader


def reset_findings() -> None:
    """Clear accumulated findings (for new session)."""
    global _findings_accumulator
    _findings_accumulator = []


def add_finding(finding: dict) -> None:
    """Add a finding to the accumulator."""
    _findings_accumulator.append(finding)


# ------------------------------------------------------------------
# Business Analyst tools
# ------------------------------------------------------------------


@tool
def analyze_bucket(bucket: str, questions: list[str]) -> str:
    """Analyze a data bucket against specific questions.

    Only LLM_ANALYSIS_COLUMNS are included in distributions and samples
    to keep context small for downstream LLM agents.

    Args:
        bucket: DataStore key for the bucket.
        questions: List of analysis questions to investigate.

    Returns:
        JSON with bucket metadata, distributions, and sample data for analysis.
    """
    if _data_store_ref is None:
        return json.dumps({"error": "DataStore not initialized"})

    store = _data_store_ref
    df = store.get_dataframe(bucket)
    meta = store.get_metadata(bucket)

    analysis_context: dict[str, Any] = {
        "bucket": bucket,
        "metadata": meta,
        "questions": questions,
        "row_count": len(df),
    }

    # Distributions for LLM analysis columns only
    from config import LLM_ANALYSIS_COLUMNS, GROUP_BY_COLUMNS

    llm_cols = [c for c in LLM_ANALYSIS_COLUMNS if c in df.columns]
    distributions = {}
    for col in llm_cols:
        dist = MetricsEngine.get_distribution(df, col)
        if "distribution" in dist:
            dist["distribution"] = dist["distribution"][:10]
        distributions[col] = dist

    # Also include grouping column distributions for context
    for col in GROUP_BY_COLUMNS:
        if col in df.columns and col not in distributions:
            dist = MetricsEngine.get_distribution(df, col)
            if "distribution" in dist:
                dist["distribution"] = dist["distribution"][:10]
            distributions[col] = dist

    analysis_context["distributions"] = distributions

    # Sample rows — only LLM-relevant columns
    relevant_cols = list(dict.fromkeys(
        LLM_ANALYSIS_COLUMNS + GROUP_BY_COLUMNS + ["exact_problem_statement"]
    ))
    available_cols = [c for c in relevant_cols if c in df.columns]
    df_slim = df[available_cols] if available_cols else df

    sample = df_slim.sample(n=min(10, len(df_slim)), random_state=42)
    rows = []
    for _, row in sample.iterrows():
        row_dict = {}
        for col, val in row.items():
            s = str(val)
            row_dict[col] = s[:300] + "..." if len(s) > 300 else s
        rows.append(row_dict)
    analysis_context["sample_rows"] = rows
    analysis_context["columns_included"] = available_cols

    return json.dumps(analysis_context, indent=2)


@tool
def apply_skill(skill_name: str, bucket: str) -> str:
    """Load a skill and provide its analysis framework alongside bucket data.

    Args:
        skill_name: Name of the skill (e.g., 'payment_transfer').
        bucket: DataStore key for the data bucket to analyze.

    Returns:
        JSON with skill content and bucket context for LLM analysis.
    """
    if _skill_loader_ref is None:
        return json.dumps({"error": "SkillLoader not initialized"})
    if _data_store_ref is None:
        return json.dumps({"error": "DataStore not initialized"})

    skill_content = _skill_loader_ref.load_skill(skill_name)
    meta = _data_store_ref.get_metadata(bucket)
    df = _data_store_ref.get_dataframe(bucket)

    top_problems = (
        MetricsEngine.top_n(df, "exact_problem_statement", n=10)
        if "exact_problem_statement" in df.columns
        else []
    )

    return json.dumps(
        {
            "skill": skill_name,
            "skill_content": skill_content,
            "bucket": bucket,
            "bucket_metadata": meta,
            "row_count": len(df),
            "top_problems": top_problems,
        },
        indent=2,
    )


@tool
def get_findings_summary() -> str:
    """Aggregate and rank all findings accumulated so far.

    Returns:
        JSON with ranked findings list.
    """
    ranked = MetricsEngine.rank_findings(list(_findings_accumulator))
    return json.dumps({"total_findings": len(ranked), "findings": ranked}, indent=2)


# ------------------------------------------------------------------
# Critique tools
# ------------------------------------------------------------------


@tool
def validate_findings(findings: list[dict]) -> str:
    """Validate findings for completeness and consistency.

    Args:
        findings: List of RankedFinding dicts to validate.

    Returns:
        JSON with validation results and issues found.
    """
    issues = []
    required_fields = [
        "finding", "category", "volume", "impact_score",
        "ease_score", "confidence", "recommended_action",
    ]

    for i, f in enumerate(findings):
        for field in required_fields:
            if field not in f:
                issues.append({
                    "finding_index": i, "severity": "high",
                    "issue": f"Missing required field: {field}",
                })
        if "volume" in f and not (0 <= f["volume"] <= 100):
            issues.append({
                "finding_index": i, "severity": "medium",
                "issue": f"Volume {f['volume']}% out of range [0, 100]",
            })
        if "confidence" in f and not (0 <= f["confidence"] <= 1):
            issues.append({
                "finding_index": i, "severity": "medium",
                "issue": f"Confidence {f['confidence']} out of range [0, 1]",
            })
        if "recommended_action" in f and len(str(f["recommended_action"])) < 10:
            issues.append({
                "finding_index": i, "severity": "low",
                "issue": "Recommendation too vague (< 10 chars)",
            })

    return json.dumps({
        "total_findings": len(findings),
        "issues_found": len(issues),
        "issues": issues,
        "valid": len(issues) == 0,
    }, indent=2)


@tool
def score_quality(
    findings_count: int,
    coverage_score: float,
    actionability_score: float,
    consistency_score: float,
    data_accuracy_score: float,
) -> str:
    """Compute an overall quality score for the analysis.

    Args:
        findings_count: Number of findings produced.
        coverage_score: How well major themes are covered (0-1).
        actionability_score: How actionable recommendations are (0-1).
        consistency_score: How consistent findings are across buckets (0-1).
        data_accuracy_score: How accurately data is cited (0-1).

    Returns:
        JSON with overall quality score and breakdown.
    """
    weights = {
        "coverage": 0.25,
        "actionability": 0.30,
        "consistency": 0.20,
        "data_accuracy": 0.25,
    }
    scores = {
        "coverage": coverage_score,
        "actionability": actionability_score,
        "consistency": consistency_score,
        "data_accuracy": data_accuracy_score,
    }
    overall = sum(scores[k] * weights[k] for k in weights)

    return json.dumps({
        "overall_quality_score": round(overall, 3),
        "breakdown": scores,
        "weights": weights,
        "findings_count": findings_count,
        "grade": (
            "A" if overall >= 0.9 else
            "B" if overall >= 0.75 else
            "C" if overall >= 0.6 else "D"
        ),
    }, indent=2)


# ------------------------------------------------------------------
# DataViz tool (chart code execution)
# ------------------------------------------------------------------


@tool
def execute_chart_code(code: str, output_filename: str) -> str:
    """Execute Python code to generate a chart image.

    Args:
        code: Python code using matplotlib to generate a chart.
              The variable ``output_path`` is pre-set to the target file path.
        output_filename: Filename for the chart image (e.g., 'friction_distribution.png').

    Returns:
        JSON with the path to the saved chart image.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    output_path = Path(DATA_DIR) / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    exec_globals = {
        "plt": plt,
        "pd": pd,
        "np": np,
        "output_path": str(output_path),
    }
    try:
        exec(code, exec_globals)  # noqa: S102
    except Exception as exc:
        return json.dumps({"error": str(exc), "filename": output_filename})
    finally:
        plt.close("all")

    return json.dumps({"chart_path": str(output_path), "filename": output_filename})


# ------------------------------------------------------------------
# Aggregated registries
# ------------------------------------------------------------------

ANALYSIS_TOOLS = [analyze_bucket, apply_skill, get_findings_summary]
CRITIQUE_TOOLS = [validate_findings, score_quality]
CHART_TOOLS = [execute_chart_code]

TOOL_REGISTRY: dict[str, Any] = {
    "load_dataset": load_dataset,
    "filter_data": filter_data,
    "bucket_data": bucket_data,
    "sample_data": sample_data,
    "get_distribution": get_distribution,
    "analyze_bucket": analyze_bucket,
    "apply_skill": apply_skill,
    "get_findings_summary": get_findings_summary,
    "generate_markdown_report": generate_markdown_report,
    "export_to_pptx": export_to_pptx,
    "export_filtered_csv": export_filtered_csv,
    "validate_findings": validate_findings,
    "score_quality": score_quality,
    "execute_chart_code": execute_chart_code,
}

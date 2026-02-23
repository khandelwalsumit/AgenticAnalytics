"""Pydantic output schemas for structured-output agents.

These models mirror the JSON contracts already documented in each agent's
system prompt. Using ``with_structured_output`` on the LLM guarantees the
model returns valid, parseable objects — eliminating the fragile
``_parse_supervisor_decision`` regex/json fallback approach.

Agents that use structured output:
  - supervisor        → SupervisorOutput
  - planner           → PlannerOutput
  - data_analyst      → DataAnalystOutput
  - synthesizer_agent → SynthesizerOutput
  - critique          → CritiqueOutput
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class SupervisorOutput(BaseModel):
    """Structured decision output from the Supervisor agent."""

    decision: Literal["answer", "clarify", "extract", "analyse", "execute"] = Field(
        description="Routing decision: what action to take next."
    )
    confidence: int = Field(
        ge=0,
        le=100,
        description="Confidence level 0-100. Below 70 should trigger 'clarify'.",
    )
    reasoning: str = Field(description="Concise explanation of the decision.")
    response: str = Field(
        description=(
            "User-facing content: answer text, clarification question, "
            "extraction start message, analysis objective, or plan step description."
        )
    )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class PlanTask(BaseModel):
    """A single executable step in the analysis plan."""

    title: str = Field(description="Human-readable description of the step.")
    agent: str = Field(description="Agent or subgraph name to execute this step.")
    status: Literal["ready", "todo", "in_progress", "done", "failed"] = Field(
        default="ready",
        description="Initial status — always 'ready' when just planned.",
    )


class PlannerOutput(BaseModel):
    """Structured execution plan from the Planner agent."""

    plan_tasks: list[PlanTask] = Field(
        description="Ordered list of plan steps for the Supervisor to execute."
    )
    plan_steps_total: int = Field(description="Total number of steps in this plan.")
    analysis_objective: str = Field(
        description="Confirmed analysis objective extracted from user intent."
    )
    reasoning: str = Field(description="Brief explanation of why this plan was chosen.")


# ---------------------------------------------------------------------------
# Data Analyst
# ---------------------------------------------------------------------------


class DataAnalystOutput(BaseModel):
    """Structured output from the Data Analyst agent."""

    decision: Literal["success", "clarify", "caution"] = Field(
        description=(
            "Outcome: 'success' = filters applied, 'clarify' = need more info, "
            "'caution' = broad/unfiltered result."
        )
    )
    confidence: int = Field(
        ge=0,
        le=100,
        description="Confidence in the filter mapping and data extraction.",
    )
    reasoning: str = Field(description="Concise explanation of the decision.")
    response: str = Field(
        description="User-facing summary: filter results, schema info, or clarification question."
    )


# ---------------------------------------------------------------------------
# Synthesizer Agent
# ---------------------------------------------------------------------------


class DominantDrivers(BaseModel):
    """Breakdown of how many findings each lens drives."""

    digital: int = Field(default=0)
    operations: int = Field(default=0)
    communication: int = Field(default=0)
    policy: int = Field(default=0)


class SynthesisSummary(BaseModel):
    """High-level synthesis summary stats."""

    total_findings: int
    dominant_drivers: DominantDrivers
    multi_factor_count: int = Field(description="Themes flagged by 2+ lenses.")
    overall_preventability: float = Field(
        ge=0.0,
        le=1.0,
        description="0.0 = unavoidable, 1.0 = entirely preventable.",
    )
    quick_wins_count: int
    executive_narrative: str = Field(description="2-3 sentence overall summary.")


class RankedFinding(BaseModel):
    """A single synthesized, prioritized finding."""

    finding: str
    category: str
    volume: float
    impact_score: float = Field(ge=0.0, le=1.0)
    ease_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str
    dominant_driver: Literal["digital", "operations", "communication", "policy"]
    contributing_factors: list[str]
    preventability_score: float = Field(ge=0.0, le=1.0)
    priority_quadrant: Literal[
        "quick_win", "strategic_investment", "low_hanging_fruit", "deprioritize"
    ]


class SynthesizerOutput(BaseModel):
    """Structured unified synthesis from the Synthesizer agent."""

    decision: Literal["complete", "incomplete"] = Field(
        description="'complete' = all 4 agents produced output, 'incomplete' = gaps found."
    )
    confidence: int = Field(ge=0, le=100)
    reasoning: str = Field(description="Brief explanation of synthesis quality.")
    summary: SynthesisSummary
    findings: list[RankedFinding] = Field(
        description="Ranked findings sorted by impact × ease descending."
    )


# ---------------------------------------------------------------------------
# Critique
# ---------------------------------------------------------------------------


class QualityIssue(BaseModel):
    """A single quality issue identified by the Critique agent."""

    dimension: Literal["accuracy", "completeness", "actionability", "consistency", "bias"]
    severity: Literal["high", "medium", "low"]
    description: str
    location: str = Field(description="Which finding or section is affected.")
    suggested_fix: str


class DimensionScores(BaseModel):
    """Per-dimension quality scores (0.0–1.0)."""

    accuracy: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    actionability: float = Field(ge=0.0, le=1.0)
    consistency: float = Field(ge=0.0, le=1.0)
    bias: float = Field(ge=0.0, le=1.0)


class CritiqueOutput(BaseModel):
    """Structured QA review from the Critique agent."""

    decision: Literal["pass", "needs_revision", "fail"] = Field(
        description=(
            "'pass' = score ≥ 0.75 and no high-severity issues, "
            "'needs_revision' = score 0.60-0.74 or has high issues, "
            "'fail' = score < 0.60."
        )
    )
    confidence: int = Field(ge=0, le=100)
    reasoning: str = Field(description="Brief explanation of overall quality assessment.")
    quality_score: float = Field(ge=0.0, le=1.0)
    grade: Literal["A", "B", "C", "D"]
    summary: str = Field(description="2-3 sentence overall assessment.")
    issues: list[QualityIssue] = Field(
        description="Quality issues found, sorted by severity (high first)."
    )
    top_issues: list[str] = Field(description="Top 3 most critical issues as strings.")
    dimension_scores: DimensionScores


# ---------------------------------------------------------------------------
# Registry: agent name → output schema class
# ---------------------------------------------------------------------------

STRUCTURED_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "supervisor": SupervisorOutput,
    "planner": PlannerOutput,
    "data_analyst": DataAnalystOutput,
    "synthesizer_agent": SynthesizerOutput,
    "critique": CritiqueOutput,
}

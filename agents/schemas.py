"""Pydantic output schemas for structured-output agents.

These models mirror the JSON contracts already documented in each agent's
system prompt. Using ``with_structured_output`` on the LLM guarantees the
model returns valid, parseable objects — eliminating the fragile
``_parse_supervisor_decision`` regex/json fallback approach.

Agents that use structured output:
  - supervisor        → SupervisorOutput
  - planner           → PlannerOutput
  - synthesizer_agent → SynthesizerOutput (reads friction outputs from DataStore files)

Agents that use ReAct (tool-calling) with JSON fallback parsing:
  - data_analyst      → DataAnalystOutput (schema kept for reference)
  - critique          → CritiqueOutput (needs validate_findings, score_quality tools)
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class SupervisorOutput(BaseModel):
    """Structured decision output from the Supervisor agent."""

    decision: Literal["answer", "plan", "execute"] = Field(
        description="Routing decision: 'answer' for direct responses/QnA, "
                    "'plan' to create/update execution plan, "
                    "'execute' to run next step in existing plan."
    )
    confidence: int = Field(
        ge=0,
        le=100,
        description="Confidence level 0-100.",
    )
    reasoning: str = Field(description="Concise explanation of the decision.")
    response: str = Field(
        description="User-visible text for 'answer'; empty for plan/execute."
    )
    proposed_filters: dict[str, Any] = Field(
        default_factory=dict,
        description="When decision='plan', map column names to proposed filter values "
                    "based on the user's request and available dataset filters. "
                    "Empty for 'answer' and 'execute'.",
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
    selected_agents: list[str] = Field(
        description=(
            "Selected friction lens agents to run based on analysis_scope_reply. "
            "Use only: digital_friction_agent, operations_agent, communication_agent, policy_agent."
        )
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
# Synthesizer Agent — LLM output normalizers
# ---------------------------------------------------------------------------

_VALID_QUADRANTS = {"quick_win", "strategic_investment", "low_hanging_fruit", "deprioritize"}
_QUADRANT_KEYWORDS: dict[str, str] = {
    "quick": "quick_win",
    "win": "quick_win",
    "strategic": "strategic_investment",
    "invest": "strategic_investment",
    "low": "low_hanging_fruit",
    "hanging": "low_hanging_fruit",
    "fruit": "low_hanging_fruit",
    "deprioritize": "deprioritize",
    "deprio": "deprioritize",
    "monitor": "deprioritize",
    "defer": "deprioritize",
}

_VALID_DRIVERS = {"digital", "operations", "communication", "policy"}
_DRIVER_KEYWORDS: dict[str, str] = {
    "digital": "digital",
    "tech": "digital",
    "operations": "operations",
    "ops": "operations",
    "operational": "operations",
    "communication": "communication",
    "comms": "communication",
    "comm": "communication",
    "policy": "policy",
    "policies": "policy",
    "regulatory": "policy",
}


def _normalize_quadrant(raw: str) -> str:
    """Map any LLM quadrant string to a valid literal value."""
    cleaned = raw.lower().strip().replace("-", "_").replace(" ", "_")
    if cleaned in _VALID_QUADRANTS:
        return cleaned
    for keyword, quadrant in _QUADRANT_KEYWORDS.items():
        if keyword in cleaned:
            return quadrant
    return "strategic_investment"


def _normalize_driver(raw: Any) -> str:
    """Map any LLM-produced driver value to a valid literal value."""
    if raw is None:
        return "digital"
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                candidate = _normalize_driver(item)
                if candidate in _VALID_DRIVERS:
                    return candidate
        return "digital"
    if isinstance(raw, dict):
        for key in ("dominant_driver", "driver", "dimension", "type"):
            if key in raw:
                return _normalize_driver(raw.get(key))
        return "digital"

    cleaned = str(raw).lower().strip().replace("-", "_").replace(" ", "_")
    if cleaned in _VALID_DRIVERS:
        return cleaned
    for keyword, driver in _DRIVER_KEYWORDS.items():
        if keyword in cleaned:
            return driver
    return "digital"


_LABEL_TO_PROB: dict[str, float] = {
    "high": 0.8, "medium": 0.5, "low": 0.2,
    "very high": 0.9, "very low": 0.1,
    "none": 0.0, "full": 1.0, "n/a": 0.5, "unknown": 0.5,
}


def _coerce_probability(value: Any, default: float = 0.5) -> float:
    """Coerce an LLM-produced value to a 0.0–1.0 float.

    Handles:
    - Already a float/int in [0, 1]          → pass through
    - Int/float > 1 (e.g. 75 meaning 75%)    → divide by 100
    - String "0.75" or "75%"                 → parse then normalise
    - Label strings "high", "medium", "low"  → map to fixed values
    - Anything unparseable                   → return default
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 100.0 if v > 1.0 else max(0.0, min(1.0, v))
    if isinstance(value, str):
        s = value.strip()
        label = s.lower().rstrip(".")
        if label in _LABEL_TO_PROB:
            return _LABEL_TO_PROB[label]
        s = s.rstrip("%").strip()
        try:
            v = float(s)
            return v / 100.0 if v > 1.0 else max(0.0, min(1.0, v))
        except ValueError:
            return default
    return default


# ---------------------------------------------------------------------------
# Synthesizer Agent — models
# ---------------------------------------------------------------------------


class DominantDrivers(BaseModel):
    """Breakdown of how many findings each lens drives."""

    digital: int = Field(default=0)
    operations: int = Field(default=0)
    communication: int = Field(default=0)
    policy: int = Field(default=0)

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_list(cls, data: Any) -> Any:
        """LLM sometimes returns a list like ['digital'] instead of a dict."""
        if isinstance(data, list):
            counts: dict[str, int] = {"digital": 0, "operations": 0, "communication": 0, "policy": 0}
            for item in data:
                key = str(item).lower().strip()
                if key in counts:
                    counts[key] += 1
            return counts
        if isinstance(data, str):
            key = data.lower().strip()
            return {key: 1} if key in ("digital", "operations", "communication", "policy") else {}
        return data


class SynthesisSummary(BaseModel):
    """High-level synthesis summary stats."""

    total_calls_analyzed: int = Field(default=0, description="Total call count across all themes.")
    total_findings: int = Field(default=0)
    total_themes: int = Field(default=0, description="Number of unique themes synthesized.")
    dominant_drivers: DominantDrivers = Field(default_factory=DominantDrivers)
    multi_factor_count: int = Field(default=0, description="Themes flagged by 2+ lenses.")
    overall_preventability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="0.0 = unavoidable, 1.0 = entirely preventable.",
    )
    quick_wins_count: int = Field(default=0)
    executive_narrative: str = Field(default="", description="2-3 sentence overall summary with call counts.")

    @model_validator(mode="before")
    @classmethod
    def _coerce_floats(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "overall_preventability" in data:
            data["overall_preventability"] = _coerce_probability(data["overall_preventability"], default=0.5)
        return data


class RankedFinding(BaseModel):
    """A single synthesized, prioritized finding."""

    finding: str = Field(default="")
    theme: str = Field(default="", description="Theme/bucket this finding belongs to.")
    category: str = Field(default="general")
    call_count: int = Field(default=0, description="Raw call count for this finding.")
    call_percentage: float = Field(default=0.0, description="Percentage of total call volume.")
    volume: float = Field(default=0.0, description="Legacy volume field (percentage).")
    impact_score: float = Field(ge=0.0, le=10.0, default=5.0, description="1-10 impact scale.")
    ease_score: float = Field(ge=0.0, le=10.0, default=5.0, description="1-10 ease of implementation scale.")
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    recommended_action: str = Field(default="")
    dominant_driver: Literal["digital", "operations", "communication", "policy"] = Field(default="digital")
    contributing_factors: list[str] = Field(default_factory=list)
    preventability_score: float = Field(ge=0.0, le=1.0, default=0.5)
    priority_quadrant: Literal[
        "quick_win", "strategic_investment", "low_hanging_fruit", "deprioritize"
    ] = Field(default="strategic_investment")

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        pq = data.get("priority_quadrant")
        if isinstance(pq, str):
            data["priority_quadrant"] = _normalize_quadrant(pq)
        dd = data.get("dominant_driver")
        if dd is not None:
            data["dominant_driver"] = _normalize_driver(dd)
        for field in ("preventability_score", "confidence"):
            if field in data:
                data[field] = _coerce_probability(data[field], default=0.5)
        # call_percentage and volume are 0-100 scale, NOT 0-1 probability
        for field in ("call_percentage", "volume"):
            if field in data:
                try:
                    data[field] = round(float(data[field]), 1)
                except (TypeError, ValueError):
                    data[field] = 0.0
        for field in ("impact_score", "ease_score"):
            if field in data:
                raw = data[field]
                try:
                    v = float(raw) if not isinstance(raw, (int, float)) else float(raw)
                    # LLM may return 0-100 scale instead of 0-10
                    data[field] = v / 10.0 if v > 10.0 else max(0.0, min(10.0, v))
                except (TypeError, ValueError):
                    data[field] = 5.0
        return data


class ThemeDriver(BaseModel):
    """A single driver within a theme, tagged with its source dimension."""

    driver: str
    call_count: int = Field(default=0)
    contribution_pct: float = Field(default=0.0)
    type: Literal["primary", "secondary"] = Field(default="secondary")
    dimension: Literal["digital", "operations", "communication", "policy"] = Field(default="digital")
    recommended_solution: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_string(cls, data: Any) -> Any:
        """LLM sometimes returns a plain string instead of a ThemeDriver dict."""
        if isinstance(data, str):
            return {"driver": data, "dimension": "digital"}
        if isinstance(data, dict):
            # Map alternate field names → 'driver'
            if not data.get("driver"):
                data["driver"] = (
                    data.pop("driver_description", "")
                    or data.pop("finding", "")
                    or data.pop("description", "")
                    or ""
                )
            dim = data.get("dimension")
            if dim is not None:
                data["dimension"] = _normalize_driver(dim)
        return data


class ThemeSummary(BaseModel):
    """Theme-level aggregation across all friction dimensions."""

    theme: str = Field(default="")
    call_count: int = Field(default=0)
    call_percentage: float = Field(default=0.0)
    impact_score: float = Field(ge=0.0, le=10.0, default=5.0)
    ease_score: float = Field(ge=0.0, le=10.0, default=5.0)
    priority_score: float = Field(default=5.0, description="impact * 0.6 + ease * 0.4")
    dominant_driver: Literal["digital", "operations", "communication", "policy"] = Field(default="digital")
    contributing_factors: list[str] = Field(default_factory=list)
    preventability_score: float = Field(ge=0.0, le=1.0, default=0.5)
    priority_quadrant: Literal[
        "quick_win", "strategic_investment", "low_hanging_fruit", "deprioritize"
    ] = Field(default="strategic_investment")
    all_drivers: list[ThemeDriver] = Field(default_factory=list)
    quick_wins: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # LLM uses "theme_name" or "bucket_name" instead of "theme"
        if "theme_name" in data and "theme" not in data:
            data["theme"] = data.pop("theme_name")
        if "bucket_name" in data and not data.get("theme"):
            data["theme"] = data["bucket_name"]
        # Coerce contributing_factors: LLM may put dicts instead of strings
        cf = data.get("contributing_factors")
        if isinstance(cf, list):
            coerced = []
            for item in cf:
                if isinstance(item, dict):
                    coerced.append(item.get("driver", item.get("factor", str(item))))
                else:
                    coerced.append(str(item))
            data["contributing_factors"] = coerced
        pq = data.get("priority_quadrant")
        if isinstance(pq, str):
            data["priority_quadrant"] = _normalize_quadrant(pq)
        dd = data.get("dominant_driver")
        if dd is not None:
            data["dominant_driver"] = _normalize_driver(dd)
        for field in ("preventability_score",):
            if field in data:
                data[field] = _coerce_probability(data[field], default=0.5)
        # call_percentage is 0-100 scale, NOT 0-1 probability
        if "call_percentage" in data:
            try:
                data["call_percentage"] = round(float(data["call_percentage"]), 1)
            except (TypeError, ValueError):
                data["call_percentage"] = 0.0
        for field in ("impact_score", "ease_score", "priority_score"):
            if field in data:
                raw = data[field]
                try:
                    v = float(raw) if not isinstance(raw, (int, float)) else float(raw)
                    data[field] = v / 10.0 if v > 10.0 else max(0.0, min(10.0, v))
                except (TypeError, ValueError):
                    data[field] = 5.0
        return data


class SynthesizerOutput(BaseModel):
    """Structured unified synthesis from the Synthesizer agent."""

    decision: Literal["complete", "incomplete"] = Field(
        description="'complete' = all 4 agents produced output, 'incomplete' = gaps found."
    )
    confidence: int = Field(ge=0, le=100)
    reasoning: str = Field(description="Brief explanation of synthesis quality.")
    summary: SynthesisSummary
    themes: list[ThemeSummary] = Field(
        default_factory=list,
        description="Theme-level aggregations sorted by priority_score descending.",
    )
    findings: list[RankedFinding] = Field(
        description="Individual ranked findings sorted by call_count descending.",
    )


# ---------------------------------------------------------------------------
# Formatting Agent — Section-based Slide Blueprint
# ---------------------------------------------------------------------------


class SectionSlideElement(BaseModel):
    """A single content element in a section slide blueprint.

    Simpler than the legacy SlideElement — no image placement fields.
    Charts are referenced by key; the PPTX builder handles placement.
    """

    type: str = Field(
        default="point_description",
        description="Element type: h2, h3, point_heading, point_description, sub_point, bullet, callout, table, chart_placeholder",
    )
    text: str = Field(default="")
    bold_label: Optional[str] = Field(default=None, description="Bold prefix before text (e.g., 'Impact:')")
    level: Optional[int] = Field(default=None, ge=1, le=3, description="Bullet indent level (1-3)")

    # table-only
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)

    # chart-only
    chart_key: Optional[str] = Field(default=None, description="Chart key: friction_distribution, impact_ease_scatter, driver_breakdown")
    position: Optional[Literal["right", "left", "bottom", "full"]] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def coerce_fields(cls, data: Any) -> Any:
        """Coerce LLM quirks: stringify non-str values, normalise rows to list[list[str]]."""
        if not isinstance(data, dict):
            return data
        # Coerce rows: each row must be list[str]; dicts become their values
        raw_rows = data.get("rows")
        if isinstance(raw_rows, list):
            coerced: list[list[str]] = []
            for row in raw_rows:
                if isinstance(row, list):
                    coerced.append([str(cell) for cell in row])
                elif isinstance(row, dict):
                    coerced.append([str(v) for v in row.values()])
                else:
                    coerced.append([str(row)])
            data = {**data, "rows": coerced}
        # Coerce headers: each header must be str
        raw_headers = data.get("headers")
        if isinstance(raw_headers, list):
            data = {**data, "headers": [str(h) for h in raw_headers]}
        return data


class SectionSlide(BaseModel):
    """One slide in a section blueprint."""

    slide_number: int = Field(default=1, ge=1)
    slide_role: str = Field(default="content", description="Slide role from section contract: hook_and_quick_wins, pain_points, impact_matrix, recommendations, theme_card")
    layout_index: int = Field(default=1, ge=0, description="Template layout index from template_spec")
    title: str = Field(default="")
    subtitle: Optional[str] = Field(default=None)
    elements: list[SectionSlideElement] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_elements(cls, data: Any) -> Any:
        """Coerce elements list: strings become point_description dicts; non-dicts are dropped."""
        if not isinstance(data, dict):
            return data
        raw_elements = data.get("elements")
        if not isinstance(raw_elements, list):
            return data
        coerced: list[dict] = []
        for el in raw_elements:
            if isinstance(el, dict):
                coerced.append(el)
            elif isinstance(el, str) and el.strip():
                coerced.append({"type": "point_description", "text": el})
        data = {**data, "elements": coerced}
        return data


class SectionBlueprintOutput(BaseModel):
    """Structured output from formatting agent — one section at a time."""

    section_key: str = Field(description="Section identifier: exec_summary, impact, or theme_deep_dives")
    slides: list[SectionSlide] = Field(default_factory=list)


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
    "synthesizer_agent": SynthesizerOutput,
    "formatting_agent": SectionBlueprintOutput,
    # data_analyst removed: it needs ReAct (tool-calling) agent, not structured-only.
    # DataAnalystOutput schema is kept for reference / fallback JSON parsing.
    # critique removed: needs validate_findings and score_quality tools.
    # CritiqueOutput schema is kept for reference / fallback JSON parsing.
}

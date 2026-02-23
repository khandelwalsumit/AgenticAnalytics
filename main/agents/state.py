"""Shared state definitions for the analytics graph."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ExecutionTrace(TypedDict):
    """Structured trace for each agent execution step."""

    step_id: str
    agent: str
    input_summary: str
    output_summary: str
    tools_used: list[str]
    latency_ms: int
    success: bool


class PlanTask(TypedDict):
    """A visible task in the live task list.

    Status values: ``todo`` | ``in_progress`` | ``done`` | ``failed``
    """

    id: str
    title: str
    status: str  # todo | in_progress | done | failed | blocked


class AnalyticsState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

    # User intent
    user_focus: str
    analysis_type: str  # "domain" | "operational" | "combined"
    selected_skills: list[str]
    critique_enabled: bool

    # Plan (Planner generates, Supervisor executes)
    plan_steps_total: int
    plan_steps_completed: int
    plan_tasks: list[PlanTask]  # Live task list shown in Chainlit UI

    # Execution trace
    execution_trace: list[ExecutionTrace]

    # Node telemetry for UI (graph contract)
    reasoning: list[dict[str, Any]]
    node_io: dict[str, Any]
    io_trace: list[dict[str, Any]]
    last_completed_node: str

    # Data — METADATA ONLY (raw data lives in DataStore)
    dataset_path: str
    dataset_schema: dict[str, Any]
    active_filters: dict[str, Any]
    data_buckets: dict[str, dict[str, Any]]

    # Analysis — scored findings
    findings: list[RankedFinding]
    domain_analysis: dict[str, Any]
    operational_analysis: dict[str, Any]

    # Friction lens agent outputs (written by each agent independently)
    digital_analysis: dict[str, Any]
    operations_analysis: dict[str, Any]
    communication_analysis: dict[str, Any]
    policy_analysis: dict[str, Any]

    # Synthesis output (written by Synthesizer Agent)
    synthesis_result: dict[str, Any]

    # Reporting subgraph outputs
    narrative_output: dict[str, Any]
    dataviz_output: dict[str, Any]
    formatting_output: dict[str, Any]

    # Report — metadata only (full text in DataStore)
    report_markdown_key: str
    report_file_path: str
    data_file_path: str

    # Quality
    critique_feedback: dict[str, Any]
    quality_score: float

    # Control flow
    next_agent: str
    supervisor_decision: str  # "answer" | "clarify" | "extract" | "analyse" | "execute"
    requires_user_input: bool
    checkpoint_message: str
    checkpoint_prompt: str
    checkpoint_token: str
    pending_input_for: str
    analysis_complete: bool  # True once all plan steps are done
    phase: str  # "analysis" | "qa"

    # Supervisor decision context
    filters_applied: dict[str, Any]
    themes_for_analysis: list[str]
    navigation_log: list[dict[str, Any]]
    analysis_objective: str

    # Session agent selection
    selected_agents: list[str]
    selected_friction_agents: list[str]
    auto_approve_checkpoints: bool

    # Fault injection / resilience (dev/test)
    fault_injection: dict[str, str]
    error_count: int
    recoverable_error: str

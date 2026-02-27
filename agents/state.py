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

    # Data — METADATA ONLY (raw data lives in cache files)
    dataset_path: str                   # path to input parquet (never copied)
    dataset_schema: dict[str, Any]
    active_filters: dict[str, Any]
    data_buckets: dict[str, dict[str, Any]]
    filtered_parquet_path: str          # data/.cache/<thread_id>/filtered.parquet
    bucket_paths: dict[str, str]        # {bucket_key → parquet_path}

    # Compact supervisor-answerable summaries (kept in state, always small)
    top_themes: list[str]               # theme names from data_analyst bucketing
    analytics_insights: dict[str, Any]  # exec_narrative, top_themes, quick_wins_count, etc.

    # Analysis — scored findings (dicts matching RankedFinding schema)
    findings: list[dict[str, Any]]
    domain_analysis: dict[str, Any]
    operational_analysis: dict[str, Any]

    # Friction lens agent outputs (written by each agent independently)
    digital_analysis: dict[str, Any]
    operations_analysis: dict[str, Any]
    communication_analysis: dict[str, Any]
    policy_analysis: dict[str, Any]

    # Friction agent output file references (agent_id → DataStore key, legacy)
    friction_output_files: dict[str, str]
    # Friction agent markdown paths (agent_id → absolute .md path) — primary
    friction_md_paths: dict[str, str]

    # Synthesis output (written by Synthesizer Agent)
    synthesis_result: dict[str, Any]
    synthesis_output_file: str   # DataStore key (legacy)
    synthesis_path: str          # absolute path to synthesis_vN.md (primary)

    # Reporting subgraph outputs
    narrative_output: dict[str, Any]
    narrative_path: str          # absolute path to narrative_vN.md (primary)
    dataviz_output: dict[str, Any]
    formatting_output: dict[str, Any]

    # Report — metadata only (full text in DataStore)
    report_markdown_key: str
    report_file_path: str
    data_file_path: str
    markdown_file_path: str

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
    expected_friction_lenses: list[str]
    missing_friction_lenses: list[str]
    auto_approve_checkpoints: bool

    # Fault injection / resilience (dev/test)
    fault_injection: dict[str, str]
    error_count: int
    recoverable_error: str

"""Shared state definitions for the analytics graph.

Rule enforced by this state: nothing large lives in state.
Every agent reads a file, writes a file, updates one or two path fields, returns.
State stays under 5KB regardless of dataset size.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AnalyticsState(TypedDict):

    # ── Identity ──────────────────────────────────────────────────────────
    thread_id: str

    # ── Conversation ──────────────────────────────────────────────────────
    messages: Annotated[list[AnyMessage], add_messages]

    # ── Orchestration ─────────────────────────────────────────────────────
    phase: str                      # "setup" | "analysis" | "reporting" | "qna"
    plan_tasks: list                # list of {name, status} dicts
    plan_steps_total: int
    plan_steps_completed: int
    next_agent: str
    supervisor_decision: str        # "answer" | "plan" | "execute"
    last_completed_node: str
    execution_trace: list           # ordered list of node execution dicts
    reasoning: list                 # list of {step_name, step_text} for Chainlit UI
    analysis_complete: bool

    # ── User intent ───────────────────────────────────────────────────────
    analysis_objective: str         # cleaned statement of what user wants
    proposed_filters: dict          # LLM-extracted filters before confirmation
    filters_applied: dict           # filters confirmed and applied
    selected_agents: list           # lens agents user chose to run
    analysis_scope_reply: str       # raw user reply to lens confirmation prompt
    themes_for_analysis: list       # theme names from bucketing (for supervisor context)

    # ── Human-in-loop ─────────────────────────────────────────────────────
    pending_input_for: str          # which node is waiting for user input
    checkpoint_message: str         # message shown to user at interrupt
    checkpoint_prompt: str          # question asked at interrupt
    auto_approve_checkpoints: bool
    critique_enabled: bool

    # ── Dataset ───────────────────────────────────────────────────────────
    dataset_path: str               # path to source parquet
    dataset_schema: dict            # column names, dtypes, sample values

    # ── Data layer — file pointers only ───────────────────────────────────
    filtered_parquet_path: str      # output of filter_data tool
    bucket_manifest_path: str       # JSON listing all buckets with metadata
                                    # replaces: data_buckets, bucket_paths,
                                    #           top_themes, themes_for_analysis

    # ── Analysis — file pointers only ─────────────────────────────────────
    lens_outputs_dir: str           # dir containing <bucket_id>_<lens>.md files
                                    # replaces: digital_analysis, operations_analysis,
                                    #           communication_analysis, policy_analysis,
                                    #           friction_md_paths, friction_output_files,
                                    #           lens_synthesis_paths
    synthesis_path: str             # single synthesis markdown file
                                    # replaces: synthesis_result, synthesis_output_file
    classified_solutions_path: str  # solutioning agent output JSON

    # ── Report — file pointers only ───────────────────────────────────────
    narrative_path: str             # path to narrative.md
    blueprint_path: str             # path to blueprint.json

    # ── Artifacts — single dir pointer ────────────────────────────────────
    artifacts_dir: str              # data/output/<thread_id>/
                                    # replaces: report_file_path, docx_file_path,
                                    #           data_file_path, markdown_file_path,
                                    #           report_markdown_key

    # ── Quality ───────────────────────────────────────────────────────────
    critique_feedback: str
    quality_score: float

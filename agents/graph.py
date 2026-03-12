"""Main LangGraph StateGraph assembly.

Each agent is defined as an explicit named async function inside ``build_graph``.
The docstring of every node states exactly which state fields it reads and writes,
so you can understand the full data flow without looking anywhere else.

Parallelism uses asyncio.gather (no LangGraph Send API).
Composite node (friction_analysis) orchestrates sub-agents internally.
Report pipeline is split: report_drafts (narrative + blueprint) and
artifact_writer (PPTX/CSV/MD generation) are separate graph nodes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from langchain_core.messages import AIMessage, HumanMessage

from agents.nodes import (
    # invocation helpers
    _run_structured_node,
    _run_react_node,
    _agent_output_field,
    # context builders
    _build_extra_context,
    # structured-output appliers
    _apply_supervisor,
    # tool-result extractors
    _extract_data_analyst_state,
    _extract_formatting_state,
    # plan helpers
    _advance_plan,
    # text / JSON utils
    _text,
    _trunc,
    _parse_json,
    # file writing
    _write_versioned_md,
    # constants
    AGENT_STATE_FIELDS,
)
from agents.schemas import (
    PlannerOutput,
    SupervisorOutput,
    SynthesizerOutput,
)
from agents.state import AnalyticsState
from config import MAX_MULTITHREADING_WORKERS, MAX_SUPERVISOR_MSGS
from core.agent_factory import AgentFactory
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY

from agents.graph_helpers import (
    FRICTION_SUB_AGENTS,
    REPORTING_SUB_AGENTS,
    _build_executive_summary_message,
    _build_fixed_deck_blueprint,
    _build_friction_reasoning_entries,
    _build_report_reasoning_entries,
    _make_sub_agent_entry,
    _merge_parallel_outputs,
    _merge_state_deltas,
    _record_plan_progress,
    _run_agent_with_retries,
    _run_section_artifact_writer,
    _set_sub_agent_status,
    _set_task_sub_agents_and_emit,
    _should_summarize_lens_outputs,
    _summarize_lens_buckets,
    _summarize_lens_buckets_with_llm,
    L2_BATCH_SIZE,
    _validate_artifact_paths,
    _validate_narrative,
)

logger = logging.getLogger("agenticanalytics.graph")


def build_graph(
    agent_factory: AgentFactory | None = None,
    skill_loader: SkillLoader | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Build and compile the analytics StateGraph.

    All agent nodes are defined explicitly here — one named async function per agent —
    so you can read each node and understand the full data flow without tracing into
    a factory or closure generator.

    Args:
        agent_factory: AgentFactory instance. Created with defaults if None.
        skill_loader:  SkillLoader instance. Created with defaults if None.
        checkpointer:  LangGraph checkpointer. Uses MemorySaver if None.

    Returns:
        Compiled LangGraph graph.
    """
    if agent_factory is None:
        agent_factory = AgentFactory(tool_registry=TOOL_REGISTRY)
    if skill_loader is None:
        skill_loader = SkillLoader()
    if checkpointer is None:
        checkpointer = MemorySaver()

    # ------------------------------------------------------------------
    # Pre-create structured output chains (done once at build time)
    # Structured agents: supervisor, planner, synthesizer_agent
    # ------------------------------------------------------------------
    supervisor_chain, _ = agent_factory.create_structured_chain("supervisor")
    planner_chain, _    = agent_factory.create_structured_chain("planner")
    synthesizer_chain, _ = agent_factory.create_structured_chain("synthesizer_agent")

    # ══════════════════════════════════════════════════════════════════════════
    # SUPERVISOR
    # ══════════════════════════════════════════════════════════════════════════

    async def supervisor_node(state: AnalyticsState) -> dict[str, Any]:
        """Routes user intent to the correct pipeline stage.

        Reads:
            messages               – conversation so far (trimmed: human + AI only)
            dataset_schema         – filter columns/values (injected into prompt)
            filters_applied        – current active filters (for scope-change detection)
            themes_for_analysis    – extracted themes ready for analysis
            plan_tasks             – current execution plan (for execute routing)
            analysis_objective     – confirmed objective (for context)

        Writes:
            next_agent             – which node to run next
            supervisor_decision    – routing decision string
            messages               – user-visible reply (answer/clarify/qna only)
            plan_tasks             – marks next step in-progress (execute decision)
            selected_agents      – dimension filter from user reply
        """
        ctx = _build_extra_context("supervisor", state, None)
        sys_prompt = agent_factory.parse_agent_md("supervisor").system_prompt + ctx

        # Trim messages: keep only HumanMessages + AI messages (drop internal tool calls)
        slim_state = dict(state)
        slim_msgs = []
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                slim_msgs.append(msg)
            elif isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None) and msg.content:
                slim_msgs.append(msg)
        # Cap message count: keep first 2 (original question + first reply) + last N
        if len(slim_msgs) > MAX_SUPERVISOR_MSGS:
            slim_msgs = slim_msgs[:2] + slim_msgs[-(MAX_SUPERVISOR_MSGS - 2):]
        slim_state["messages"] = slim_msgs

        base, structured, last_msg = await _run_structured_node(
            "supervisor", supervisor_chain, SupervisorOutput, sys_prompt, slim_state,
        )

        if isinstance(structured, SupervisorOutput):
            _apply_supervisor(structured, state, base)
        elif last_msg:
            raise RuntimeError(
                f"[supervisor] Structured output failed — got {type(structured).__name__}. "
                "Check chain setup or model response."
            )

        # If routing helpers requested user input (old user_checkpoint route),
        # use interrupt() to pause the graph and collect user reply inline.
        if base.get("next_agent") == "user_checkpoint":
            msg = base.get("checkpoint_message", "Awaiting your input...")
            prompt = base.get("checkpoint_prompt", "Please provide input to continue.")
            user_reply = interrupt({
                "type": base.get("pending_input_for", "supervisor_checkpoint"),
                "message": msg,
                "prompt": prompt,
            })
            # Graph resumes here with user's reply.
            # Do NOT inject HumanMessage — Command.update in on_message already does it.
            base["next_agent"] = "supervisor"
            base["requires_user_input"] = False

        return base

    # ══════════════════════════════════════════════════════════════════════════
    # PLANNER
    # ══════════════════════════════════════════════════════════════════════════

    async def planner_node(state: AnalyticsState) -> dict[str, Any]:
        """Creates the ordered execution plan from a confirmed objective and themes.

        Reads:
            filters_applied        – active filters (shown in context)
            analysis_objective     – what the user wants to know
            critique_enabled       – whether to include a QA step
            plan_tasks             – existing done steps (prepended to new plan)

        Writes:
            plan_tasks             – new ordered task list
            plan_steps_total       – total step count
            plan_steps_completed   – count of already-done steps (from existing done tasks)
            analysis_objective     – confirmed/refined objective
            reasoning              – planner's reasoning text
        """
        ctx = _build_extra_context("planner", state, None)
        sys_prompt = agent_factory.parse_agent_md("planner").system_prompt + ctx

        # Planner works from structured context only — no conversation needed
        planner_state = dict(state)
        scope_reply = state.get("analysis_scope_reply", "")
        planner_msg = f"Create an execution plan. Objective: {state.get('analysis_objective', '')}"
        if scope_reply:
            planner_msg += f"\nUser lens selection: {scope_reply}"
        planner_state["messages"] = [HumanMessage(content=planner_msg)]

        base, structured, last_msg = await _run_structured_node(
            "planner", planner_chain, PlannerOutput, sys_prompt, planner_state,
        )

        if not isinstance(structured, PlannerOutput):
            raise RuntimeError(
                f"[planner] Structured output failed — got {type(structured).__name__}. "
                "Check chain setup or model response."
            )

        new_tasks  = [t.model_dump() for t in structured.plan_tasks]
        existing   = state.get("plan_tasks", [])
        done_steps = [t for t in existing if t.get("status") == "done"]
        # Deduplicate: remove new tasks whose agent already has a done step
        done_agents = {t.get("agent") for t in done_steps}
        new_tasks = [t for t in new_tasks if t.get("agent") not in done_agents]
        all_tasks  = done_steps + new_tasks
        all_lenses = {
            "digital_friction_agent",
            "operations_agent",
            "communication_agent",
            "policy_agent",
        }
        selected = [a for a in structured.selected_agents if a in all_lenses]
        if not selected:
            selected = sorted(all_lenses)

        base.update({
            "plan_tasks":           all_tasks,
            "plan_steps_total":     len(all_tasks),
            "plan_steps_completed": len(done_steps),
            "analysis_objective":   structured.analysis_objective,
            "selected_agents":      list(dict.fromkeys(selected)),
        })
        base["reasoning"] = [{"step_name": "Planner", "step_text": structured.reasoning}]
        logger.info("Planner: %d tasks (%d done + %d new), objective=%r",
                    len(all_tasks), len(done_steps), len(new_tasks),
                    structured.analysis_objective[:80])
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # DATA ANALYST
    # ══════════════════════════════════════════════════════════════════════════

    async def data_analyst_node(state: AnalyticsState) -> dict[str, Any]:
        """Loads the dataset, applies filters, buckets themes, and confirms dimensions.

        Reads:
            messages               - user's filter specification
            dataset_path           - CSV path from config
            dataset_schema         - available column names / values (injected into prompt)
            analysis_objective     - context for bucket labelling

        Writes:
            filters_applied        - dict of column->value filters that were applied
            themes_for_analysis    - list of bucket/theme names discovered
            data_buckets           - per-bucket row counts and sample rows
            dataset_schema         - populated from load_dataset if not already set
            analysis_scope_reply   - user's dimension confirmation
            messages               - single clean summary (tool noise replaced)

        Tools: load_dataset, filter_data, bucket_data, describe_filters
        """
        ctx = _build_extra_context("data_analyst", state, None)
        base, last_msg = await _run_react_node("data_analyst", agent_factory, ctx, state)

        # Scan all tool-result messages and promote key values to state fields
        _extract_data_analyst_state(state, base)

        # Replace raw tool messages with a single clean user-facing summary
        da_data = _parse_json(_text(last_msg.content)) if last_msg else {}
        summary = da_data.get("response", _text(last_msg.content) if last_msg else "")
        if not isinstance(summary, str):
            summary = json.dumps(summary, indent=2, default=str)

        base["reasoning"] = [{"step_name": "Data Analyst", "step_text": summary}]
        # Keep the full summary in reasoning only (collapsible in UI).
        # The user-facing message and interrupt use a concise version.
        if summary:
            base["messages"] = [AIMessage(content=summary)]

        # After bucketing, interrupt for dimension confirmation
        has_buckets = base.get("data_buckets") or state.get("data_buckets")
        already_confirmed = state.get("analysis_scope_reply")
        if has_buckets and not already_confirmed:
            # Build a concise bucket summary (names + row counts only)
            buckets = base.get("data_buckets") or state.get("data_buckets") or {}
            filters = base.get("filters_applied") or state.get("filters_applied") or {}
            filter_desc = " and ".join(f"{k}={v}" for k, v in filters.items()) if filters else "all data"
            bucket_lines = []
            total_rows = 0
            for binfo in buckets.values():
                if isinstance(binfo, dict):
                    bname = binfo.get("bucket_name", "?")
                    bcount = binfo.get("row_count", 0)
                    total_rows += bcount
                    bucket_lines.append(f"- **{bname}** ({bcount} rows)")
            concise_summary = (
                f"Filtered to **{total_rows} rows** on {filter_desc}. "
                f"Created **{len(bucket_lines)} buckets**:\n"
                + "\n".join(bucket_lines)
            )
            user_reply = interrupt({
                "type": "analysis_dimension_confirmation",
                "message": (
                    f"{concise_summary}\n\n"
                    "Before starting multi-lens friction analysis, please confirm "
                    "which dimensions to analyse:\n"
                    "\u2022 **Digital Friction** \u2014 app failures, self-service gaps, web/UX issues\n"
                    "\u2022 **Operations** \u2014 process breakdowns, SLA breaches, handoff failures\n"
                    "\u2022 **Communication** \u2014 notification gaps, expectation mismatches\n"
                    "\u2022 **Policy** \u2014 regulatory constraints, fee disputes, compliance issues"
                ),
                "prompt": (
                    "Reply **run all lenses** to analyse all dimensions, "
                    "or specify which ones (e.g. 'digital and operations')."
                ),
            })
            reply_text = str(user_reply).strip()
            logger.info("data_analyst: dimension confirmation reply %r", reply_text[:120])

            # Guard: check if the reply is actually a lens selection vs. an
            # unrelated message (e.g. user correcting filters while data_analyst
            # was still running). Lens-related replies mention lens keywords or
            # are simple confirmations like "all", "yes", "run all".
            _LENS_KEYWORDS = {
                "all", "digital", "operations", "communication", "policy",
                "run all", "run all lenses", "yes", "go ahead", "proceed",
            }
            reply_lower = reply_text.lower()
            is_lens_reply = any(kw in reply_lower for kw in _LENS_KEYWORDS)

            if is_lens_reply:
                base["analysis_scope_reply"] = reply_text
                base["next_agent"] = "planner"
            else:
                # Not a lens selection — likely a filter correction or other
                # user intent. Route back to supervisor to handle it properly.
                logger.info("data_analyst: reply doesn't match lens selection, routing to supervisor")
                base["next_agent"] = "supervisor"

        _advance_plan("data_analyst", state, base)
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # FRICTION LENS AGENTS  (4 agents, run in parallel inside friction_analysis)
    # ══════════════════════════════════════════════════════════════════════════

    def _lens_md_base(agent_id: str, state: dict) -> str:
        """Return versioned-md base name: '{agent_id}_{bucket}' or just '{agent_id}'."""
        fb = state.get("_focus_bucket", "")
        return f"{agent_id}_{fb}" if fb else agent_id


    async def digital_friction_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies digital/UX friction: app failures, self-service gaps, web issues.

        Reads:  messages, data_buckets, _focus_bucket (optional), skill_loader
        Writes: digital_analysis, friction_md_paths
        Tools:  analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("digital_friction_agent", state, skill_loader)
        base, last_msg = await _run_react_node("digital_friction_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        output_field = _agent_output_field("digital_friction_agent", base["messages"], summary)
        base["digital_analysis"] = output_field
        base["reasoning"] = [{"step_name": "Digital Friction Agent", "step_text": summary}]
        md_path = _write_versioned_md(
            _lens_md_base("digital_friction_agent", state),
            output_field.get("full_response", "") or summary,
            {"agent": "digital_friction_agent", "bucket": state.get("_focus_bucket", "all")},
        )
        if md_path:
            base["friction_md_paths"] = {"digital_friction_agent": md_path}
        return base

    async def operations_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies operational friction: process breakdowns, SLA breaches, handoff failures.

        Reads:  messages, data_buckets, _focus_bucket (optional), skill_loader
        Writes: operations_analysis, friction_md_paths
        Tools:  analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("operations_agent", state, skill_loader)
        base, last_msg = await _run_react_node("operations_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        output_field = _agent_output_field("operations_agent", base["messages"], summary)
        base["operations_analysis"] = output_field
        base["reasoning"] = [{"step_name": "Operations Agent", "step_text": summary}]
        md_path = _write_versioned_md(
            _lens_md_base("operations_agent", state),
            output_field.get("full_response", "") or summary,
            {"agent": "operations_agent", "bucket": state.get("_focus_bucket", "all")},
        )
        if md_path:
            base["friction_md_paths"] = {"operations_agent": md_path}
        return base

    async def communication_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies communication friction: notification gaps, expectation mismatches.

        Reads:  messages, data_buckets, _focus_bucket (optional), skill_loader
        Writes: communication_analysis, friction_md_paths
        Tools:  analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("communication_agent", state, skill_loader)
        base, last_msg = await _run_react_node("communication_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        output_field = _agent_output_field("communication_agent", base["messages"], summary)
        base["communication_analysis"] = output_field
        base["reasoning"] = [{"step_name": "Communication Agent", "step_text": summary}]
        md_path = _write_versioned_md(
            _lens_md_base("communication_agent", state),
            output_field.get("full_response", "") or summary,
            {"agent": "communication_agent", "bucket": state.get("_focus_bucket", "all")},
        )
        if md_path:
            base["friction_md_paths"] = {"communication_agent": md_path}
        return base

    async def policy_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies policy friction: regulatory constraints, fee disputes, compliance issues.

        Reads:  messages, data_buckets, _focus_bucket (optional), skill_loader
        Writes: policy_analysis, friction_md_paths
        Tools:  analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("policy_agent", state, skill_loader)
        base, last_msg = await _run_react_node("policy_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        output_field = _agent_output_field("policy_agent", base["messages"], summary)
        base["policy_analysis"] = output_field
        base["reasoning"] = [{"step_name": "Policy Agent", "step_text": summary}]
        md_path = _write_versioned_md(
            _lens_md_base("policy_agent", state),
            output_field.get("full_response", "") or summary,
            {"agent": "policy_agent", "bucket": state.get("_focus_bucket", "all")},
        )
        if md_path:
            base["friction_md_paths"] = {"policy_agent": md_path}
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # SYNTHESIZER
    # ══════════════════════════════════════════════════════════════════════════

    async def synthesizer_node(state: AnalyticsState) -> dict[str, Any]:
        """Aggregates the 4 lens outputs into cross-cutting themes and ranked findings.

        Reads:
            messages                – conversation + friction agent outputs
            digital_analysis        – from digital_friction_node
            operations_analysis     – from operations_node
            communication_analysis  – from communication_node
            policy_analysis         – from policy_node
            friction_output_files   – DataStore keys for full lens text (preferred over state dict)
            selected_agents       – which friction lenses ran

        Writes:
            synthesis_result        – full synthesis dict:
                                       executive_narrative, themes[], findings[],
                                       dominant_drivers, overall_preventability,
                                       decision ("complete" | "incomplete"), confidence
            findings                – flat list for downstream reporting agents
            messages                – executive_narrative summary (user-visible)
        """
        ctx = _build_extra_context("synthesizer_agent", state, None)
        sys_prompt = agent_factory.parse_agent_md("synthesizer_agent").system_prompt + ctx

        # Note: ctx is already embedded in sys_prompt — pass empty extra_context
        # to avoid double-counting in the LLM input signature log.
        base, structured, last_msg = await _run_structured_node(
            "synthesizer_agent", synthesizer_chain, SynthesizerOutput, sys_prompt, state,
        )

        if isinstance(structured, SynthesizerOutput):
            narrative      = structured.summary.executive_narrative
            synthesis_data = structured.summary.model_dump()
            synthesis_data.update({
                "decision":   structured.decision,
                "confidence": structured.confidence,
                "reasoning":  structured.reasoning,
            })
            if structured.themes:
                synthesis_data["themes"]   = [t.model_dump() for t in structured.themes]
            if structured.findings:
                synthesis_data["findings"] = [f.model_dump() for f in structured.findings]

            top_theme_names = [t.theme for t in structured.themes[:5]] if structured.themes else []

            base.update({
                "synthesis_result":  synthesis_data,
                "findings":          [f.model_dump() for f in structured.findings],
                "top_themes":        top_theme_names,
            })
            base["reasoning"] = [{"step_name": "Synthesizer Agent", "step_text": narrative}]
            if narrative:
                base["messages"] = [AIMessage(content=narrative)]

            # Write versioned synthesis markdown to cache — path is completion flag.
            synthesis_md = json.dumps(synthesis_data, indent=2, default=str)
            synthesis_path = _write_versioned_md(
                "synthesis", synthesis_md, {"agent": "synthesizer_agent"}
            )
            if synthesis_path:
                base["synthesis_path"] = synthesis_path

            logger.info("Synthesizer: %d findings, %d themes, confidence=%d, synthesis_path=%s",
                        len(structured.findings), len(structured.themes), structured.confidence,
                        synthesis_path or "not written")

        elif last_msg:
            # Fallback: parse JSON directly from last AI message
            data          = _parse_json(_text(last_msg.content))
            synthesis_data: dict[str, Any] = {}
            if data.get("summary"):
                synthesis_data = dict(data["summary"])
            for key in ("decision", "confidence", "reasoning"):
                if key in data:
                    synthesis_data[key] = data[key]
            if data.get("themes"):
                synthesis_data["themes"]   = data["themes"]
            if data.get("findings"):
                synthesis_data["findings"] = data["findings"]
                base["findings"]           = data["findings"]
            if synthesis_data:
                base["synthesis_result"] = synthesis_data

            raw_text = _text(last_msg.content)
            narrative = (synthesis_data.get("executive_narrative")
                         or (raw_text if not raw_text.startswith("{") else "Synthesis complete."))
            base["reasoning"] = [{"step_name": "Synthesizer Agent", "step_text": narrative}]
            if narrative:
                base["messages"] = [AIMessage(content=narrative)]
            logger.info("Synthesizer (fallback): %d findings, %d themes",
                        len(data.get("findings", [])), len(data.get("themes", [])))

        return base

    # ══════════════════════════════════════════════════════════════════════════
    # NARRATIVE AGENT
    # ══════════════════════════════════════════════════════════════════════════

    async def narrative_node(state: AnalyticsState) -> dict[str, Any]:
        """Writes the analytical narrative: exec summary, impact/ease matrix, recommendations, theme dives.

        Reads:
            messages               – includes synthesizer executive narrative
            synthesis_result       – themes[], findings[], executive_narrative, scores
            synthesis_output_file  – DataStore key to reload full synthesis if needed
            findings               – flat finding list
            filters_applied        – shown in report header
            report_retry_context   – retry instructions if this is a second attempt

        Writes:
            narrative_output       – {output, full_response, agent}
                                     full_response is the complete markdown text with slide tags

        Tools: get_findings_summary
        """
        ctx = _build_extra_context("narrative_agent", state, None)
        base, last_msg = await _run_react_node("narrative_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        output_field = _agent_output_field("narrative_agent", base["messages"], summary)
        base["narrative_output"] = output_field
        base["reasoning"] = [{"step_name": "Narrative Agent", "step_text": summary}]

        # Write versioned narrative markdown to cache — path is completion flag.
        # Critique creates narrative_v2.md by re-running with revision instructions.
        full_narrative = output_field.get("full_response", "") or summary
        narrative_path = _write_versioned_md(
            "narrative", full_narrative, {"agent": "narrative_agent"}
        )
        if narrative_path:
            base["narrative_path"] = narrative_path
        logger.info("Narrative: written to %s", narrative_path or "not written")
        return base


    # ══════════════════════════════════════════════════════════════════════════
    # REPORT ANALYST
    # ══════════════════════════════════════════════════════════════════════════

    async def report_analyst_node(state: AnalyticsState) -> dict[str, Any]:
        """Delivers the final report: verifies artifacts exist, presents download links.

        Reads:
            messages               – "deliver report" instruction from supervisor
            synthesis_result       – summary metrics for delivery message
            findings               – top findings for summary
            report_file_path       – PPTX path (already written by artifact_writer)
            markdown_file_path     – .md path
            data_file_path         – CSV path
            filters_applied        – shown in delivery context

        Writes:
            report_file_path       – updated if agent re-generates a missing artifact
            markdown_file_path     – updated if agent re-generates
            data_file_path         – updated if agent re-generates
            messages               – final user-visible delivery message

        Tools: generate_markdown_report, export_to_pptx, export_filtered_csv
        """
        ctx = _build_extra_context("report_analyst", state, None)
        base, last_msg = await _run_react_node("report_analyst", agent_factory, ctx, state)

        # If the agent called any export tools, extract the artifact paths from tool results
        _extract_formatting_state(state, base)

        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        base["reasoning"] = [{"step_name": "Report Analyst", "step_text": summary}]
        _advance_plan("report_analyst", state, base)
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # CRITIQUE
    # ══════════════════════════════════════════════════════════════════════════

    async def critique_node(state: AnalyticsState) -> dict[str, Any]:
        """QA validation: grades synthesis quality, flags gaps, requests revisions.

        Reads:
            messages               – synthesis + findings for grading
            synthesis_result       – full synthesis to evaluate
            findings               – flat finding list

        Writes:
            critique_feedback      – full critique dict (grade, issues, recommendations)
            quality_score          – float 0-1
            messages               – "Grade: X | Score: Y | Decision: Z" summary

        Tools: validate_findings, score_quality
        """
        # Build proper context for critique (synthesis + findings)
        ctx = _build_extra_context("critique", state, None)
        critique_state = dict(state)
        critique_state["messages"] = [HumanMessage(content="Grade the analysis quality.")]
        base, last_msg = await _run_react_node("critique", agent_factory, ctx, critique_state)

        data          = _parse_json(_text(last_msg.content)) if last_msg else {}
        quality_score = float(data.get("quality_score", data.get("overall_quality_score", 0.0)))
        grade         = data.get("grade", "C")
        decision      = data.get("decision", "needs_revision")
        summary_text  = data.get("summary", _text(last_msg.content) if last_msg else "")
        text          = f"Grade: {grade} | Score: {quality_score:.2f} | Decision: {decision}\n{summary_text}"

        base.update({
            "critique_feedback": data,
            "quality_score":     quality_score,
            "reasoning":         [{"step_name": "Critique Agent", "step_text": text}],
            "messages":          [AIMessage(content=text)],
        })
        return base

    # ══════════════════════════════════════════════════════════════════════════════
    # QNA AGENT
    # ══════════════════════════════════════════════════════════════════════════════

    async def qna_node(state: AnalyticsState) -> dict[str, Any]:
        """Answers user follow-up questions using the generated markdown report.

        Reads:
            messages               – user’s question
            markdown_file_path     – path to the analysis report (.md)

        Writes:
            messages               – answer to the user’s question
        """
        ctx = _build_extra_context("qna_agent", state, None)
        base, last_msg = await _run_react_node("qna_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        base["reasoning"] = [{"step_name": "QnA Agent", "step_text": summary}]
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # COMPOSITE NODE: friction_analysis
    # Runs the 4 lens agents in parallel (asyncio.gather), then synthesizer.
    # Respects selected_agents from state for dimension selection.
    # ══════════════════════════════════════════════════════════════════════════

    _ALL_LENS_IDS = [
        "digital_friction_agent", "operations_agent",
        "communication_agent",    "policy_agent",
    ]
    _LENS_NODE_MAP = {
        "digital_friction_agent": digital_friction_node,
        "operations_agent":       operations_node,
        "communication_agent":    communication_node,
        "policy_agent":           policy_node,
    }

    async def friction_analysis_node(state: AnalyticsState) -> dict[str, Any]:
        """Run each lens agent once per bucket in parallel, then two-pass synthesis.

        Phase 0: Run (lens × bucket) combinations in parallel via asyncio.gather.
                 e.g. 4 lenses × 6 buckets = 24 parallel ReAct runs.
                 UI shows live ``(completed/total)`` per lens.
        Phase 1: Per-lens aggregation — concatenate all bucket outputs per lens
                 into ``lens_synthesis_{lens_id}.md`` (no LLM, structural merge).
                 Synthesizer row shows ``Per-lens aggregation (n/4)``.
        Phase 2: Final synthesis — synthesizer reads 4 per-lens markdowns and
                 produces the executive synthesis, themes, and ranked findings.
                 Synthesizer row shows ``Final cross-lens synthesis``.

        Reads:  selected_agents, data_buckets
        Writes: friction_md_paths (nested), lens_synthesis_paths,
                synthesis_result, findings,
                plan_steps_completed
        """
        from pathlib import Path as _Path

        selected = state.get("selected_agents", [])
        lens_ids = [a for a in selected if a in _ALL_LENS_IDS] if selected else list(_ALL_LENS_IDS)
        if not lens_ids:
            lens_ids = list(_ALL_LENS_IDS)
        lens_ids = list(dict.fromkeys(lens_ids))

        # Bucket keys from data_analyst output
        raw_buckets = state.get("data_buckets", {})
        bucket_keys = list(raw_buckets.keys()) if raw_buckets else ["all"]
        total_buckets = len(bucket_keys)

        total_runs = len(lens_ids) * total_buckets
        per_agent_limit = MAX_MULTITHREADING_WORKERS // len(lens_ids)
        per_agent_limit = max(per_agent_limit, 1)  # at least 1
        semaphore = asyncio.Semaphore(MAX_MULTITHREADING_WORKERS)
        logger.info(
            "Friction analysis: %d lenses × %d buckets = %d runs "
            "(max %d workers, %d per agent)",
            len(lens_ids), total_buckets, total_runs,
            MAX_MULTITHREADING_WORKERS, per_agent_limit,
        )

        # Per-agent semaphores to enforce floor(MAX_WORKERS / num_agents) limit
        agent_semaphores: dict[str, asyncio.Semaphore] = {
            lid: asyncio.Semaphore(per_agent_limit) for lid in lens_ids
        }

        # Build sub_agents with (0/N) progress counters
        sub_agents: list[dict[str, Any]] = []
        for lid in lens_ids:
            meta = FRICTION_SUB_AGENTS[lid]
            sub_agents.append({
                "id": lid,
                "title": meta["title"],
                "detail": f"{meta['detail']} (0/{total_buckets})",
                "status": "in_progress",
            })
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []), agent_name="friction_analysis",
            sub_agents=sub_agents, task_status="in_progress",
        )

        # ── Phase 0: run (lens × bucket) in parallel with live progress ──
        completed_per_lens: dict[str, int] = {lid: 0 for lid in lens_ids}

        async def _tracked_run(lens_id: str, bucket_key: str, coro):
            """Wrap a lens coroutine with concurrency limiting + UI progress."""
            async with semaphore:
                async with agent_semaphores[lens_id]:
                    result = await coro
            completed_per_lens[lens_id] += 1
            done = completed_per_lens[lens_id]
            base_detail = FRICTION_SUB_AGENTS[lens_id]["detail"]
            new_status = "done" if done == total_buckets else "in_progress"
            _set_sub_agent_status(
                sub_agents, lens_id, status=new_status,
                detail=f"{base_detail} ({done}/{total_buckets})",
            )
            nonlocal tasks
            tasks = await _set_task_sub_agents_and_emit(
                tasks, agent_name="friction_analysis",
                sub_agents=sub_agents, task_status="in_progress",
            )
            return result

        run_tasks = []
        run_combos: list[tuple[str, str]] = []
        for lens_id in lens_ids:
            for bucket_key in bucket_keys:
                focused_state = dict(state)
                # Clear cumulative traces so each run produces ONLY its own
                # new trace entry. _merge_parallel_outputs will collect them.
                focused_state["execution_trace"] = []
                focused_state["_focus_bucket"] = bucket_key
                # Single targeted message — bucket data is already in extra_context
                bucket_name = raw_buckets.get(bucket_key, {}).get("bucket_name", bucket_key) if isinstance(raw_buckets.get(bucket_key), dict) else bucket_key
                focused_state["messages"] = [HumanMessage(content=(
                    f"Analyze bucket '{bucket_name}' for friction drivers. "
                    f"Analysis objective: {state.get('analysis_objective', 'Identify friction drivers')}"
                ))]
                coro = _LENS_NODE_MAP[lens_id](focused_state)
                run_tasks.append(_tracked_run(lens_id, bucket_key, coro))
                run_combos.append((lens_id, bucket_key))

        results = await asyncio.gather(*run_tasks)

        # Assemble nested friction_md_paths: {agent_id: {bucket_key: md_path}}
        nested_md_paths: dict[str, dict[str, str]] = {lid: {} for lid in lens_ids}
        for (lens_id, bucket_key), result in zip(run_combos, results):
            flat_paths = result.get("friction_md_paths", {})
            nested_md_paths[lens_id][bucket_key] = flat_paths.get(lens_id, "")

        merged = _merge_parallel_outputs(list(results))
        merged["friction_md_paths"]        = nested_md_paths

        logger.info("  Merged %d friction outputs: lenses=%s, buckets=%s",
                    total_runs, lens_ids, bucket_keys)

        # ── Phase 1: per-lens aggregation with synthesizer progress ──
        # If total raw output exceeds SUMMARIZE_THRESHOLD_CHARS, extract
        # structured per-bucket summaries (key issues, call volume, solutions
        # by team) instead of raw concatenation.  This keeps the synthesizer
        # context manageable at scale (e.g. 50 buckets × 4 lenses).
        use_summarization = _should_summarize_lens_outputs(nested_md_paths)
        phase1_label = "Per-lens summarization" if use_summarization else "Per-lens aggregation"
        logger.info("  Phase 1: %s (summarize=%s)", phase1_label, use_summarization)

        sub_agents.append({
            "id": "synthesizer_agent",
            "title": FRICTION_SUB_AGENTS["synthesizer_agent"]["title"],
            "detail": f"{phase1_label} (0/{len(lens_ids)})",
            "status": "in_progress",
        })
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="friction_analysis",
            sub_agents=sub_agents, task_status="in_progress",
        )

        lens_synthesis_paths: dict[str, str] = {}
        for i, lid in enumerate(lens_ids):
            bucket_path_dict = nested_md_paths[lid]
            num_buckets = len(bucket_path_dict)

            if use_summarization and num_buckets > L2_BATCH_SIZE:
                # >10 buckets: intermediate LLM grouping (batch ~10 buckets,
                # LLM per batch to consolidate, then assemble)
                lens_md = await _summarize_lens_buckets_with_llm(lid, bucket_path_dict, raw_buckets)
            elif use_summarization:
                # ≤10 buckets: direct tiered extraction (no LLM, text-only)
                lens_md = _summarize_lens_buckets(lid, bucket_path_dict, raw_buckets)
            else:
                # Raw concatenation (small context — no summarization needed)
                parts = [f"# {lid} — Per-Bucket Analysis\n"]
                for bk in sorted(bucket_path_dict.keys()):
                    bpath = bucket_path_dict[bk]
                    if bpath and _Path(bpath).exists():
                        content = _Path(bpath).read_text(encoding="utf-8")
                        bucket_name = raw_buckets.get(bk, {}).get("bucket_name", bk) if isinstance(raw_buckets.get(bk), dict) else bk
                        parts.append(f"\n## Bucket: {bucket_name}\n{content}")
                    else:
                        parts.append(f"\n## Bucket: {bk}\n(No output)\n")
                lens_md = "\n".join(parts)

            lens_path = _write_versioned_md(
                f"lens_synthesis_{lid}", lens_md,
                {"lens": lid, "bucket_count": num_buckets,
                 "summarized": use_summarization,
                 "intermediate_llm": use_summarization and num_buckets > L2_BATCH_SIZE},
            )
            if lens_path:
                lens_synthesis_paths[lid] = lens_path

            _set_sub_agent_status(
                sub_agents, "synthesizer_agent", status="in_progress",
                detail=f"{phase1_label} ({i + 1}/{len(lens_ids)})",
            )
            tasks = await _set_task_sub_agents_and_emit(
                tasks, agent_name="friction_analysis",
                sub_agents=sub_agents, task_status="in_progress",
            )

        merged["lens_synthesis_paths"] = lens_synthesis_paths
        logger.info("  Phase 1 done: %d per-lens synthesis files written (summarized=%s)",
                     len(lens_synthesis_paths), use_summarization)

        # ── Phase 2: final synthesis (single LLM call) ──
        _set_sub_agent_status(
            sub_agents, "synthesizer_agent", status="in_progress",
            detail="Final cross-lens synthesis",
        )
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="friction_analysis",
            sub_agents=sub_agents, task_status="in_progress",
        )

        synth_state = dict(state)
        for k, v in merged.items():
            if k != "messages":
                synth_state[k] = v
        # Clear cumulative traces so synthesizer produces only its own entry
        synth_state["execution_trace"] = []
        # Single targeted message — lens data is already in extra_context
        synth_state["messages"] = [HumanMessage(content=(
            "Synthesize the friction lens analyses into themes. "
            "Produce executive narrative, ranked findings, and impact×ease scores. "
            f"Analysis objective: {state.get('analysis_objective', 'Identify friction drivers')}"
        ))]
        synth_state["lens_synthesis_paths"]  = lens_synthesis_paths
        synth_state["friction_md_paths"]     = nested_md_paths

        logger.info("Friction analysis: running synthesizer (Phase 2) | %d lens files",
                    len(lens_synthesis_paths))
        synth_result = await synthesizer_node(synth_state)

        # Tag synthesis with completeness decision
        missing_lenses = [lid for lid in lens_ids if lid not in lens_synthesis_paths]
        synthesis_payload = synth_result.get("synthesis_result", {})
        if isinstance(synthesis_payload, dict):
            synthesis_payload = dict(synthesis_payload)
            synthesis_payload["decision"] = "complete" if not missing_lenses else "incomplete"
            synth_result["synthesis_result"] = synthesis_payload

        # Offload synthesis_result to DataStore to avoid state bloat
        import chainlit as cl
        data_store = cl.user_session.get("data_store")
        if data_store and synth_result.get("synthesis_result"):
            content = json.dumps(synth_result["synthesis_result"])
            key = data_store.store_text(
                "synthesis_output", content,
                {"agent": "synthesizer_agent", "type": "synthesis_output"},
            )
            synth_result["synthesis_output_file"] = key
            logger.info("Friction analysis: stored synthesis_result in DataStore as %s", key)

        logger.info("Friction analysis: synthesizer done | findings=%d msgs=%d",
                    len(synth_result.get("findings", [])),
                    len(synth_result.get("messages", [])))

        # Final UI: mark synthesizer done
        _set_sub_agent_status(
            sub_agents, "synthesizer_agent", status="done",
            detail="Cross-lens synthesis complete",
        )
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="friction_analysis", sub_agents=sub_agents, task_status="done",
        )

        final = _merge_state_deltas(
            merged, synth_result,
            list_keys={"execution_trace"},
            skip_keys={"messages"},
        )
        final["reasoning"]   = _build_friction_reasoning_entries(lens_ids, state, synth_result)
        final["messages"]    = synth_result.get("messages", [])
        final["plan_tasks"]  = tasks

        _record_plan_progress(state, final, agent_name="friction_analysis")
        return final

    # ══════════════════════════════════════════════════════════════════════════
    # REPORT DRAFTS  (narrative agent + fixed deck blueprint)
    # ══════════════════════════════════════════════════════════════════════════

    async def report_drafts_node(state: AnalyticsState) -> dict[str, Any]:
        """Narrative agent + deterministic deck blueprint (no artifact writing).

        Reads:
            synthesis_result       - themes + findings for narrative + deck
            synthesis_output_file  - DataStore key (preferred over state dict)
            findings               - flat finding list
            filters_applied        - report header

        Writes:
            narrative_output       - markdown narrative
            formatting_output      - slide blueprint JSON
            plan_steps_completed   - incremented
        """
        logger.info("Report drafts: starting narrative -> fixed deck blueprint")
        expected = [a for a in state.get("selected_agents", []) if a in _ALL_LENS_IDS]
        if not expected:
            expected = list(_ALL_LENS_IDS)
        expected = list(dict.fromkeys([a for a in expected if a]))
        available_lenses = list((state.get("lens_synthesis_paths", {}) or {}).keys())
        if not available_lenses:
            available_lenses = list((state.get("friction_output_files", {}) or {}).keys())
        missing = [a for a in expected if a not in available_lenses]
        missing = list(dict.fromkeys([a for a in missing if a]))
        if missing:
            raise RuntimeError(
                "Report drafts blocked: required friction lenses are missing outputs. "
                f"Missing: {missing}. Run complete friction analysis before generating report drafts."
            )

        sub_agents = [
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "narrative_agent",  status="in_progress"),
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "formatting_agent", status="ready"),
        ]
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []), agent_name="report_drafts",
            sub_agents=sub_agents, task_status="in_progress",
        )

        # --- Step 1: Narrative agent (ReAct) ---
        narrative_state = dict(state)
        # Clear cumulative traces so narrative produces only its own entry
        narrative_state["execution_trace"] = []
        narrative_state["messages"] = [HumanMessage(content=(
            "Generate the narrative markdown now with explicit slide boundary tags. "
            "You must call get_findings_summary before finalizing."
        ))]
        narrative_result = await _run_agent_with_retries(
            agent_id="narrative_agent", node_fn=narrative_node,
            base_state=narrative_state, required_tools=["get_findings_summary"],
            validator=_validate_narrative,
        )

        _set_sub_agent_status(sub_agents, "narrative_agent",  status="done")
        _set_sub_agent_status(sub_agents, "formatting_agent", status="in_progress")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="report_drafts", sub_agents=sub_agents, task_status="in_progress",
        )

        # --- Step 2: Fixed deck blueprint (deterministic) ---
        synthesis = state.get("synthesis_result", {})
        if not synthesis and state.get("synthesis_output_file"):
            import chainlit as cl
            data_store = cl.user_session.get("data_store")
            if data_store:
                loaded = data_store.get_text(state["synthesis_output_file"])
                if loaded:
                    synthesis = json.loads(loaded)

        section_blueprints = _build_fixed_deck_blueprint(
            synthesis,
            state.get("findings", []),
        )
        total_slides = sum(len(s.get("slides", [])) for s in section_blueprints)
        logger.info(
            "Report drafts: fixed deck blueprint built | %d slides across %d sections",
            total_slides, len(section_blueprints),
        )

        _set_sub_agent_status(sub_agents, "formatting_agent", status="done",
                              detail=f"Fixed deck: {total_slides} slides")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="report_drafts", sub_agents=sub_agents, task_status="done",
        )

        # Build final state delta (no artifacts yet)
        fmt_summary = {
            "formatting_output": {
                "output": f"{total_slides} slides across {len(section_blueprints)} sections",
                "full_response": json.dumps(section_blueprints, indent=2, default=str),
                "agent": "formatting_agent",
            },
        }
        final = _merge_state_deltas(
            narrative_result, fmt_summary,
            list_keys={"execution_trace"},
            skip_keys={"messages"},
        )
        final["reasoning"]  = _build_report_reasoning_entries()
        final["messages"]   = [AIMessage(content=_build_executive_summary_message(final.get("narrative_output", {})))]
        final["plan_tasks"] = tasks

        _record_plan_progress(state, final, agent_name="report_drafts")
        return final

    # ══════════════════════════════════════════════════════════════════════════
    # ARTIFACT WRITER  (charts + PPTX + CSV + markdown)
    # ══════════════════════════════════════════════════════════════════════════

    async def artifact_writer_node(state: AnalyticsState) -> dict[str, Any]:
        """Generates report artifacts: charts, PPTX, CSV, markdown files.

        Reads:
            narrative_output       - markdown narrative from report_drafts
            formatting_output      - slide blueprint JSON from report_drafts
            synthesis_result       - themes + findings
            findings               - flat finding list
            filters_applied        - for CSV export

        Writes:
            report_file_path       - PPTX path on disk
            docx_file_path         - Word (.docx) path on disk
            markdown_file_path     - .md path on disk
            data_file_path         - CSV path on disk
            analysis_complete      - True (pipeline done)
        """
        logger.info("Artifact writer: generating charts, PPTX, CSV, markdown")

        # Reconstruct section_blueprints from formatting_output
        fmt_output = state.get("formatting_output", {})
        section_blueprints = []
        if isinstance(fmt_output, dict):
            raw = fmt_output.get("full_response", "")
            if raw:
                try:
                    section_blueprints = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    pass

        narrative_result = {"narrative_output": state.get("narrative_output", {})}

        sub_agents = [
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "artifact_writer_node", status="in_progress"),
        ]
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []), agent_name="artifact_writer",
            sub_agents=sub_agents, task_status="in_progress",
        )

        artifact_result = _run_section_artifact_writer(state, narrative_result, section_blueprints)
        artifact_errors = _validate_artifact_paths(artifact_result)
        if artifact_errors:
            raise RuntimeError(f"artifact_writer failed validation: {artifact_errors}")
        logger.info(
            "Artifact writer: created | report=%r docx=%r markdown=%r data=%r",
            artifact_result.get("report_file_path", ""),
            artifact_result.get("docx_file_path", ""),
            artifact_result.get("markdown_file_path", ""),
            artifact_result.get("data_file_path", ""),
        )

        _set_sub_agent_status(sub_agents, "artifact_writer_node", status="done",
                              detail="Created PPTX, Word, CSV and markdown files.")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="artifact_writer", sub_agents=sub_agents, task_status="done",
        )

        final = dict(artifact_result)
        final["plan_tasks"] = tasks
        final["reasoning"] = [{"step_name": "Artifact Writer", "step_text": "Report artifacts generated."}]

        _record_plan_progress(state, final, agent_name="artifact_writer", mark_analysis_complete=True)
        return final

    # ══════════════════════════════════════════════════════════════════════════
    # PLAN DISPATCHER (deterministic — no LLM call)
    # Replaces the planner→supervisor ping-pong mid-pipeline.
    # Reads plan_tasks, marks current task done, picks next ready task.
    # ══════════════════════════════════════════════════════════════════════════

    async def plan_dispatcher_node(state: AnalyticsState) -> dict[str, Any]:
        """Deterministic plan execution: advance plan and route to next work node.

        No LLM call.  Reads plan_tasks, marks the most recent in_progress task
        as done, promotes the next ready/todo task to in_progress, and sets
        next_agent for the conditional edge.

        Also handles OPT-5: if the next task is report_analyst and all artifact
        paths are already valid, skip it and mark analysis complete.

        Reads:  plan_tasks, report_file_path, data_file_path, markdown_file_path
        Writes: plan_tasks, plan_steps_completed, plan_steps_total, next_agent,
                analysis_complete, phase
        """
        tasks = [dict(t) for t in state.get("plan_tasks", [])]

        # Respect explicit routing override from upstream node (e.g. data_analyst
        # setting next_agent="supervisor" for non-lens replies).
        upstream_next = state.get("next_agent", "")
        if upstream_next in ("supervisor", "planner") and not tasks:
            logger.info("Plan dispatcher: upstream override next=%s (no plan)", upstream_next)
            return {
                "plan_tasks": [],
                "plan_steps_completed": 0,
                "plan_steps_total": 0,
                "next_agent": upstream_next,
            }

        # If no plan exists yet (e.g. data_analyst completed before planner ran),
        # route to planner for initial plan creation.
        if not tasks:
            logger.info("Plan dispatcher: no plan yet, routing to planner")
            return {
                "plan_tasks": [],
                "plan_steps_completed": 0,
                "plan_steps_total": 0,
                "next_agent": "planner",
            }

        # Mark the in_progress task as done
        for t in tasks:
            if t.get("status") == "in_progress":
                t["status"] = "done"
                break

        # Find next ready/todo task
        next_agent = "__end__"
        for t in tasks:
            if t.get("status") in ("ready", "todo"):
                t["status"] = "in_progress"
                next_agent = t.get("agent", "__end__")
                break

        done_count = len([t for t in tasks if t.get("status") == "done"])
        total = len(tasks)

        result: dict[str, Any] = {
            "plan_tasks": tasks,
            "plan_steps_completed": done_count,
            "plan_steps_total": total,
            "next_agent": next_agent,
        }

        # OPT-5: Skip report_analyst if all artifacts are already valid
        if next_agent == "report_analyst":
            artifact_errors = _validate_artifact_paths({
                "report_file_path": state.get("report_file_path", ""),
                "data_file_path": state.get("data_file_path", ""),
                "markdown_file_path": state.get("markdown_file_path", ""),
            })
            if not artifact_errors:
                # All artifacts exist — skip report_analyst, mark it done
                for t in tasks:
                    if t.get("agent") == "report_analyst" and t.get("status") == "in_progress":
                        t["status"] = "done"
                        break
                done_count = len([t for t in tasks if t.get("status") == "done"])
                result["plan_tasks"] = tasks
                result["plan_steps_completed"] = done_count
                result["analysis_complete"] = True
                result["phase"] = "qa"
                next_agent = "__end__"
                result["next_agent"] = next_agent
                logger.info("Plan dispatcher: skipped report_analyst (all artifacts valid)")

        # Check if plan is fully complete
        if total > 0 and done_count >= total and not result.get("analysis_complete"):
            result["analysis_complete"] = True
            result["phase"] = "qa"

        logger.info("Plan dispatcher: %d/%d done, next=%s", done_count, total, next_agent)
        return result

    # ------------------------------------------------------------------
    # Graph wiring
    # ------------------------------------------------------------------

    graph = StateGraph(AnalyticsState)

    graph.add_node("supervisor",        supervisor_node)
    graph.add_node("planner",           planner_node)
    graph.add_node("plan_dispatcher",   plan_dispatcher_node)
    graph.add_node("data_analyst",      data_analyst_node)
    graph.add_node("friction_analysis", friction_analysis_node)
    graph.add_node("report_drafts",     report_drafts_node)
    graph.add_node("artifact_writer",   artifact_writer_node)
    graph.add_node("critique",          critique_node)
    graph.add_node("report_analyst",    report_analyst_node)
    graph.add_node("qna",              qna_node)

    graph.add_edge(START, "supervisor")

    # Work nodes -> plan_dispatcher (deterministic routing, no LLM)
    # data_analyst: route to planner when user just confirmed lenses, else plan_dispatcher
    def route_from_data_analyst(state: AnalyticsState) -> str:
        if state.get("next_agent") == "planner":
            return "planner"
        return "plan_dispatcher"

    graph.add_conditional_edges("data_analyst", route_from_data_analyst, {
        "planner": "planner",
        "plan_dispatcher": "plan_dispatcher",
    })
    graph.add_edge("friction_analysis", "plan_dispatcher")
    graph.add_edge("report_drafts",     "plan_dispatcher")
    graph.add_edge("artifact_writer",   "plan_dispatcher")
    graph.add_edge("critique",          "plan_dispatcher")

    # Planner -> plan_dispatcher (after initial plan creation, dispatcher picks first task)
    graph.add_edge("planner",          "plan_dispatcher")

    # Final nodes -> supervisor (for answer/qna routing)
    graph.add_edge("report_analyst",    "supervisor")

    # QnA ends the graph — next user message starts fresh via START -> supervisor
    graph.add_edge("qna",              END)

    # Supervisor conditional routing (only for initial routing + answer/qna)
    def route_from_supervisor(state: AnalyticsState) -> str:
        next_agent = state.get("next_agent", "")
        route_map = {
            "data_analyst":      "data_analyst",
            "friction_analysis": "friction_analysis",
            "report_drafts":     "report_drafts",
            "artifact_writer":   "artifact_writer",
            "critique":          "critique",
            "report_analyst":    "report_analyst",
            "qna":               "qna",
            "planner":           "planner",
            "supervisor":        "supervisor",
            "__end__":           END,
        }
        return route_map.get(next_agent, END)

    graph.add_conditional_edges("supervisor", route_from_supervisor, {
        "data_analyst":      "data_analyst",
        "friction_analysis": "friction_analysis",
        "report_drafts":     "report_drafts",
        "artifact_writer":   "artifact_writer",
        "critique":          "critique",
        "report_analyst":    "report_analyst",
        "qna":               "qna",
        "planner":           "planner",
        "supervisor":        "supervisor",
        END:                 END,
    })

    # Plan dispatcher conditional routing (deterministic next task)
    def route_from_plan_dispatcher(state: AnalyticsState) -> str:
        next_agent = state.get("next_agent", "")
        route_map = {
            "data_analyst":      "data_analyst",
            "friction_analysis": "friction_analysis",
            "report_drafts":     "report_drafts",
            "artifact_writer":   "artifact_writer",
            "critique":          "critique",
            "report_analyst":    "report_analyst",
            "planner":           "planner",
            "__end__":           END,
        }
        # Fall back to supervisor for unrecognized agents (e.g. qna routing)
        return route_map.get(next_agent, "supervisor")

    graph.add_conditional_edges("plan_dispatcher", route_from_plan_dispatcher, {
        "data_analyst":      "data_analyst",
        "friction_analysis": "friction_analysis",
        "report_drafts":     "report_drafts",
        "artifact_writer":   "artifact_writer",
        "critique":          "critique",
        "report_analyst":    "report_analyst",
        "planner":           "planner",
        "supervisor":        "supervisor",
        END:                 END,
    })

    compiled = graph.compile(checkpointer=checkpointer)
    compiled.recursion_limit = 25
    return compiled

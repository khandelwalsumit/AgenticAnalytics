"""Main LangGraph StateGraph assembly.

Each agent is defined as an explicit named async function inside ``build_graph``.
The docstring of every node states exactly which state fields it reads and writes,
so you can understand the full data flow without looking anywhere else.

Parallelism uses asyncio.gather (no LangGraph Send API).
Composite nodes (friction_analysis, report_generation) orchestrate sub-agents
internally and return a single merged delta to the graph.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
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
    _apply_supervisor_fallback,
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
    # checkpoint node
    user_checkpoint_node,
    # constants
    AGENT_STATE_FIELDS,
)
from agents.schemas import (
    LensAnalysisOutput,
    LensSynthesisOutput,
    PlannerOutput,
    SectionBlueprintOutput,
    SupervisorOutput,
    SynthesizerOutput,
)
from agents.state import AnalyticsState
from config import MAX_MULTITHREADING_WORKERS
from core.agent_factory import AgentFactory
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY

from agents.graph_helpers import (
    FRICTION_SUB_AGENTS,
    REPORTING_SUB_AGENTS,
    _build_executive_summary_message,
    _build_fallback_formatting_from_narrative_markdown,
    _build_fallback_section_blueprint,
    _build_friction_reasoning_entries,
    _build_report_reasoning_entries,
    _build_section_formatting_message,
    _make_sub_agent_entries,
    _make_sub_agent_entry,
    _merge_parallel_outputs,
    _merge_state_deltas,
    _record_plan_progress,
    _run_agent_with_retries,
    _run_artifact_writer_node,
    _run_section_artifact_writer,
    _persist_friction_outputs,
    _set_sub_agent_status,
    _set_task_sub_agents_and_emit,
    _validate_artifact_paths,
    _validate_formatting_blueprint,
    _validate_narrative,
    _validate_section_blueprint,
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
    # ------------------------------------------------------------------
    supervisor_chain, _ = agent_factory.create_structured_chain("supervisor")
    planner_chain, _    = agent_factory.create_structured_chain("planner")
    synthesizer_chain, _ = agent_factory.create_structured_chain("synthesizer_agent")
    formatting_chain, _  = agent_factory.create_structured_chain("formatting_agent")

    # Friction lens agents — all 4 use LensAnalysisOutput
    lens_chains: dict[str, Any] = {}
    for _lens_name in ["digital_friction_agent", "operations_agent", "communication_agent", "policy_agent"]:
        lens_chains[_lens_name], _ = agent_factory.create_structured_chain(_lens_name)
    # Per-lens synthesis (Phase 1)
    lens_synth_chain, _ = agent_factory.create_structured_chain("lens_synthesizer")

    # ══════════════════════════════════════════════════════════════════════════
    # SUPERVISOR
    # ══════════════════════════════════════════════════════════════════════════

    async def supervisor_node(state: AnalyticsState) -> dict[str, Any]:
        """Routes user intent to the correct pipeline stage.

        Reads:
            messages               – conversation so far
            dataset_schema         – available filter columns/values (injected into prompt)
            filters_applied        – current active filters (for scope-change detection)
            data_buckets           – row counts per theme (for insight-review display)
            themes_for_analysis    – extracted themes ready for analysis
            plan_tasks             – current execution plan (for execute routing)
            plan_steps_completed   – progress counter (for execute routing)
            navigation_log         – theme hierarchy (for context)
            analysis_objective     – confirmed objective (for context)

        Writes:
            next_agent             – which node to run next
            supervisor_decision    – "answer" | "clarify" | "extract" | "analyse" | "execute"
            messages               – user-visible reply (answer / clarify decisions only)
            plan_tasks             – marks next step in-progress (execute decision)
            selected_friction_agents, expected_friction_lenses
                                   – dimension filter from user reply (analyse decision)
        """
        ctx = _build_extra_context("supervisor", state, None)
        sys_prompt = agent_factory.parse_agent_md("supervisor").system_prompt + ctx

        base, structured, last_msg = await _run_structured_node(
            "supervisor", supervisor_chain, SupervisorOutput, sys_prompt, state, extra_context=ctx
        )

        if isinstance(structured, SupervisorOutput):
            _apply_supervisor(structured, state, base)
        elif last_msg:
            _apply_supervisor_fallback(_text(last_msg.content), state, base)
            data = _parse_json(_text(last_msg.content))
            reasoning = data.get("reasoning", base.get("supervisor_decision", "?"))
            base["reasoning"] = [{"step_name": "Supervisor", "step_text": reasoning}]

        return base

    # ══════════════════════════════════════════════════════════════════════════
    # PLANNER
    # ══════════════════════════════════════════════════════════════════════════

    async def planner_node(state: AnalyticsState) -> dict[str, Any]:
        """Creates the ordered execution plan from a confirmed objective and themes.

        Reads:
            filters_applied        – active filters (shown in context)
            themes_for_analysis    – buckets to analyse
            navigation_log         – theme hierarchy
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

        base, structured, last_msg = await _run_structured_node(
            "planner", planner_chain, PlannerOutput, sys_prompt, state, extra_context=ctx
        )

        if isinstance(structured, PlannerOutput):
            new_tasks = [t.model_dump() for t in structured.plan_tasks]
            existing   = state.get("plan_tasks", [])
            done_steps = [t for t in existing if t.get("status") == "done"]
            all_tasks  = done_steps + new_tasks
            base.update({
                "plan_tasks":           all_tasks,
                "plan_steps_total":     len(all_tasks),
                "plan_steps_completed": len(done_steps),
                "analysis_objective":   structured.analysis_objective,
            })
            base["reasoning"] = [{"step_name": "Planner", "step_text": structured.reasoning}]
            logger.info("Planner: %d tasks (%d done + %d new), objective=%r",
                        len(all_tasks), len(done_steps), len(new_tasks),
                        structured.analysis_objective[:80])
        elif last_msg:
            data = _parse_json(_text(last_msg.content))
            if data.get("plan_tasks"):
                existing   = state.get("plan_tasks", [])
                done_steps = [t for t in existing if t.get("status") == "done"]
                all_tasks  = done_steps + data["plan_tasks"]
                base.update({
                    "plan_tasks":           all_tasks,
                    "plan_steps_total":     len(all_tasks),
                    "plan_steps_completed": len(done_steps),
                })
                if data.get("analysis_objective"):
                    base["analysis_objective"] = data["analysis_objective"]

        return base

    # ══════════════════════════════════════════════════════════════════════════
    # DATA ANALYST
    # ══════════════════════════════════════════════════════════════════════════

    async def data_analyst_node(state: AnalyticsState) -> dict[str, Any]:
        """Loads the dataset, applies filters, and buckets themes.

        Reads:
            messages               – user's filter specification
            dataset_path           – CSV path from config
            dataset_schema         – available column names / values (injected into prompt)
            analysis_objective     – context for bucket labelling

        Writes:
            filters_applied        – dict of column→value filters that were applied
            themes_for_analysis    – list of bucket/theme names discovered
            data_buckets           – per-bucket row counts and sample rows
            dataset_schema         – populated from load_dataset if not already set
            messages               – single clean summary (tool noise replaced)

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
        if summary:
            base["messages"] = [AIMessage(content=summary)]

        _advance_plan("data_analyst", state, base)
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # FRICTION LENS AGENTS  (4 agents, run in parallel inside friction_analysis)
    # ══════════════════════════════════════════════════════════════════════════

    def _lens_md_base(agent_id: str, state: dict) -> str:
        """Return versioned-md base name: '{agent_id}_{bucket}' or just '{agent_id}'."""
        fb = state.get("_focus_bucket", "")
        return f"{agent_id}_{fb}" if fb else agent_id

    async def _structured_lens_node(
        agent_id: str, state_field: str, display_name: str, state: AnalyticsState,
    ) -> dict[str, Any]:
        """Generic structured-output lens node. Shared by all 4 friction agents."""
        ctx = _build_extra_context(agent_id, state, skill_loader)
        sys_prompt = agent_factory.parse_agent_md(agent_id).system_prompt + ctx

        base, structured, last_msg = await _run_structured_node(
            agent_id, lens_chains[agent_id], LensAnalysisOutput, sys_prompt, state, extra_context=ctx,
        )

        if isinstance(structured, LensAnalysisOutput):
            analysis_dict = structured.model_dump()
            summary = structured.bucket_analysis.key_finding or structured.reasoning
            output_field = {
                "output": summary[:200],
                "full_response": json.dumps(analysis_dict, indent=2),
                "agent": agent_id,
                "structured": analysis_dict,
            }
        else:
            summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
            output_field = _agent_output_field(agent_id, base["messages"], summary)

        base[state_field] = output_field
        base["reasoning"] = [{"step_name": display_name, "step_text": (summary or "")[:200]}]

        md_content = output_field.get("full_response", "") or summary
        md_path = _write_versioned_md(
            _lens_md_base(agent_id, state),
            md_content,
            {"agent": agent_id, "bucket": state.get("_focus_bucket", "all")},
        )
        if md_path:
            base["friction_md_paths"] = {agent_id: md_path}
        return base

    async def digital_friction_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies digital/UX friction using structured output.

        Reads:  messages, data_buckets, _focus_bucket, skill_loader (context)
        Writes: digital_analysis, friction_md_paths
        """
        return await _structured_lens_node(
            "digital_friction_agent", "digital_analysis", "Digital Friction Agent", state,
        )

    async def operations_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies operational friction using structured output.

        Reads:  messages, data_buckets, _focus_bucket, skill_loader (context)
        Writes: operations_analysis, friction_md_paths
        """
        return await _structured_lens_node(
            "operations_agent", "operations_analysis", "Operations Agent", state,
        )

    async def communication_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies communication friction using structured output.

        Reads:  messages, data_buckets, _focus_bucket, skill_loader (context)
        Writes: communication_analysis, friction_md_paths
        """
        return await _structured_lens_node(
            "communication_agent", "communication_analysis", "Communication Agent", state,
        )

    async def policy_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies policy friction using structured output.

        Reads:  messages, data_buckets, _focus_bucket, skill_loader (context)
        Writes: policy_analysis, friction_md_paths
        """
        return await _structured_lens_node(
            "policy_agent", "policy_analysis", "Policy Agent", state,
        )

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
            selected_friction_agents / expected_friction_lenses – which lenses ran

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

        base, structured, last_msg = await _run_structured_node(
            "synthesizer_agent", synthesizer_chain, SynthesizerOutput, sys_prompt, state, extra_context=ctx
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

            # Compact insights kept in state so supervisor can answer questions
            # about analysis results without re-running the pipeline.
            top_theme_names = [t.theme for t in structured.themes[:5]] if structured.themes else []
            analytics_insights = {
                "executive_narrative":    narrative,
                "top_themes":             top_theme_names,
                "total_calls_analyzed":   structured.summary.total_calls_analyzed,
                "total_findings":         structured.summary.total_findings,
                "quick_wins_count":       structured.summary.quick_wins_count,
                "overall_preventability": structured.summary.overall_preventability,
                "confidence":             structured.confidence,
            }

            base.update({
                "synthesis_result":  synthesis_data,
                "findings":          [f.model_dump() for f in structured.findings],
                "analytics_insights": analytics_insights,
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
    # FORMATTING AGENT  (structured: outputs a slide blueprint JSON)
    # ══════════════════════════════════════════════════════════════════════════

    async def formatting_node(state: AnalyticsState) -> dict[str, Any]:
        """Converts a single narrative section into a structured slide blueprint JSON.

        Reads:
            messages               – section formatting instruction with template spec
            narrative_output       – full_response contains the markdown text with slide tags
            synthesis_result       – summary context for chart data
            findings               – compact finding list
            report_retry_context   – retry instructions if validation failed

        Writes:
            formatting_output      – {output, full_response, agent}
                                     full_response is a JSON section blueprint
                                     (SectionBlueprintOutput serialised)
        """
        ctx = _build_extra_context("formatting_agent", state, None)
        sys_prompt = agent_factory.parse_agent_md("formatting_agent").system_prompt + ctx

        base, structured, last_msg = await _run_structured_node(
            "formatting_agent", formatting_chain, SectionBlueprintOutput, sys_prompt, state, extra_context=ctx
        )

        if isinstance(structured, SectionBlueprintOutput):
            blueprint_json = structured.model_dump_json(indent=2)
            slide_count    = len(structured.slides)
            base["formatting_output"] = {
                "output":        f"{structured.section_key}: {slide_count} slides",
                "full_response": blueprint_json,
                "agent":         "formatting_agent",
            }
            base["reasoning"] = [{
                "step_name": "Formatting Agent",
                "step_text": f"Section blueprint ready: {structured.section_key} with {slide_count} slides.",
            }]
        elif last_msg:
            raw = _text(last_msg.content)
            base["formatting_output"] = _agent_output_field("formatting_agent", base["messages"], _trunc(raw, 200))
            base["reasoning"] = [{"step_name": "Formatting Agent", "step_text": _trunc(raw, 200)}]

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
        base, last_msg = await _run_react_node("critique", agent_factory, "", state)

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

    # ══════════════════════════════════════════════════════════════════════════
    # COMPOSITE NODE: friction_analysis
    # Runs the 4 lens agents in parallel (asyncio.gather), then synthesizer.
    # Respects selected_friction_agents from state for dimension selection.
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

    _LENS_TO_DIMENSION: dict[str, str] = {
        "digital_friction_agent": "digital",
        "operations_agent": "operations",
        "communication_agent": "communication",
        "policy_agent": "policy",
    }

    async def friction_analysis_node(state: AnalyticsState) -> dict[str, Any]:
        """Run each lens agent once per bucket in parallel, then two-pass synthesis.

        Phase 0: Run (lens × bucket) combinations in parallel via asyncio.gather.
                 Each lens produces a LensAnalysisOutput (structured).
                 UI shows live ``(completed/total)`` per lens.
        Phase 1: Per-lens synthesis — LLM-driven merge of bucket outputs into
                 max 10 themes per lens (LensSynthesisOutput). 4 runs in parallel.
        Phase 2: Final synthesis — synthesizer reads 4 LensSynthesisOutput JSONs
                 and produces max 10 cross-lens themes (SynthesizerOutput).

        Reads:  selected_friction_agents, data_buckets
        Writes: friction_md_paths (nested), lens_synthesis_paths,
                lens_synthesis_results, lens_bucket_results,
                synthesis_result, findings, expected/missing_friction_lenses,
                plan_steps_completed
        """
        selected = state.get("selected_friction_agents", [])
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
        per_agent_limit = max(per_agent_limit, 1)
        semaphore = asyncio.Semaphore(MAX_MULTITHREADING_WORKERS)
        logger.info(
            "Friction analysis: %d lenses × %d buckets = %d runs "
            "(max %d workers, %d per agent)",
            len(lens_ids), total_buckets, total_runs,
            MAX_MULTITHREADING_WORKERS, per_agent_limit,
        )

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
                focused_state["_focus_bucket"] = bucket_key
                coro = _LENS_NODE_MAP[lens_id](focused_state)
                run_tasks.append(_tracked_run(lens_id, bucket_key, coro))
                run_combos.append((lens_id, bucket_key))

        results = await asyncio.gather(*run_tasks)

        # Assemble nested friction_md_paths + structured bucket results
        nested_md_paths: dict[str, dict[str, str]] = {lid: {} for lid in lens_ids}
        lens_bucket_results: dict[str, dict[str, dict]] = {lid: {} for lid in lens_ids}
        for (lens_id, bucket_key), result in zip(run_combos, results):
            flat_paths = result.get("friction_md_paths", {})
            nested_md_paths[lens_id][bucket_key] = flat_paths.get(lens_id, "")
            # Collect structured output for Phase 1
            field_name = AGENT_STATE_FIELDS.get(lens_id, "")
            analysis = result.get(field_name, {})
            if isinstance(analysis, dict) and "structured" in analysis:
                lens_bucket_results[lens_id][bucket_key] = analysis["structured"]

        merged = _merge_parallel_outputs(list(results))
        merged["friction_md_paths"]        = nested_md_paths
        merged["expected_friction_lenses"] = lens_ids
        merged["lens_bucket_results"]      = lens_bucket_results

        logger.info("  Merged %d friction outputs: lenses=%s, buckets=%s",
                    total_runs, lens_ids, bucket_keys)

        # ── Phase 1: per-lens LLM synthesis (parallel, 4 tasks) ──
        sub_agents.append({
            "id": "synthesizer_agent",
            "title": FRICTION_SUB_AGENTS["synthesizer_agent"]["title"],
            "detail": f"Per-lens synthesis (0/{len(lens_ids)})",
            "status": "in_progress",
        })
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="friction_analysis",
            sub_agents=sub_agents, task_status="in_progress",
        )

        lens_synthesis_paths: dict[str, str] = {}
        lens_synthesis_results: dict[str, dict] = {}
        completed_synth = {"count": 0}

        async def _run_lens_synthesis(lens_id: str) -> None:
            """Run lens_synthesizer for one lens."""
            bucket_outputs = list(lens_bucket_results[lens_id].values())
            if not bucket_outputs:
                return

            synth_state = dict(state)
            synth_state["_synthesis_lens_id"] = lens_id
            synth_state["_lens_bucket_outputs"] = bucket_outputs
            synth_state["messages"] = list(state["messages"])

            ctx = _build_extra_context("lens_synthesizer", synth_state, None)
            sys_prompt = agent_factory.parse_agent_md("lens_synthesizer").system_prompt + ctx

            _base, structured, _ = await _run_structured_node(
                "lens_synthesizer", lens_synth_chain,
                LensSynthesisOutput, sys_prompt, synth_state, extra_context=ctx,
            )

            if isinstance(structured, LensSynthesisOutput):
                result_dict = structured.model_dump()
                result_dict["lens"] = _LENS_TO_DIMENSION[lens_id]
                lens_synthesis_results[lens_id] = result_dict

                lens_path = _write_versioned_md(
                    f"lens_synthesis_{lens_id}",
                    json.dumps(result_dict, indent=2, default=str),
                    {"lens": lens_id, "type": "lens_synthesis"},
                )
                if lens_path:
                    lens_synthesis_paths[lens_id] = lens_path

            completed_synth["count"] += 1
            _set_sub_agent_status(
                sub_agents, "synthesizer_agent", status="in_progress",
                detail=f"Per-lens synthesis ({completed_synth['count']}/{len(lens_ids)})",
            )
            nonlocal tasks
            tasks = await _set_task_sub_agents_and_emit(
                tasks, agent_name="friction_analysis",
                sub_agents=sub_agents, task_status="in_progress",
            )

        await asyncio.gather(*[_run_lens_synthesis(lid) for lid in lens_ids])

        merged["lens_synthesis_paths"]   = lens_synthesis_paths
        merged["lens_synthesis_results"] = lens_synthesis_results
        logger.info("  Phase 1 done: %d per-lens syntheses", len(lens_synthesis_results))

        # ── Phase 2: final cross-lens synthesis (single LLM call) ──
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
        synth_state["messages"]               = list(state["messages"]) + merged.get("messages", [])
        synth_state["lens_synthesis_results"] = lens_synthesis_results
        synth_state["lens_synthesis_paths"]   = lens_synthesis_paths

        logger.info("Friction analysis: running synthesizer (Phase 2) | %d lens syntheses",
                    len(lens_synthesis_results))
        synth_result = await synthesizer_node(synth_state)

        # Tag synthesis with completeness decision
        missing_lenses = [lid for lid in lens_ids if lid not in lens_synthesis_results]
        synthesis_payload = synth_result.get("synthesis_result", {})
        if isinstance(synthesis_payload, dict):
            synthesis_payload = dict(synthesis_payload)
            synthesis_payload["decision"] = "complete" if not missing_lenses else "incomplete"
            synth_result["synthesis_result"] = synthesis_payload
        synth_result["missing_friction_lenses"]  = list(missing_lenses)
        synth_result["expected_friction_lenses"] = list(lens_ids)

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
            list_keys={"execution_trace", "io_trace"},
            skip_keys={"messages"},
        )
        final["reasoning"]   = _build_friction_reasoning_entries(lens_ids, state, synth_result)
        final["messages"]    = synth_result.get("messages", [])
        final["plan_tasks"]  = tasks

        _record_plan_progress(state, final, agent_name="friction_analysis")
        return final

    # ══════════════════════════════════════════════════════════════════════════
    # COMPOSITE NODE: report_generation
    # Runs narrative → formatting blueprint → deterministic artifact writer.
    # ══════════════════════════════════════════════════════════════════════════

    async def report_generation_node(state: AnalyticsState) -> dict[str, Any]:
        """Narrative agent → formatting blueprint → deterministic artifact writing.

        Reads:
            synthesis_result       – themes + findings for narrative
            synthesis_output_file  – DataStore key (preferred over state dict)
            findings               – flat finding list
            filters_applied        – report header
            friction_output_files  – must all be present (guard enforced)
            expected / missing friction lenses – completeness check

        Writes:
            narrative_output       – markdown narrative
            formatting_output      – slide blueprint JSON
            report_file_path       – PPTX path on disk
            markdown_file_path     – .md path on disk
            data_file_path         – CSV path on disk
            plan_steps_completed   – incremented
            analysis_complete      – True (pipeline done)
        """
        logger.info("Report generation: starting narrative -> formatting blueprint -> artifact writer")
        expected = state.get("expected_friction_lenses", []) or state.get("selected_friction_agents", [])
        expected = list(dict.fromkeys([a for a in expected if a]))
        # Check completeness via lens_synthesis_paths (per-bucket) or friction_output_files (legacy)
        available_lenses = list((state.get("lens_synthesis_paths", {}) or {}).keys())
        if not available_lenses:
            available_lenses = list((state.get("friction_output_files", {}) or {}).keys())
        missing = state.get("missing_friction_lenses", []) or [a for a in expected if a not in available_lenses]
        missing = list(dict.fromkeys([a for a in missing if a]))
        if missing:
            raise RuntimeError(
                "Report generation blocked: required friction lenses are missing outputs. "
                f"Missing: {missing}. Run complete friction analysis before generating report artifacts."
            )

        sub_agents = [
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "narrative_agent",    status="in_progress"),
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "formatting_agent",   status="ready"),
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "artifact_writer_node", status="ready"),
        ]
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []), agent_name="report_generation",
            sub_agents=sub_agents, task_status="in_progress",
        )

        # --- Step 1: Narrative agent ---
        narrative_state = dict(state)
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
            tasks, agent_name="report_generation", sub_agents=sub_agents, task_status="in_progress",
        )

        # --- Step 2: Section-based formatting (3 parallel LLM calls) ---
        from utils.section_splitter import split_narrative_into_sections

        narrative_payload = narrative_result.get("narrative_output", {})
        narrative_md = str(
            narrative_payload.get("full_response", "") if isinstance(narrative_payload, dict) else ""
        ).strip()

        # Split narrative into 3 sections with template catalog slices
        sections = split_narrative_into_sections(narrative_md)

        # Extract synthesis summary for verification
        synthesis_payload = state.get("synthesis_result", {})
        synthesis_summary = {}
        if isinstance(synthesis_payload, dict):
            summary_obj = synthesis_payload.get("summary", {})
            if isinstance(summary_obj, dict):
                synthesis_summary = summary_obj

        # Run formatting agent once per section in parallel
        section_keys = ["exec_summary", "impact", "theme_deep_dives"]
        section_blueprints: list[dict[str, Any]] = []

        async def _format_one_section(section_key: str) -> dict[str, Any]:
            section_data = sections.get(section_key, {})
            if not section_data or not section_data.get("narrative_chunk"):
                logger.warning("Report generation: section '%s' has no narrative content, using fallback", section_key)
                return _build_fallback_section_blueprint(section_key, section_data)

            fmt_state = dict(state)
            for k, v in _merge_parallel_outputs([narrative_result]).items():
                if k != "messages":
                    fmt_state[k] = v
            fmt_state["messages"] = [HumanMessage(content=_build_section_formatting_message(
                section_key, section_data, synthesis_summary,
            ))]

            try:
                fmt_result = await _run_agent_with_retries(
                    agent_id="formatting_agent", node_fn=formatting_node,
                    base_state=fmt_state, required_tools=[],
                    validator=_validate_section_blueprint, max_attempts=2,
                )
                # Extract the blueprint JSON from the result
                fmt_payload = fmt_result.get("formatting_output", {})
                fmt_json_str = fmt_payload.get("full_response", "") if isinstance(fmt_payload, dict) else ""
                from agents.graph_helpers import _extract_json
                fmt_json = _extract_json(fmt_json_str)
                if isinstance(fmt_json, dict) and fmt_json.get("slides"):
                    return fmt_json
            except Exception as e:
                logger.warning("Report generation: section '%s' formatting failed: %s -- using fallback", section_key, e)

            return _build_fallback_section_blueprint(section_key, section_data)

        # Run all 3 sections in parallel
        section_results = await asyncio.gather(
            *[_format_one_section(sk) for sk in section_keys],
            return_exceptions=False,
        )
        section_blueprints = list(section_results)
        total_slides = sum(len(s.get("slides", [])) for s in section_blueprints)
        logger.info("Report generation: section formatting complete | %d total slides across %d sections",
                     total_slides, len(section_blueprints))

        _set_sub_agent_status(sub_agents, "formatting_agent",    status="done")
        _set_sub_agent_status(sub_agents, "artifact_writer_node", status="in_progress")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="report_generation", sub_agents=sub_agents, task_status="in_progress",
        )

        # --- Step 3: Deterministic section-based artifact writer ---
        artifact_result = _run_section_artifact_writer(state, narrative_result, section_blueprints)
        artifact_errors = _validate_artifact_paths(artifact_result)
        if artifact_errors:
            raise RuntimeError(f"artifact_writer_node failed validation: {artifact_errors}")
        logger.info(
            "Report generation: artifacts created | report=%r markdown=%r data=%r",
            artifact_result.get("report_file_path", ""),
            artifact_result.get("markdown_file_path", ""),
            artifact_result.get("data_file_path", ""),
        )

        _set_sub_agent_status(sub_agents, "artifact_writer_node", status="done",
                              detail="Creating PPT, data and md files.")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="report_generation", sub_agents=sub_agents, task_status="done",
        )

        # Build a formatting summary result for state merge
        fmt_summary = {
            "formatting_output": {
                "output": f"{total_slides} slides across {len(section_blueprints)} sections",
                "full_response": json.dumps(section_blueprints, indent=2, default=str),
                "agent": "formatting_agent",
            },
        }
        final = _merge_state_deltas(
            narrative_result, fmt_summary, artifact_result,
            list_keys={"execution_trace", "io_trace"},
            skip_keys={"messages"},
        )
        final["reasoning"]  = _build_report_reasoning_entries()
        final["messages"]   = [AIMessage(content=_build_executive_summary_message(final.get("narrative_output", {})))]
        final["plan_tasks"] = tasks

        _record_plan_progress(state, final, agent_name="report_generation", mark_analysis_complete=True)
        return final

    # ------------------------------------------------------------------
    # Graph wiring
    # ------------------------------------------------------------------

    graph = StateGraph(AnalyticsState)

    graph.add_node("supervisor",        supervisor_node)
    graph.add_node("planner",           planner_node)
    graph.add_node("data_analyst",      data_analyst_node)
    graph.add_node("report_analyst",    report_analyst_node)
    graph.add_node("critique",          critique_node)
    graph.add_node("user_checkpoint",   user_checkpoint_node)
    graph.add_node("friction_analysis", friction_analysis_node)
    graph.add_node("report_generation", report_generation_node)

    graph.add_edge(START, "supervisor")

    def route_from_supervisor(state: AnalyticsState) -> str:
        next_agent = state.get("next_agent", "")
        route_map = {
            "friction_analysis": "friction_analysis",
            "report_generation": "report_generation",
            "data_analyst":      "data_analyst",
            "planner":           "planner",
            "report_analyst":    "report_analyst",
            "critique":          "critique",
            "user_checkpoint":   "user_checkpoint",
            "__end__":           END,
        }
        return route_map.get(next_agent, END)

    graph.add_conditional_edges("supervisor", route_from_supervisor, {
        "friction_analysis": "friction_analysis",
        "report_generation": "report_generation",
        "data_analyst":      "data_analyst",
        "planner":           "planner",
        "report_analyst":    "report_analyst",
        "critique":          "critique",
        "user_checkpoint":   "user_checkpoint",
        END:                 END,
    })

    graph.add_edge("friction_analysis", "supervisor")
    graph.add_edge("report_generation", "supervisor")
    graph.add_edge("data_analyst",      "supervisor")
    graph.add_edge("planner",           "supervisor")
    graph.add_edge("report_analyst",    "supervisor")
    graph.add_edge("critique",          "supervisor")
    graph.add_edge("user_checkpoint",   "supervisor")

    compiled = graph.compile(checkpointer=checkpointer, interrupt_before=["user_checkpoint"])
    compiled.recursion_limit = 25
    return compiled

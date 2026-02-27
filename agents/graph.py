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
    # checkpoint node
    user_checkpoint_node,
    # constants
    AGENT_STATE_FIELDS,
)
from agents.schemas import (
    FormattingDeckOutput,
    PlannerOutput,
    SupervisorOutput,
    SynthesizerOutput,
)
from agents.state import AnalyticsState
from core.agent_factory import AgentFactory
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY

from agents.graph_helpers import (
    FRICTION_SUB_AGENTS,
    REPORTING_SUB_AGENTS,
    _build_executive_summary_message,
    _build_fallback_formatting_from_narrative_markdown,
    _build_friction_reasoning_entries,
    _build_report_reasoning_entries,
    _make_sub_agent_entries,
    _make_sub_agent_entry,
    _merge_parallel_outputs,
    _merge_state_deltas,
    _record_plan_progress,
    _run_agent_with_retries,
    _run_artifact_writer_node,
    _persist_friction_outputs,
    _set_sub_agent_status,
    _set_task_sub_agents_and_emit,
    _validate_artifact_paths,
    _validate_formatting_blueprint,
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
    # Structured agents: supervisor, planner, synthesizer_agent, formatting_agent
    # ------------------------------------------------------------------
    supervisor_chain, _ = agent_factory.create_structured_chain("supervisor")
    planner_chain, _    = agent_factory.create_structured_chain("planner")
    synthesizer_chain, _ = agent_factory.create_structured_chain("synthesizer_agent")
    formatting_chain, _  = agent_factory.create_structured_chain("formatting_agent")

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
            "supervisor", supervisor_chain, SupervisorOutput, sys_prompt, state
        )

        if isinstance(structured, SupervisorOutput):
            _apply_supervisor(structured, state, base)
        elif last_msg:
            _apply_supervisor_fallback(_text(last_msg.content), state, base)

        base["reasoning"] = [{"step_name": "Supervisor", "step_text": base.get("supervisor_decision", "?")}]
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
            "planner", planner_chain, PlannerOutput, sys_prompt, state
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

    async def digital_friction_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies digital/UX friction: app failures, self-service gaps, web issues.

        Reads:
            messages               – conversation context
            data_buckets           – per-bucket row data to analyse
            themes_for_analysis    – bucket names in scope
            skill_loader           – domain skill catalog (injected from closure)

        Writes:
            digital_analysis       – {output, full_response, agent}
                                     Bucket-level findings with call counts,
                                     ease/impact scores (1-10), primary/secondary drivers.

        Tools: analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("digital_friction_agent", state, skill_loader)
        base, last_msg = await _run_react_node("digital_friction_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        base["digital_analysis"] = _agent_output_field("digital_friction_agent", base["messages"], summary)
        base["reasoning"] = [{"step_name": "Digital Friction Agent", "step_text": summary}]
        return base

    async def operations_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies operational friction: process breakdowns, SLA breaches, handoff failures.

        Reads:
            messages, data_buckets, themes_for_analysis, skill_loader

        Writes:
            operations_analysis    – {output, full_response, agent}
                                     Bucket-level findings with call counts and scores.

        Tools: analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("operations_agent", state, skill_loader)
        base, last_msg = await _run_react_node("operations_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        base["operations_analysis"] = _agent_output_field("operations_agent", base["messages"], summary)
        base["reasoning"] = [{"step_name": "Operations Agent", "step_text": summary}]
        return base

    async def communication_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies communication friction: notification gaps, expectation mismatches.

        Reads:
            messages, data_buckets, themes_for_analysis, skill_loader

        Writes:
            communication_analysis – {output, full_response, agent}

        Tools: analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("communication_agent", state, skill_loader)
        base, last_msg = await _run_react_node("communication_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        base["communication_analysis"] = _agent_output_field("communication_agent", base["messages"], summary)
        base["reasoning"] = [{"step_name": "Communication Agent", "step_text": summary}]
        return base

    async def policy_node(state: AnalyticsState) -> dict[str, Any]:
        """Identifies policy friction: regulatory constraints, fee disputes, compliance issues.

        Reads:
            messages, data_buckets, themes_for_analysis, skill_loader

        Writes:
            policy_analysis        – {output, full_response, agent}

        Tools: analyze_bucket, score_friction_driver
        """
        ctx = _build_extra_context("policy_agent", state, skill_loader)
        base, last_msg = await _run_react_node("policy_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        base["policy_analysis"] = _agent_output_field("policy_agent", base["messages"], summary)
        base["reasoning"] = [{"step_name": "Policy Agent", "step_text": summary}]
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
            "synthesizer_agent", synthesizer_chain, SynthesizerOutput, sys_prompt, state
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

            base.update({
                "synthesis_result": synthesis_data,
                "findings":         [f.model_dump() for f in structured.findings],
            })
            base["reasoning"] = [{"step_name": "Synthesizer Agent", "step_text": narrative}]
            if narrative:
                base["messages"] = [AIMessage(content=narrative)]
            logger.info("Synthesizer: %d findings, %d themes, confidence=%d",
                        len(structured.findings), len(structured.themes), structured.confidence)

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
        base["narrative_output"] = _agent_output_field("narrative_agent", base["messages"], summary)
        base["reasoning"] = [{"step_name": "Narrative Agent", "step_text": summary}]
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # FORMATTING AGENT  (structured: outputs a slide blueprint JSON)
    # ══════════════════════════════════════════════════════════════════════════

    async def formatting_node(state: AnalyticsState) -> dict[str, Any]:
        """Converts narrative markdown into a structured slide blueprint JSON.

        Reads:
            messages               – instruction to parse narrative
            narrative_output       – full_response contains the markdown text with slide tags
            synthesis_result       – summary context for chart data
            findings               – compact finding list
            report_retry_context   – retry instructions if validation failed

        Writes:
            formatting_output      – {output, full_response, agent}
                                     full_response is a JSON slide blueprint
                                     (FormattingDeckOutput serialised)
        """
        ctx = _build_extra_context("formatting_agent", state, None)
        sys_prompt = agent_factory.parse_agent_md("formatting_agent").system_prompt + ctx

        base, structured, last_msg = await _run_structured_node(
            "formatting_agent", formatting_chain, FormattingDeckOutput, sys_prompt, state
        )

        if isinstance(structured, FormattingDeckOutput):
            blueprint_json = structured.model_dump_json(indent=2)
            slide_count    = len(structured.slides)
            qa_count       = len(structured.qa_enhancements_applied)
            base["formatting_output"] = {
                "output":        f"{slide_count} slides, {qa_count} QA notes",
                "full_response": blueprint_json,
                "agent":         "formatting_agent",
            }
            base["reasoning"] = [{
                "step_name": "Formatting Agent",
                "step_text": f"Slide blueprint ready: {slide_count} slides, {qa_count} QA enhancements.",
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

    async def friction_analysis_node(state: AnalyticsState) -> dict[str, Any]:
        """Run selected friction lens agents in parallel, then synthesize.

        Reads:  selected_friction_agents (which lenses to run; all 4 if empty)
        Writes: digital_analysis, operations_analysis, communication_analysis,
                policy_analysis, synthesis_result, findings, friction_output_files,
                expected_friction_lenses, missing_friction_lenses,
                synthesis_output_file (DataStore key), plan_steps_completed
        """
        selected = state.get("selected_friction_agents", [])
        lens_ids = [a for a in selected if a in _ALL_LENS_IDS] if selected else list(_ALL_LENS_IDS)
        if not lens_ids:
            lens_ids = list(_ALL_LENS_IDS)
        lens_ids = list(dict.fromkeys(lens_ids))

        logger.info("Friction analysis: starting %d agents: %s", len(lens_ids), lens_ids)

        sub_agents_before = _make_sub_agent_entries(FRICTION_SUB_AGENTS, lens_ids, status="in_progress")
        _ = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []), agent_name="friction_analysis",
            sub_agents=sub_agents_before, task_status="in_progress",
        )

        node_fns = [_LENS_NODE_MAP[aid] for aid in lens_ids]
        results  = await asyncio.gather(*(fn(state) for fn in node_fns))

        for agent_id, result in zip(lens_ids, results):
            has_output = any(result.get(f) for f in (
                "digital_analysis", "operations_analysis", "communication_analysis", "policy_analysis"
            ))
            logger.info("  Friction [%s]: msgs=%d, has_state_field=%s",
                        agent_id, len(result.get("messages", [])), has_output)

        merged = _merge_parallel_outputs(list(results))
        logger.info("  Merged friction outputs: keys=%s, msgs=%d",
                    [k for k in merged if merged[k] and k != "messages"],
                    len(merged.get("messages", [])))

        friction_output_files = _persist_friction_outputs(lens_ids, list(results))
        merged["friction_output_files"]    = friction_output_files
        merged["expected_friction_lenses"] = lens_ids
        merged["missing_friction_lenses"]  = [aid for aid in lens_ids if aid not in friction_output_files]

        sub_agents = [_make_sub_agent_entry(FRICTION_SUB_AGENTS, aid, status="done") for aid in lens_ids]
        sub_agents.append(_make_sub_agent_entry(FRICTION_SUB_AGENTS, "synthesizer_agent", status="in_progress"))
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []), agent_name="friction_analysis",
            sub_agents=sub_agents, task_status="in_progress",
        )

        # Build synthesizer input state: original conversation + all friction messages + merged fields
        synth_state = dict(state)
        for k, v in merged.items():
            if k != "messages":
                synth_state[k] = v
        synth_state["messages"]             = list(state["messages"]) + merged.get("messages", [])
        synth_state["friction_output_files"] = friction_output_files

        logger.info(
            "Friction analysis: running synthesizer | msgs=%d | digital=%s ops=%s comm=%s policy=%s",
            len(synth_state["messages"]),
            bool(synth_state.get("digital_analysis")),  bool(synth_state.get("operations_analysis")),
            bool(synth_state.get("communication_analysis")), bool(synth_state.get("policy_analysis")),
        )
        synth_result = await synthesizer_node(synth_state)

        # Tag synthesis with completeness decision
        expected_lenses = merged.get("expected_friction_lenses", lens_ids)
        missing_lenses  = merged.get("missing_friction_lenses", [])
        synthesis_payload = synth_result.get("synthesis_result", {})
        if isinstance(synthesis_payload, dict):
            synthesis_payload = dict(synthesis_payload)
            synthesis_payload["decision"] = "complete" if not missing_lenses else "incomplete"
            if missing_lenses:
                reason = str(synthesis_payload.get("reasoning", "")).strip()
                extra  = f" Missing expected lens outputs: {', '.join(missing_lenses)}."
                synthesis_payload["reasoning"] = (reason + extra).strip() if reason else extra.strip()
            synth_result["synthesis_result"] = synthesis_payload
        synth_result["missing_friction_lenses"]  = list(missing_lenses)
        synth_result["expected_friction_lenses"] = list(expected_lenses)

        # Offload synthesis_result to DataStore to avoid state bloat
        import chainlit as cl
        data_store = cl.user_session.get("data_store")
        if data_store and synth_result.get("synthesis_result"):
            try:
                content = json.dumps(synth_result["synthesis_result"])
                key = data_store.store_text(
                    "synthesis_output", content,
                    {"agent": "synthesizer_agent", "type": "synthesis_output"},
                )
                synth_result["synthesis_output_file"] = key
                logger.info("Friction analysis: stored synthesis_result in DataStore as %s", key)
            except Exception as e:
                logger.error("Friction analysis: failed to store synthesis_result: %s", e)

        logger.info("Friction analysis: synthesizer done | findings=%d synthesis=%s msgs=%d",
                    len(synth_result.get("findings", [])),
                    bool(synth_result.get("synthesis_output_file")),
                    len(synth_result.get("messages", [])))

        _set_sub_agent_status(sub_agents, "synthesizer_agent", status="done",
                              detail="Consolidating cross-lens signals into an executive synthesis.")
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
        available = list((state.get("friction_output_files", {}) or {}).keys())
        missing = state.get("missing_friction_lenses", []) or [a for a in expected if a not in available]
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

        # --- Step 2: Formatting agent (slide blueprint) ---
        fmt_state = dict(state)
        for k, v in _merge_parallel_outputs([narrative_result]).items():
            if k != "messages":
                fmt_state[k] = v
        fmt_state["messages"] = [HumanMessage(content=(
            "Parse narrative markdown and create the slide blueprint JSON with chart placeholders. "
            "Do not call export tools."
        ))]

        try:
            fmt_result = await _run_agent_with_retries(
                agent_id="formatting_agent", node_fn=formatting_node,
                base_state=fmt_state, required_tools=[],
                validator=_validate_formatting_blueprint, max_attempts=2,
            )
        except Exception as fmt_error:
            fallback_blueprint = _build_fallback_formatting_from_narrative_markdown(
                str(narrative_result.get("narrative_output", {}).get("full_response", ""))
            )
            fallback_json = json.dumps(fallback_blueprint, indent=2)
            fmt_result = {
                "messages":         [AIMessage(content=fallback_json)],
                "formatting_output": {
                    "output":        fallback_json[:200],
                    "full_response": fallback_json,
                    "agent":         "formatting_agent",
                },
                "reasoning": [{
                    "step_name": "Formatting Fallback",
                    "step_text": (
                        "Formatting agent retries failed; generated deterministic blueprint "
                        "from narrative markdown slide tags."
                    ),
                    "agent": "formatting_agent",
                }],
            }
            logger.warning("Report generation: formatting fallback used due to error: %s", fmt_error)

        _set_sub_agent_status(sub_agents, "formatting_agent",    status="done")
        _set_sub_agent_status(sub_agents, "artifact_writer_node", status="in_progress")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="report_generation", sub_agents=sub_agents, task_status="in_progress",
        )

        # --- Step 3: Deterministic artifact writer ---
        artifact_result = _run_artifact_writer_node(state, narrative_result, fmt_result)
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

        final = _merge_state_deltas(
            narrative_result, fmt_result, artifact_result,
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

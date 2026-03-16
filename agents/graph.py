"""Main LangGraph StateGraph assembly.

Each agent is defined as an explicit named async function inside ``build_graph``.
The docstring of every node states exactly which state fields it reads and writes,
so you can understand the full data flow without looking anywhere else.

State rule: nothing large lives in AnalyticsState.
All large payloads are written to files; state holds file pointers only.

Parallelism uses asyncio.gather (no LangGraph Send API).
Composite node (friction_analysis) orchestrates lens agents internally.
Report pipeline: report_drafts (narrative + blueprint) → artifact_writer (PPTX/CSV/MD).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from langchain_core.messages import AIMessage, HumanMessage

from agents.nodes import (
    # invocation helpers
    _run_structured_node,
    _run_react_node,
    # context builders
    _build_extra_context,
    # structured-output appliers
    _apply_supervisor,
    # tool-result extractors
    _extract_data_analyst_state,
    _extract_formatting_state,
    # plan helpers
    _advance_plan,
    _find_next_plan_agent,
    # text / JSON utils
    _text,
    _trunc,
    _parse_json,
    # file writing
    _write_versioned_md,
    _write_file,
    # guard helpers
    _enforce_analysis_start_guard,
)
from agents.schemas import (
    PlannerOutput,
    SupervisorOutput,
    SynthesizerOutput,
)
from agents.state import AnalyticsState
from config import (
    MAX_MULTITHREADING_WORKERS,
    MAX_SUPERVISOR_MSGS,
    SPECIALIST_DOMAIN_TRIGGERS,
    SPECIALIST_MIN_BUCKET_SIZE,
)
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
    # ------------------------------------------------------------------
    supervisor_chain, _    = agent_factory.create_structured_chain("supervisor")
    planner_chain, _       = agent_factory.create_structured_chain("planner")
    synthesizer_chain, _   = agent_factory.create_structured_chain("synthesizer_agent")

    # ══════════════════════════════════════════════════════════════════════════
    # SUPERVISOR
    # ══════════════════════════════════════════════════════════════════════════

    async def supervisor_node(state: AnalyticsState) -> dict[str, Any]:
        """Routes user intent to the correct pipeline stage.

        Reads:
            messages               – conversation so far (trimmed: human + AI only)
            dataset_schema         – filter columns/values (injected into prompt)
            filters_applied        – current active filters
            themes_for_analysis    – extracted themes ready for analysis
            plan_tasks             – current execution plan
            analysis_objective     – confirmed objective

        Writes:
            next_agent             – which node to run next
            supervisor_decision    – routing decision string
            messages               – user-visible reply (answer/clarify/qna only)
            plan_tasks             – marks next step in-progress (execute decision)
        """
        ctx = _build_extra_context("supervisor", state, None)
        sys_prompt = agent_factory.parse_agent_md("supervisor").system_prompt + ctx

        slim_state = dict(state)
        slim_msgs = []
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                slim_msgs.append(msg)
            elif isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None) and msg.content:
                slim_msgs.append(msg)
        if len(slim_msgs) > MAX_SUPERVISOR_MSGS:
            slim_msgs = slim_msgs[:2] + slim_msgs[-(MAX_SUPERVISOR_MSGS - 2):]
        slim_state["messages"] = slim_msgs

        base, structured, last_msg = await _run_structured_node(
            "supervisor", supervisor_chain, SupervisorOutput, sys_prompt, slim_state,
        )

        if isinstance(structured, SupervisorOutput):
            _apply_supervisor(structured, state, base)
            _enforce_analysis_start_guard(state, base)
        elif last_msg:
            raise RuntimeError(
                f"[supervisor] Structured output failed — got {type(structured).__name__}."
            )

        if base.get("next_agent") == "user_checkpoint":
            msg = base.get("checkpoint_message", "Awaiting your input...")
            prompt = base.get("checkpoint_prompt", "Please provide input to continue.")
            interrupt({
                "type": base.get("pending_input_for", "supervisor_checkpoint"),
                "message": msg,
                "prompt": prompt,
            })
            base["next_agent"] = "supervisor"

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
            plan_steps_completed   – count of already-done steps
            analysis_objective     – confirmed/refined objective
            reasoning              – planner's reasoning text
        """
        ctx = _build_extra_context("planner", state, None)
        sys_prompt = agent_factory.parse_agent_md("planner").system_prompt + ctx

        planner_state = dict(state)
        scope_reply = state.get("analysis_scope_reply", "")
        planner_msg = f"Create an execution plan. Objective: {state.get('analysis_objective', '')}"
        if scope_reply:
            planner_msg += f"\nUser lens selection: {scope_reply}"
        planner_state["messages"] = [HumanMessage(content=planner_msg)]

        base, structured, _ = await _run_structured_node(
            "planner", planner_chain, PlannerOutput, sys_prompt, planner_state,
        )

        if not isinstance(structured, PlannerOutput):
            raise RuntimeError(
                f"[planner] Structured output failed — got {type(structured).__name__}."
            )

        new_tasks  = [t.model_dump() for t in structured.plan_tasks]
        existing   = state.get("plan_tasks", [])
        done_steps = [t for t in existing if t.get("status") == "done"]
        done_agents = {t.get("agent") for t in done_steps}
        new_tasks = [t for t in new_tasks if t.get("agent") not in done_agents]
        all_tasks  = done_steps + new_tasks

        _ALL_LENS_IDS_SET = {
            "digital_friction_agent", "operations_agent",
            "communication_agent", "policy_agent",
        }
        selected = [a for a in structured.selected_agents if a in _ALL_LENS_IDS_SET]
        if not selected:
            selected = sorted(_ALL_LENS_IDS_SET)

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
            messages               – user's filter specification
            dataset_path           – CSV path from config
            dataset_schema         – available column names / values
            analysis_objective     – context for bucket labelling

        Writes:
            filters_applied        – dict of column->value filters applied
            bucket_manifest_path   – path to bucket_manifest.json
            themes_for_analysis    – list of bucket names discovered
            filtered_parquet_path  – path to filtered parquet
            analysis_scope_reply   – user's dimension confirmation
            messages               – single clean summary

        Tools: load_dataset, filter_data, bucket_data, describe_filters
        """
        ctx = _build_extra_context("data_analyst", state, None)
        base, last_msg = await _run_react_node("data_analyst", agent_factory, ctx, state)

        _extract_data_analyst_state(state, base)

        da_data = _parse_json(_text(last_msg.content)) if last_msg else {}
        summary = da_data.get("response", _text(last_msg.content) if last_msg else "")
        if not isinstance(summary, str):
            summary = json.dumps(summary, indent=2, default=str)

        base["reasoning"] = [{"step_name": "Data Analyst", "step_text": summary}]
        if summary:
            base["messages"] = [AIMessage(content=summary)]

        # Interrupt for dimension confirmation after bucketing
        has_buckets = base.get("bucket_manifest_path") or state.get("bucket_manifest_path")
        already_confirmed = state.get("analysis_scope_reply")
        if has_buckets and not already_confirmed:
            # Build concise bucket summary from manifest
            manifest_path = base.get("bucket_manifest_path") or state.get("bucket_manifest_path", "")
            bucket_lines = []
            total_rows = 0
            if manifest_path and Path(manifest_path).exists():
                try:
                    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                    for b in manifest.get("buckets", []):
                        bname = b.get("bucket_name", b.get("bucket_id", "?"))
                        bcount = b.get("row_count", 0)
                        total_rows += bcount
                        bucket_lines.append(f"- **{bname}** ({bcount} rows)")
                except Exception:
                    pass
            filters = base.get("filters_applied") or state.get("filters_applied") or {}
            filter_desc = " and ".join(f"{k}={v}" for k, v in filters.items()) if filters else "all data"
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
                logger.info("data_analyst: reply doesn't match lens selection, routing to supervisor")
                base["next_agent"] = "supervisor"

        _advance_plan("data_analyst", state, base)
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # FRICTION LENS AGENTS  (4 agents + specialist, run in parallel inside friction_analysis)
    # ══════════════════════════════════════════════════════════════════════════

    async def _run_lens_node(
        agent_id: str,
        focused_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one lens agent and write its output to lens_outputs_dir/{bucket_id}_{agent_id}.md."""
        ctx = _build_extra_context(agent_id, focused_state, skill_loader)
        base, last_msg = await _run_react_node(agent_id, agent_factory, ctx, focused_state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""

        # Collect full response from messages
        full_response = "\n\n".join(
            _text(m.content) for m in base.get("messages", [])
            if hasattr(m, "content") and _text(m.content).strip()
        ) or summary

        # Write to lens_outputs_dir
        lens_outputs_dir = focused_state.get("lens_outputs_dir", "")
        bucket_id = str(focused_state.get("_focus_bucket_id", "all"))
        if lens_outputs_dir:
            out_path = Path(lens_outputs_dir) / f"{bucket_id}_{agent_id}.md"
            _write_file(out_path, full_response)

        display_name = agent_id.replace("_agent", "").replace("_", " ").title()
        base["reasoning"] = [{"step_name": display_name, "step_text": summary}]
        return base

    async def digital_friction_node(state: AnalyticsState) -> dict[str, Any]:
        return await _run_lens_node("digital_friction_agent", state)

    async def operations_node(state: AnalyticsState) -> dict[str, Any]:
        return await _run_lens_node("operations_agent", state)

    async def communication_node(state: AnalyticsState) -> dict[str, Any]:
        return await _run_lens_node("communication_agent", state)

    async def policy_node(state: AnalyticsState) -> dict[str, Any]:
        return await _run_lens_node("policy_agent", state)

    async def specialist_node(state: AnalyticsState) -> dict[str, Any]:
        return await _run_lens_node("specialist_agent", state)

    # ══════════════════════════════════════════════════════════════════════════
    # SYNTHESIZER
    # ══════════════════════════════════════════════════════════════════════════

    async def synthesizer_node(state: AnalyticsState) -> dict[str, Any]:
        """Aggregates lens outputs into cross-cutting themes and ranked findings.

        Reads:
            lens_outputs_dir        – directory of per-bucket per-lens markdown files
            selected_agents         – which friction lenses ran

        Writes:
            synthesis_path          – path to synthesis markdown file
            themes_for_analysis     – extracted theme names for supervisor context
            messages                – executive_narrative summary (user-visible)
        """
        ctx = _build_extra_context("synthesizer_agent", state, None)
        sys_prompt = agent_factory.parse_agent_md("synthesizer_agent").system_prompt + ctx

        base, structured, last_msg = await _run_structured_node(
            "synthesizer_agent", synthesizer_chain, SynthesizerOutput, sys_prompt, state,
        )

        if isinstance(structured, SynthesizerOutput):
            narrative     = structured.summary.executive_narrative
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

            synthesis_md = json.dumps(synthesis_data, indent=2, default=str)
            synthesis_path = _write_versioned_md(
                "synthesis", synthesis_md, {"agent": "synthesizer_agent"}
            )

            base.update({
                "synthesis_path":      synthesis_path,
                "themes_for_analysis": top_theme_names,
            })
            base["reasoning"] = [{"step_name": "Synthesizer Agent", "step_text": narrative}]
            if narrative:
                base["messages"] = [AIMessage(content=narrative)]
            logger.info("Synthesizer: %d findings, %d themes, synthesis_path=%s",
                        len(structured.findings), len(structured.themes), synthesis_path)

        elif last_msg:
            data = _parse_json(_text(last_msg.content))
            synthesis_data = {}
            if data.get("summary"):
                synthesis_data = dict(data["summary"])
            for key in ("decision", "confidence", "reasoning", "themes", "findings"):
                if key in data:
                    synthesis_data[key] = data[key]
            synthesis_md = json.dumps(synthesis_data, indent=2, default=str)
            synthesis_path = _write_versioned_md(
                "synthesis", synthesis_md, {"agent": "synthesizer_agent"}
            )
            base["synthesis_path"] = synthesis_path
            narrative = synthesis_data.get("executive_narrative", "")
            raw_text = _text(last_msg.content)
            narrative = narrative or (raw_text if not raw_text.startswith("{") else "Synthesis complete.")
            base["reasoning"] = [{"step_name": "Synthesizer Agent", "step_text": narrative}]
            if narrative:
                base["messages"] = [AIMessage(content=narrative)]

        return base

    # ══════════════════════════════════════════════════════════════════════════
    # COMPOSITE NODE: friction_analysis
    # Runs lens agents × buckets in parallel (asyncio.gather).
    # Adds specialist agent for matching domains.
    # Then two-pass synthesis.
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
                 Domain router adds specialist_agent for matching high-volume buckets.
                 All outputs written to lens_outputs_dir/{bucket_id}_{lens_id}.md.
        Phase 1: Per-lens aggregation — concatenate/summarize all bucket outputs per lens
                 into lens_outputs_dir/{lens_id}_synthesis.md (structural merge).
        Phase 2: Final synthesis — synthesizer reads from lens_outputs_dir and produces
                 the executive synthesis, themes, and ranked findings.

        Reads:  selected_agents, bucket_manifest_path
        Writes: lens_outputs_dir, synthesis_path, themes_for_analysis
        """
        import chainlit as cl

        selected = state.get("selected_agents", [])
        lens_ids = [a for a in selected if a in _ALL_LENS_IDS] if selected else list(_ALL_LENS_IDS)
        if not lens_ids:
            lens_ids = list(_ALL_LENS_IDS)
        lens_ids = list(dict.fromkeys(lens_ids))

        # Read bucket manifest
        manifest_path = state.get("bucket_manifest_path", "")
        manifest: dict[str, Any] = {}
        buckets: list[dict[str, Any]] = []
        if manifest_path and Path(manifest_path).exists():
            try:
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                buckets = manifest.get("buckets", [])
            except Exception:
                pass
        if not buckets:
            buckets = [{"bucket_id": "all", "bucket_name": "All Data", "row_count": 0}]

        bucket_ids = [b["bucket_id"] for b in buckets]
        # raw_buckets: {bucket_id: bucket_metadata} for summarization helpers
        raw_buckets: dict[str, Any] = {b["bucket_id"]: b for b in buckets}

        # Create lens_outputs_dir
        data_store = cl.user_session.get("data_store")
        if data_store:
            lens_dir = Path(data_store.base_dir) / "lens_outputs"
        else:
            lens_dir = Path(state.get("artifacts_dir", "/tmp")) / "lens_outputs"
        lens_dir.mkdir(parents=True, exist_ok=True)
        lens_outputs_dir = str(lens_dir)

        # Domain router: determine which buckets also get specialist agent
        specialist_bucket_ids: set[str] = set()
        for b in buckets:
            domain = b.get("primary_domain", "")
            row_count = b.get("row_count", 0)
            if domain in SPECIALIST_DOMAIN_TRIGGERS and row_count >= SPECIALIST_MIN_BUCKET_SIZE:
                specialist_bucket_ids.add(b["bucket_id"])

        total_buckets = len(bucket_ids)
        total_runs = len(lens_ids) * total_buckets + len(specialist_bucket_ids)
        per_agent_limit = max(1, MAX_MULTITHREADING_WORKERS // max(len(lens_ids), 1))
        semaphore = asyncio.Semaphore(MAX_MULTITHREADING_WORKERS)

        logger.info(
            "Friction analysis: %d lenses × %d buckets = %d runs + %d specialist runs "
            "(max %d workers)",
            len(lens_ids), total_buckets, len(lens_ids) * total_buckets,
            len(specialist_bucket_ids), MAX_MULTITHREADING_WORKERS,
        )

        # Per-agent semaphores
        agent_semaphores: dict[str, asyncio.Semaphore] = {
            lid: asyncio.Semaphore(per_agent_limit) for lid in lens_ids + ["specialist_agent"]
        }

        # Build sub_agents for UI
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

        async def _tracked_run(lens_id: str, bucket_id: str, coro: Any) -> Any:
            async with semaphore:
                async with agent_semaphores[lens_id]:
                    result = await coro
            completed_per_lens[lens_id] += 1
            done = completed_per_lens[lens_id]
            base_detail = FRICTION_SUB_AGENTS.get(lens_id, {}).get("detail", lens_id)
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
        run_combos: list[tuple[str, str]] = []  # (lens_id, bucket_id)

        for lens_id in lens_ids:
            for bucket in buckets:
                bucket_id = bucket["bucket_id"]
                bucket_name = bucket.get("bucket_name", bucket_id)
                focused_state = dict(state)
                focused_state["execution_trace"] = []
                focused_state["_focus_bucket_id"] = bucket_id
                focused_state["lens_outputs_dir"] = lens_outputs_dir
                focused_state["messages"] = [HumanMessage(content=(
                    f"Analyze bucket '{bucket_name}' for friction drivers. "
                    f"Analysis objective: {state.get('analysis_objective', 'Identify friction drivers')}"
                ))]
                coro = _LENS_NODE_MAP[lens_id](focused_state)
                run_tasks.append(_tracked_run(lens_id, bucket_id, coro))
                run_combos.append((lens_id, bucket_id))

        # Add specialist runs
        for bucket in buckets:
            bucket_id = bucket["bucket_id"]
            if bucket_id not in specialist_bucket_ids:
                continue
            bucket_name = bucket.get("bucket_name", bucket_id)
            specialist_skill = bucket.get("specialist_skill") or SPECIALIST_DOMAIN_TRIGGERS.get(
                bucket.get("primary_domain", ""), ""
            )
            focused_state = dict(state)
            focused_state["execution_trace"] = []
            focused_state["_focus_bucket_id"] = bucket_id
            focused_state["lens_outputs_dir"] = lens_outputs_dir
            focused_state["messages"] = [HumanMessage(content=(
                f"Provide specialist domain analysis for bucket '{bucket_name}'. "
                f"Analysis objective: {state.get('analysis_objective', 'Identify friction drivers')}"
            ))]

            async def _specialist_tracked(bucket_id=bucket_id, focused_state=focused_state):
                async with semaphore:
                    async with agent_semaphores["specialist_agent"]:
                        return await specialist_node(focused_state)

            run_tasks.append(_specialist_tracked())
            run_combos.append(("specialist_agent", bucket_id))

        results = await asyncio.gather(*run_tasks)

        # Build nested_md_paths: {lens_id: {bucket_id: path}}
        nested_md_paths: dict[str, dict[str, str]] = {lid: {} for lid in lens_ids}
        for (lens_id, bucket_id), _ in zip(run_combos, results):
            if lens_id == "specialist_agent":
                continue
            candidate = lens_dir / f"{bucket_id}_{lens_id}.md"
            nested_md_paths[lens_id][bucket_id] = str(candidate) if candidate.exists() else ""

        merged = _merge_parallel_outputs(list(results))
        merged["lens_outputs_dir"] = lens_outputs_dir
        logger.info("Friction analysis: merged %d runs, lenses=%s, buckets=%s",
                    len(results), lens_ids, bucket_ids)

        # ── Phase 1: per-lens aggregation ──
        use_summarization = _should_summarize_lens_outputs(nested_md_paths)
        phase1_label = "Per-lens summarization" if use_summarization else "Per-lens aggregation"
        logger.info("Friction analysis Phase 1: %s (summarize=%s)", phase1_label, use_summarization)

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

        for i, lid in enumerate(lens_ids):
            bucket_path_dict = nested_md_paths[lid]
            num_buckets = len(bucket_path_dict)

            if use_summarization and num_buckets > L2_BATCH_SIZE:
                lens_md = await _summarize_lens_buckets_with_llm(lid, bucket_path_dict, raw_buckets)
            elif use_summarization:
                lens_md = _summarize_lens_buckets(lid, bucket_path_dict, raw_buckets)
            else:
                parts = [f"# {lid} — Per-Bucket Analysis\n"]
                for bid in sorted(bucket_path_dict.keys()):
                    bpath = bucket_path_dict[bid]
                    bucket_name = raw_buckets.get(bid, {}).get("bucket_name", bid)
                    if bpath and Path(bpath).exists():
                        content = Path(bpath).read_text(encoding="utf-8")
                        parts.append(f"\n## Bucket: {bucket_name}\n{content}")
                    else:
                        parts.append(f"\n## Bucket: {bucket_name}\n(No output)\n")
                lens_md = "\n".join(parts)

            # Write per-lens synthesis file to lens_outputs_dir
            synthesis_file = lens_dir / f"{lid}_synthesis.md"
            _write_file(synthesis_file, lens_md)

            _set_sub_agent_status(
                sub_agents, "synthesizer_agent", status="in_progress",
                detail=f"{phase1_label} ({i + 1}/{len(lens_ids)})",
            )
            tasks = await _set_task_sub_agents_and_emit(
                tasks, agent_name="friction_analysis",
                sub_agents=sub_agents, task_status="in_progress",
            )

        logger.info("Friction analysis Phase 1 done: %d synthesis files in %s", len(lens_ids), lens_outputs_dir)

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
        synth_state["execution_trace"] = []
        synth_state["lens_outputs_dir"] = lens_outputs_dir
        synth_state["messages"] = [HumanMessage(content=(
            "Synthesize the friction lens analyses into themes. "
            "Produce executive narrative, ranked findings, and impact×ease scores. "
            f"Analysis objective: {state.get('analysis_objective', 'Identify friction drivers')}"
        ))]

        logger.info("Friction analysis Phase 2: running synthesizer | lens_outputs_dir=%s", lens_outputs_dir)
        synth_result = await synthesizer_node(synth_state)

        # Mark synthesizer done
        _set_sub_agent_status(
            sub_agents, "synthesizer_agent", status="done",
            detail="Cross-lens synthesis complete",
        )
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="friction_analysis",
            sub_agents=sub_agents, task_status="done",
        )

        final = _merge_state_deltas(
            merged, synth_result,
            list_keys={"execution_trace"},
            skip_keys={"messages"},
        )
        final["reasoning"]        = _build_friction_reasoning_entries(lens_ids, state, synth_result)
        final["messages"]         = synth_result.get("messages", [])
        final["plan_tasks"]       = tasks
        final["lens_outputs_dir"] = lens_outputs_dir

        _record_plan_progress(state, final, agent_name="friction_analysis")
        return final

    # ══════════════════════════════════════════════════════════════════════════
    # SOLUTIONING AGENT
    # ══════════════════════════════════════════════════════════════════════════

    async def solutioning_agent_node(state: AnalyticsState) -> dict[str, Any]:
        """Classifies friction findings against the solutions registry.

        Reads:
            synthesis_path          – path to synthesis JSON/markdown
            (solutions registry injected via _build_extra_context)

        Writes:
            classified_solutions_path – path to classified_solutions.json
            messages                  – brief summary
        """
        import chainlit as cl

        ctx = _build_extra_context("solutioning_agent", state, None)
        base, last_msg = await _run_react_node("solutioning_agent", agent_factory, ctx, state)

        # Extract JSON from the agent's last message and write to classified_solutions_path
        classified_path = ""
        if last_msg:
            content = _text(last_msg.content)
            classified_data = _parse_json(content)
            if not classified_data:
                # Try to use raw content as JSON payload
                classified_data = {"raw_output": content}
            data_store = cl.user_session.get("data_store")
            if data_store:
                classified_path = data_store.store_json(
                    "classified_solutions", classified_data,
                    {"agent": "solutioning_agent"},
                )
            else:
                classified_path = _write_versioned_md(
                    "classified_solutions",
                    json.dumps(classified_data, indent=2),
                    {"agent": "solutioning_agent"},
                )

        summary = _trunc(_text(last_msg.content), 200) if last_msg else "Solution classification complete."
        base["classified_solutions_path"] = classified_path
        base["reasoning"] = [{"step_name": "Solutioning Agent", "step_text": summary}]
        if summary:
            base["messages"] = [AIMessage(content=summary)]

        _advance_plan("solutioning_agent", state, base)
        logger.info("Solutioning agent: classified_solutions_path=%s", classified_path)
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # NARRATIVE AGENT
    # ══════════════════════════════════════════════════════════════════════════

    async def narrative_node(state: AnalyticsState) -> dict[str, Any]:
        """Writes the analytical narrative: exec summary, impact/ease matrix, recommendations.

        Reads:
            classified_solutions_path – classified solutions for narrative
            synthesis_path            – synthesis themes and findings
            filters_applied           – shown in report header

        Writes:
            narrative_path            – path to narrative markdown file
        """
        ctx = _build_extra_context("narrative_agent", state, None)
        base, last_msg = await _run_react_node("narrative_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""

        # Collect full markdown from all messages
        full_narrative = "\n\n".join(
            _text(m.content) for m in base.get("messages", [])
            if hasattr(m, "content") and _text(m.content).strip()
        ) or summary

        narrative_path = _write_versioned_md(
            "narrative", full_narrative, {"agent": "narrative_agent"}
        )
        base["narrative_path"] = narrative_path
        base["reasoning"] = [{"step_name": "Narrative Agent", "step_text": summary}]
        logger.info("Narrative: written to %s", narrative_path or "not written")
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # REPORT ANALYST
    # ══════════════════════════════════════════════════════════════════════════

    async def report_analyst_node(state: AnalyticsState) -> dict[str, Any]:
        """Delivers the final report: verifies artifacts exist, presents download links.

        Reads:
            messages               – "deliver report" instruction from supervisor
            artifacts_dir          – directory with PPTX, CSV, markdown artifacts

        Writes:
            messages               – final user-visible delivery message
        """
        ctx = _build_extra_context("report_analyst", state, None)
        base, last_msg = await _run_react_node("report_analyst", agent_factory, ctx, state)

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
            synthesis_path         – synthesis for grading

        Writes:
            critique_feedback      – full critique dict
            quality_score          – float 0-1
            messages               – "Grade: X | Score: Y" summary
        """
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

    # ══════════════════════════════════════════════════════════════════════════
    # QNA AGENT
    # ══════════════════════════════════════════════════════════════════════════

    async def qna_node(state: AnalyticsState) -> dict[str, Any]:
        """Answers user follow-up questions using the generated analysis report.

        Reads:
            messages               – user's question
            artifacts_dir          – contains complete_analysis.md

        Writes:
            messages               – answer to the user's question
        """
        ctx = _build_extra_context("qna_agent", state, None)
        base, last_msg = await _run_react_node("qna_agent", agent_factory, ctx, state)
        summary = _trunc(_text(last_msg.content), 200) if last_msg else ""
        base["reasoning"] = [{"step_name": "QnA Agent", "step_text": summary}]
        return base

    # ══════════════════════════════════════════════════════════════════════════
    # REPORT DRAFTS  (narrative + fixed deck blueprint)
    # ══════════════════════════════════════════════════════════════════════════

    async def report_drafts_node(state: AnalyticsState) -> dict[str, Any]:
        """Narrative agent + deterministic deck blueprint (no artifact writing).

        Reads:
            synthesis_path            – themes + findings for narrative + deck
            classified_solutions_path – solution classifications for narrative

        Writes:
            narrative_path            – markdown narrative file path
            blueprint_path            – slide blueprint JSON file path
            plan_steps_completed      – incremented
        """
        logger.info("Report drafts: starting narrative -> fixed deck blueprint")

        # Guard: require synthesis
        synthesis_path = state.get("synthesis_path", "")
        if not synthesis_path or not Path(synthesis_path).exists():
            raise RuntimeError(
                "Report drafts blocked: synthesis_path is missing or file not found. "
                "Run friction_analysis before generating report drafts."
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
        narrative_path = narrative_result.get("narrative_path", "")

        _set_sub_agent_status(sub_agents, "narrative_agent",  status="done")
        _set_sub_agent_status(sub_agents, "formatting_agent", status="in_progress")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="report_drafts",
            sub_agents=sub_agents, task_status="in_progress",
        )

        # --- Step 2: Fixed deck blueprint (deterministic, reads synthesis from file) ---
        synthesis: dict[str, Any] = {}
        if synthesis_path and Path(synthesis_path).exists():
            try:
                synthesis = json.loads(Path(synthesis_path).read_text(encoding="utf-8"))
            except Exception:
                pass

        # Extract findings from synthesis data
        findings = synthesis.get("findings", []) if isinstance(synthesis, list) else []
        if not findings and isinstance(synthesis, dict):
            findings = synthesis.get("findings", [])

        section_blueprints = _build_fixed_deck_blueprint(synthesis, findings)
        total_slides = sum(len(s.get("slides", [])) for s in section_blueprints)
        logger.info(
            "Report drafts: fixed deck blueprint built | %d slides across %d sections",
            total_slides, len(section_blueprints),
        )

        # Write blueprint to file
        blueprint_path = _write_versioned_md(
            "blueprint",
            json.dumps(section_blueprints, indent=2, default=str),
            {"agent": "formatting_agent", "total_slides": total_slides},
        )

        _set_sub_agent_status(sub_agents, "formatting_agent", status="done",
                              detail=f"Fixed deck: {total_slides} slides")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="report_drafts",
            sub_agents=sub_agents, task_status="done",
        )

        final = _merge_state_deltas(
            narrative_result,
            {"narrative_path": narrative_path, "blueprint_path": blueprint_path},
            list_keys={"execution_trace"},
            skip_keys={"messages"},
        )
        final["reasoning"]     = _build_report_reasoning_entries()
        final["messages"]      = [AIMessage(content=_build_executive_summary_message(narrative_path))]
        final["plan_tasks"]    = tasks
        final["narrative_path"] = narrative_path
        final["blueprint_path"] = blueprint_path

        _record_plan_progress(state, final, agent_name="report_drafts")
        return final

    # ══════════════════════════════════════════════════════════════════════════
    # ARTIFACT WRITER  (charts + PPTX + CSV + markdown)
    # ══════════════════════════════════════════════════════════════════════════

    async def artifact_writer_node(state: AnalyticsState) -> dict[str, Any]:
        """Generates report artifacts: charts, PPTX, CSV, markdown files.

        Reads:
            narrative_path         – markdown narrative file (from report_drafts)
            blueprint_path         – slide blueprint JSON file (from report_drafts)
            synthesis_path         – for chart data generation

        Writes:
            artifacts_dir          – directory containing all generated artifacts
            analysis_complete      – True (pipeline done)
        """
        logger.info("Artifact writer: generating charts, PPTX, CSV, markdown")

        sub_agents = [
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "artifact_writer_node", status="in_progress"),
        ]
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []), agent_name="artifact_writer",
            sub_agents=sub_agents, task_status="in_progress",
        )

        artifact_result = _run_section_artifact_writer(state)
        artifact_errors = _validate_artifact_paths(artifact_result)
        if artifact_errors:
            raise RuntimeError(f"artifact_writer failed validation: {artifact_errors}")

        artifacts_dir = artifact_result.get("artifacts_dir", "")
        logger.info("Artifact writer: created | artifacts_dir=%r", artifacts_dir)

        _set_sub_agent_status(sub_agents, "artifact_writer_node", status="done",
                              detail="Created PPTX, Word, CSV and markdown files.")
        tasks = await _set_task_sub_agents_and_emit(
            tasks, agent_name="artifact_writer",
            sub_agents=sub_agents, task_status="done",
        )

        final = dict(artifact_result)
        final["plan_tasks"] = tasks
        final["reasoning"] = [{"step_name": "Artifact Writer", "step_text": "Report artifacts generated."}]

        _record_plan_progress(state, final, agent_name="artifact_writer", mark_analysis_complete=True)
        return final

    # ══════════════════════════════════════════════════════════════════════════
    # PLAN DISPATCHER (deterministic — no LLM call)
    # ══════════════════════════════════════════════════════════════════════════

    async def plan_dispatcher_node(state: AnalyticsState) -> dict[str, Any]:
        """Deterministic plan execution: advance plan and route to next work node.

        No LLM call. Reads plan_tasks, marks the most recent in_progress task
        as done, promotes the next ready/todo task to in_progress, and sets
        next_agent for the conditional edge.

        OPT-5: if artifacts_dir already valid, skip report_analyst.

        Reads:  plan_tasks, artifacts_dir, next_agent
        Writes: plan_tasks, plan_steps_completed, plan_steps_total, next_agent,
                analysis_complete, phase
        """
        tasks = [dict(t) for t in state.get("plan_tasks", [])]

        # Respect explicit routing override from upstream node
        upstream_next = state.get("next_agent", "")
        if upstream_next in ("supervisor", "planner") and not tasks:
            logger.info("Plan dispatcher: upstream override next=%s (no plan)", upstream_next)
            return {
                "plan_tasks": [],
                "plan_steps_completed": 0,
                "plan_steps_total": 0,
                "next_agent": upstream_next,
            }

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

        # OPT-5: Skip report_analyst if artifacts_dir already valid
        if next_agent == "report_analyst":
            artifact_errors = _validate_artifact_paths({"artifacts_dir": state.get("artifacts_dir", "")})
            if not artifact_errors:
                for t in tasks:
                    if t.get("agent") == "report_analyst" and t.get("status") == "in_progress":
                        t["status"] = "done"
                        break
                done_count = len([t for t in tasks if t.get("status") == "done"])
                result["plan_tasks"] = tasks
                result["plan_steps_completed"] = done_count
                result["analysis_complete"] = True
                result["phase"] = "qa"
                result["next_agent"] = "__end__"
                next_agent = "__end__"
                logger.info("Plan dispatcher: skipped report_analyst (artifacts_dir valid)")

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
    graph.add_node("solutioning_agent", solutioning_agent_node)
    graph.add_node("report_drafts",     report_drafts_node)
    graph.add_node("artifact_writer",   artifact_writer_node)
    graph.add_node("critique",          critique_node)
    graph.add_node("report_analyst",    report_analyst_node)
    graph.add_node("qna",               qna_node)

    graph.add_edge(START, "supervisor")

    # data_analyst: route to planner when user confirmed lenses, else plan_dispatcher
    def route_from_data_analyst(state: AnalyticsState) -> str:
        if state.get("next_agent") == "planner":
            return "planner"
        return "plan_dispatcher"

    graph.add_conditional_edges("data_analyst", route_from_data_analyst, {
        "planner":          "planner",
        "plan_dispatcher":  "plan_dispatcher",
    })

    # Work nodes → plan_dispatcher (deterministic routing)
    graph.add_edge("friction_analysis", "plan_dispatcher")
    graph.add_edge("solutioning_agent", "plan_dispatcher")
    graph.add_edge("report_drafts",     "plan_dispatcher")
    graph.add_edge("artifact_writer",   "plan_dispatcher")
    graph.add_edge("critique",          "plan_dispatcher")

    # Planner → plan_dispatcher (dispatcher picks first task)
    graph.add_edge("planner",           "plan_dispatcher")

    # Final nodes → supervisor (for answer/qna routing)
    graph.add_edge("report_analyst",    "supervisor")

    # QnA ends the graph
    graph.add_edge("qna",               END)

    # Supervisor conditional routing
    def route_from_supervisor(state: AnalyticsState) -> str:
        next_agent = state.get("next_agent", "")
        route_map = {
            "data_analyst":      "data_analyst",
            "friction_analysis": "friction_analysis",
            "solutioning_agent": "solutioning_agent",
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
        "solutioning_agent": "solutioning_agent",
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
            "solutioning_agent": "solutioning_agent",
            "report_drafts":     "report_drafts",
            "artifact_writer":   "artifact_writer",
            "critique":          "critique",
            "report_analyst":    "report_analyst",
            "planner":           "planner",
            "__end__":           END,
        }
        return route_map.get(next_agent, "supervisor")

    graph.add_conditional_edges("plan_dispatcher", route_from_plan_dispatcher, {
        "data_analyst":      "data_analyst",
        "friction_analysis": "friction_analysis",
        "solutioning_agent": "solutioning_agent",
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

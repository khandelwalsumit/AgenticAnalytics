"""Main LangGraph StateGraph assembly."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import AIMessage, HumanMessage

from agents.nodes import make_agent_node, user_checkpoint_node
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

    Args:
        agent_factory: AgentFactory instance. Created with defaults if None.
        skill_loader: SkillLoader instance. Created with defaults if None.
        checkpointer: LangGraph checkpointer. Uses MemorySaver if None.

    Returns:
        Compiled LangGraph graph.
    """
    if agent_factory is None:
        agent_factory = AgentFactory(tool_registry=TOOL_REGISTRY)
    if skill_loader is None:
        skill_loader = SkillLoader()
    if checkpointer is None:
        checkpointer = MemorySaver()

    # -- Create node functions -------------------------------------------------
    supervisor_node = make_agent_node(agent_factory, "supervisor")
    planner_node = make_agent_node(agent_factory, "planner")
    data_analyst_node = make_agent_node(agent_factory, "data_analyst")
    report_analyst_node = make_agent_node(agent_factory, "report_analyst")
    critique_node = make_agent_node(agent_factory, "critique")

    # 4 friction lens agents (all get skill_loader for domain skill injection)
    digital_node = make_agent_node(
        agent_factory, "digital_friction_agent", skill_loader=skill_loader
    )
    operations_node = make_agent_node(
        agent_factory, "operations_agent", skill_loader=skill_loader
    )
    communication_node = make_agent_node(
        agent_factory, "communication_agent", skill_loader=skill_loader
    )
    policy_node = make_agent_node(
        agent_factory, "policy_agent", skill_loader=skill_loader
    )

    # Synthesizer
    synthesizer_node = make_agent_node(agent_factory, "synthesizer_agent")

    # Reporting agents
    narrative_node = make_agent_node(agent_factory, "narrative_agent")
    formatting_node = make_agent_node(agent_factory, "formatting_agent")

    # -- Composite node: friction_analysis ------------------------------------
    # Runs friction agents in parallel via asyncio.gather, then Synthesizer.
    # Respects selected_friction_agents from state for dimension selection.

    _ALL_LENS_IDS = [
        "digital_friction_agent", "operations_agent",
        "communication_agent", "policy_agent",
    ]
    _LENS_NODE_MAP = {
        "digital_friction_agent": digital_node,
        "operations_agent": operations_node,
        "communication_agent": communication_node,
        "policy_agent": policy_node,
    }

    async def friction_analysis_node(state: AnalyticsState) -> dict[str, Any]:
        """Run selected friction lens agents in parallel, then synthesize."""
        # Determine which agents to run based on user preference
        selected = state.get("selected_friction_agents", [])
        lens_ids = [a for a in selected if a in _ALL_LENS_IDS] if selected else list(_ALL_LENS_IDS)
        if not lens_ids:
            lens_ids = list(_ALL_LENS_IDS)
        lens_ids = list(dict.fromkeys(lens_ids))

        logger.info("Friction analysis: starting %d agents: %s", len(lens_ids), lens_ids)

        # --- Emit "in_progress" sub-agents to UI BEFORE running ---
        sub_agents_before = _make_sub_agent_entries(
            FRICTION_SUB_AGENTS, lens_ids, status="in_progress"
        )
        _ = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []),
            agent_name="friction_analysis",
            sub_agents=sub_agents_before,
            task_status="in_progress",
        )

        # Run selected lens agents concurrently
        node_fns = [_LENS_NODE_MAP[aid] for aid in lens_ids]
        results = await asyncio.gather(*(fn(state) for fn in node_fns))

        # Log what each agent produced
        for agent_id, result in zip(lens_ids, results):
            msg_count = len(result.get("messages", []))
            has_output = bool(result.get("digital_analysis") or result.get("operations_analysis")
                              or result.get("communication_analysis") or result.get("policy_analysis"))
            logger.info(
                "  Friction [%s]: msgs=%d, has_state_field=%s",
                agent_id, msg_count, has_output,
            )

        # Merge parallel outputs into state
        merged = _merge_parallel_outputs(list(results))
        logger.info(
            "  Merged friction outputs: keys=%s, msgs=%d",
            [k for k in merged if merged[k] and k != "messages"],
            len(merged.get("messages", [])),
        )

        # Persist friction lens outputs for synthesizer context and resume continuity.
        friction_output_files = _persist_friction_outputs(lens_ids, list(results))
        merged["friction_output_files"] = friction_output_files
        merged["expected_friction_lenses"] = lens_ids
        merged["missing_friction_lenses"] = [aid for aid in lens_ids if aid not in friction_output_files]

        # Build sub-agent entries with results (use static descriptions for clean UI)
        sub_agents = [
            _make_sub_agent_entry(FRICTION_SUB_AGENTS, agent_id, status="done")
            for agent_id in lens_ids
        ]
        # Add synthesizer as in_progress
        sub_agents.append(
            _make_sub_agent_entry(FRICTION_SUB_AGENTS, "synthesizer_agent", status="in_progress")
        )

        # --- Emit "lens done, synth in_progress" to UI ---
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []),
            agent_name="friction_analysis",
            sub_agents=sub_agents,
            task_status="in_progress",
        )

        # Build intermediate state for synthesizer and keep full message context.
        synth_state = dict(state)
        for k, v in merged.items():
            if k == "messages":
                continue  # handle separately
            synth_state[k] = v
        # Synthesizer needs original conversation + new tool messages for context
        synth_state["messages"] = list(state["messages"]) + merged.get("messages", [])
        # Pass friction output file keys for DataStore reads
        synth_state["friction_output_files"] = friction_output_files

        # Run synthesizer on merged outputs
        logger.info(
            "Friction analysis: running synthesizer | synth_state msgs=%d | "
            "digital=%s ops=%s comm=%s policy=%s",
            len(synth_state["messages"]),
            bool(synth_state.get("digital_analysis")),
            bool(synth_state.get("operations_analysis")),
            bool(synth_state.get("communication_analysis")),
            bool(synth_state.get("policy_analysis")),
        )
        synth_result = await synthesizer_node(synth_state)

        # Synthesis completeness is based on selected/expected lenses for this run.
        expected_lenses = merged.get("expected_friction_lenses", lens_ids)
        missing_lenses = merged.get("missing_friction_lenses", [])
        synthesis_payload = synth_result.get("synthesis_result", {})
        if isinstance(synthesis_payload, dict):
            synthesis_payload = dict(synthesis_payload)
            synthesis_payload["decision"] = "complete" if not missing_lenses else "incomplete"
            if missing_lenses:
                reason = str(synthesis_payload.get("reasoning", "")).strip()
                extra = f" Missing expected lens outputs: {', '.join(missing_lenses)}."
                synthesis_payload["reasoning"] = (reason + extra).strip() if reason else extra.strip()
            synth_result["synthesis_result"] = synthesis_payload
        synth_result["missing_friction_lenses"] = list(missing_lenses)
        synth_result["expected_friction_lenses"] = list(expected_lenses)

        # Offload synthesis_result to DataStore to prevent state bloat
        # and support deterministic report retries.
        import chainlit as cl
        data_store = cl.user_session.get("data_store")
        if data_store and synth_result.get("synthesis_result"):
            try:
                content = json.dumps(synth_result["synthesis_result"])
                key = data_store.store_text(
                    "synthesis_output",
                    content,
                    {"agent": "synthesizer_agent", "type": "synthesis_output"}
                )
                synth_result["synthesis_output_file"] = key
                logger.info("Friction analysis: stored synthesis_result in DataStore as %s", key)
            except Exception as e:
                logger.error("Friction analysis: failed to store synthesis_result: %s", e)

        logger.info(
            "Friction analysis: synthesizer done | findings=%d synthesis=%s msgs=%d",
            len(synth_result.get("findings", [])),
            bool(synth_result.get("synthesis_output_file")),
            len(synth_result.get("messages", [])),
        )

        # Update synthesizer sub-agent to done
        _set_sub_agent_status(
            sub_agents,
            "synthesizer_agent",
            status="done",
            detail="Consolidating cross-lens signals into an executive synthesis.",
        )
        tasks = await _set_task_sub_agents_and_emit(
            tasks,
            agent_name="friction_analysis",
            sub_agents=sub_agents,
            task_status="done",
        )

        # Build final delta: all analysis fields from sub-agents, only synth messages for UI
        final = _merge_state_deltas(
            merged,
            synth_result,
            list_keys={"execution_trace", "io_trace"},
            skip_keys={"messages"},
        )
        # Keep only curated reasoning text for clean user-visible tracing.
        final["reasoning"] = _build_friction_reasoning_entries(lens_ids, state, synth_result)

        # Only synthesizer message goes to UI (friction agent messages are internal)
        final["messages"] = synth_result.get("messages", [])
        final["plan_tasks"] = tasks

        # Advance plan_steps_completed for this composite node
        _record_plan_progress(state, final, agent_name="friction_analysis")

        return final

    # -- Composite node: report_generation ------------------------------------
    # Runs Narrative + Formatting (structured) and then deterministic artifact writer.
    async def report_generation_node(state: AnalyticsState) -> dict[str, Any]:
        """Run narrative, formatting blueprint, then deterministic artifact writing."""
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
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "narrative_agent", status="in_progress"),
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "formatting_agent", status="ready"),
            _make_sub_agent_entry(REPORTING_SUB_AGENTS, "artifact_writer_node", status="ready"),
        ]
        tasks = await _set_task_sub_agents_and_emit(
            state.get("plan_tasks", []),
            agent_name="report_generation",
            sub_agents=sub_agents,
            task_status="in_progress",
        )

        narrative_state = dict(state)
        narrative_state["messages"] = [HumanMessage(content=(
            "Generate the narrative markdown now with explicit slide boundary tags. "
            "You must call get_findings_summary before finalizing."
        ))]
        narrative_result = await _run_agent_with_retries(
            agent_id="narrative_agent",
            node_fn=narrative_node,
            base_state=narrative_state,
            required_tools=["get_findings_summary"],
            validator=_validate_narrative,
        )

        _set_sub_agent_status(sub_agents, "narrative_agent", status="done")
        _set_sub_agent_status(sub_agents, "formatting_agent", status="in_progress")
        tasks = await _set_task_sub_agents_and_emit(
            tasks,
            agent_name="report_generation",
            sub_agents=sub_agents,
            task_status="in_progress",
        )

        fmt_state = dict(state)
        merged_for_formatting = _merge_parallel_outputs([narrative_result])
        for k, v in merged_for_formatting.items():
            if k == "messages":
                continue
            fmt_state[k] = v
        fmt_state["messages"] = [HumanMessage(content=(
            "Parse narrative markdown and create the slide blueprint JSON with chart placeholders. "
            "Do not call export tools."
        ))]

        try:
            fmt_result = await _run_agent_with_retries(
                agent_id="formatting_agent",
                node_fn=formatting_node,
                base_state=fmt_state,
                required_tools=[],
                validator=_validate_formatting_blueprint,
                max_attempts=2,
            )
        except Exception as fmt_error:
            fallback_blueprint = _build_fallback_formatting_from_narrative_markdown(
                str(narrative_result.get("narrative_output", {}).get("full_response", ""))
            )
            fallback_json = json.dumps(fallback_blueprint, indent=2)
            fmt_result = {
                "messages": [AIMessage(content=fallback_json)],
                "formatting_output": {
                    "output": fallback_json[:200],
                    "full_response": fallback_json,
                    "agent": "formatting_agent",
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

        _set_sub_agent_status(sub_agents, "formatting_agent", status="done")
        _set_sub_agent_status(sub_agents, "artifact_writer_node", status="in_progress")
        tasks = await _set_task_sub_agents_and_emit(
            tasks,
            agent_name="report_generation",
            sub_agents=sub_agents,
            task_status="in_progress",
        )

        artifact_result = _run_artifact_writer_node(state, narrative_result, fmt_result)
        artifact_errors = _validate_artifact_paths(artifact_result)
        if artifact_errors:
            raise RuntimeError(
                "artifact_writer_node failed validation: "
                f"{artifact_errors}"
            )
        logger.info(
            "Report generation: artifacts created | report=%r markdown=%r data=%r",
            artifact_result.get("report_file_path", ""),
            artifact_result.get("markdown_file_path", ""),
            artifact_result.get("data_file_path", ""),
        )

        _set_sub_agent_status(
            sub_agents,
            "artifact_writer_node",
            status="done",
            detail="Creating PPT, data and md files.",
        )
        tasks = await _set_task_sub_agents_and_emit(
            tasks,
            agent_name="report_generation",
            sub_agents=sub_agents,
            task_status="done",
        )

        final = _merge_state_deltas(
            narrative_result,
            fmt_result,
            artifact_result,
            list_keys={"execution_trace", "io_trace"},
            skip_keys={"messages"},
        )

        final["reasoning"] = _build_report_reasoning_entries()
        final["messages"] = [AIMessage(content=_build_executive_summary_message(final.get("narrative_output", {})))]
        final["plan_tasks"] = tasks

        _record_plan_progress(
            state,
            final,
            agent_name="report_generation",
            mark_analysis_complete=True,
        )

        return final

    # -- Build graph -----------------------------------------------------------
    graph = StateGraph(AnalyticsState)

    # Add nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    graph.add_node("data_analyst", data_analyst_node)
    graph.add_node("report_analyst", report_analyst_node)
    graph.add_node("critique", critique_node)
    graph.add_node("user_checkpoint", user_checkpoint_node)

    # Composite subgraph nodes (internal orchestration)
    graph.add_node("friction_analysis", friction_analysis_node)
    graph.add_node("report_generation", report_generation_node)

    # -- Entry edge ------------------------------------------------------------
    graph.add_edge(START, "supervisor")

    # -- Supervisor routing (conditional) --------------------------------------
    def route_from_supervisor(state: AnalyticsState) -> str:
        """Route based on supervisor's next_agent decision.

        The supervisor sets next_agent via structured JSON decisions:
        - answer/clarify -> END (response already in messages)
        - extract -> data_analyst
        - analyse -> planner
        - execute -> follows plan_tasks (may trigger subgraphs)
        - friction_analysis -> composite friction node
        - report_generation -> composite reporting node
        """
        next_agent = state.get("next_agent", "")

        route_map = {
            "friction_analysis": "friction_analysis",
            "report_generation": "report_generation",
            "data_analyst": "data_analyst",
            "planner": "planner",
            "report_analyst": "report_analyst",
            "critique": "critique",
            "user_checkpoint": "user_checkpoint",
            "__end__": END,
        }
        return route_map.get(next_agent, END)

    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "friction_analysis": "friction_analysis",
            "report_generation": "report_generation",
            "data_analyst": "data_analyst",
            "planner": "planner",
            "report_analyst": "report_analyst",
            "critique": "critique",
            "user_checkpoint": "user_checkpoint",
            END: END,
        },
    )

    # -- Composite nodes return to Supervisor ----------------------------------
    graph.add_edge("friction_analysis", "supervisor")
    graph.add_edge("report_generation", "supervisor")

    # -- Direct agent -> Supervisor return edges --------------------------------
    graph.add_edge("data_analyst", "supervisor")
    graph.add_edge("planner", "supervisor")
    graph.add_edge("report_analyst", "supervisor")
    graph.add_edge("critique", "supervisor")

    # -- User checkpoint -> Supervisor (after user responds) --------------------
    graph.add_edge("user_checkpoint", "supervisor")

    # -- Compile with checkpoint interrupt -------------------------------------
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["user_checkpoint"],
    )
    # Safety: explicit recursion limit to prevent infinite loops
    compiled.recursion_limit = 25

    return compiled




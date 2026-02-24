"""Main LangGraph StateGraph assembly.

Defines the full analytics pipeline graph with:
- Supervisor (intent routing + plan execution)
- Planner (creates execution plans)
- Data Analyst (filter mapping + data prep)
- Report Analyst, Critique nodes
- Friction Analysis composite node (4 parallel lens agents + Synthesizer via asyncio.gather)
- Report Generation composite node (Narrative + DataViz in parallel + Formatting via asyncio.gather)
- User checkpoint interrupts

Parallelism uses asyncio.gather (no LangGraph Send API).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.nodes import (
    make_agent_node,
    user_checkpoint_node,
)
from agents.state import AnalyticsState
from core.agent_factory import AgentFactory
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY

import chainlit as cl
from ui.components import sync_task_list

logger = logging.getLogger("agenticanalytics.graph")


# -- Sub-agent catalog (drives TaskList UI) ------------------------------------
# Each entry maps agent_id → {title, detail} for display in the Chainlit task list.

FRICTION_SUB_AGENTS = {
    "digital_friction_agent": {
        "title": "Digital Friction Agent",
        "detail": "Digital product & UX gap analysis",
    },
    "operations_agent": {
        "title": "Operations Agent",
        "detail": "Process & SLA breakdown analysis",
    },
    "communication_agent": {
        "title": "Communication Agent",
        "detail": "Notification & expectation gap analysis",
    },
    "policy_agent": {
        "title": "Policy Agent",
        "detail": "Regulatory & governance constraint analysis",
    },
    "synthesizer_agent": {
        "title": "Synthesizer Agent",
        "detail": "Cross-lens root cause synthesis & ranking",
    },
}

REPORTING_SUB_AGENTS = {
    "narrative_agent": {
        "title": "Narrative Agent",
        "detail": "Slide deck structure & story design",
    },
    "dataviz_agent": {
        "title": "DataViz Agent",
        "detail": "Chart generation via code execution",
    },
    "formatting_agent": {
        "title": "Formatting Agent",
        "detail": "PPTX + Markdown + CSV assembly",
    },
}


def _set_task_sub_agents(
    tasks: list[dict[str, Any]],
    *,
    agent_name: str,
    sub_agents: list[dict[str, Any]],
    task_status: str | None = None,
) -> list[dict[str, Any]]:
    """Update a task's sub_agents list and optionally its status.

    Finds the task whose ``agent`` field matches *agent_name* and sets its
    ``sub_agents`` list. Returns the updated tasks list (mutates in place).
    """
    updated = [dict(t) for t in tasks]
    for task in updated:
        if task.get("agent") != agent_name:
            continue
        if task_status is not None:
            task["status"] = task_status
        task["sub_agents"] = sub_agents
        return updated
    return updated


def _make_sub_agent_entries(
    catalog: dict[str, dict[str, str]],
    agent_ids: list[str],
    status: str = "in_progress",
) -> list[dict[str, Any]]:
    """Build sub_agent dicts from the catalog for given agent IDs."""
    return [
        {
            "id": agent_id,
            "title": catalog[agent_id]["title"],
            "detail": catalog[agent_id]["detail"],
            "status": status,
        }
        for agent_id in agent_ids
        if agent_id in catalog
    ]


def _merge_parallel_outputs(
    base_state: dict[str, Any],
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge multiple parallel agent outputs into a single state delta.

    Rules:
    - messages: concatenate all
    - reasoning: concatenate all
    - execution_trace: concatenate all
    - io_trace: concatenate all
    - Dedicated state fields (digital_analysis, etc.): take from whichever output has them
    - Other fields: last writer wins
    """
    merged: dict[str, Any] = {}

    list_fields = {"messages", "reasoning", "execution_trace", "io_trace"}
    for output in outputs:
        for key, value in output.items():
            if key in list_fields:
                merged.setdefault(key, [])
                if isinstance(value, list):
                    merged[key].extend(value)
                else:
                    merged[key].append(value)
            else:
                merged[key] = value

    return merged


async def _emit_task_list_update(tasks: list[dict[str, Any]]) -> None:
    """Push an intermediate TaskList update to Chainlit UI."""
    task_list: cl.TaskList | None = cl.user_session.get("task_list")
    task_list = await sync_task_list(task_list, tasks)
    cl.user_session.set("task_list", task_list)

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
    dataviz_node = make_agent_node(agent_factory, "dataviz_agent")
    formatting_node = make_agent_node(agent_factory, "formatting_agent")

    # -- Composite node: friction_analysis ------------------------------------
    # Runs 4 friction agents in parallel via asyncio.gather, then Synthesizer.
    async def friction_analysis_node(state: AnalyticsState) -> dict[str, Any]:
        """Run 4 friction lens agents in parallel, then synthesize."""
        logger.info("Friction analysis: starting 4 parallel agents")

        lens_ids = [
            "digital_friction_agent", "operations_agent",
            "communication_agent", "policy_agent",
        ]

        # --- Emit "in_progress" sub-agents to UI BEFORE running ---
        sub_agents_before = _make_sub_agent_entries(
            FRICTION_SUB_AGENTS, lens_ids, status="in_progress"
        )
        tasks_before = _set_task_sub_agents(
            state.get("plan_tasks", []),
            agent_name="friction_analysis",
            sub_agents=sub_agents_before,
            task_status="in_progress",
        )
        await _emit_task_list_update(tasks_before)

        # Run all 4 lens agents concurrently
        results = await asyncio.gather(
            digital_node(state),
            operations_node(state),
            communication_node(state),
            policy_node(state),
        )

        # Merge parallel outputs into state
        merged = _merge_parallel_outputs(state, list(results))

        # Build sub-agent entries with results
        sub_agents = []
        for agent_id, result in zip(lens_ids, results):
            meta = FRICTION_SUB_AGENTS[agent_id]
            output_summary = ""
            for r in result.get("reasoning", []):
                output_summary = r.get("step_text", "")
            sub_agents.append({
                "id": agent_id,
                "title": meta["title"],
                "detail": output_summary[:120] if output_summary else meta["detail"],
                "status": "done",
            })
        # Add synthesizer as in_progress
        sub_agents.append({
            "id": "synthesizer_agent",
            "title": FRICTION_SUB_AGENTS["synthesizer_agent"]["title"],
            "detail": FRICTION_SUB_AGENTS["synthesizer_agent"]["detail"],
            "status": "in_progress",
        })

        # --- Emit "lens done, synth in_progress" to UI ---
        tasks = _set_task_sub_agents(
            state.get("plan_tasks", []),
            agent_name="friction_analysis",
            sub_agents=sub_agents,
            task_status="in_progress",
        )
        await _emit_task_list_update(tasks)

        # Build intermediate state for synthesizer
        synth_state = dict(state)
        synth_state.update(merged)

        # Run synthesizer on merged outputs
        logger.info("Friction analysis: running synthesizer")
        synth_result = await synthesizer_node(synth_state)

        # Update synthesizer sub-agent to done
        synth_summary = ""
        for r in synth_result.get("reasoning", []):
            synth_summary = r.get("step_text", "")
        sub_agents[-1]["status"] = "done"
        sub_agents[-1]["detail"] = synth_summary[:120] if synth_summary else sub_agents[-1]["detail"]

        tasks = _set_task_sub_agents(
            tasks,
            agent_name="friction_analysis",
            sub_agents=sub_agents,
            task_status="done",
        )

        # Merge synthesizer output into final delta
        final = _merge_parallel_outputs(synth_state, [merged, synth_result])
        final["plan_tasks"] = tasks
        return final

    # -- Composite node: report_generation ------------------------------------
    # Runs Narrative + DataViz in parallel via asyncio.gather, then Formatting.
    async def report_generation_node(state: AnalyticsState) -> dict[str, Any]:
        """Run narrative + dataviz in parallel, then formatting."""
        logger.info("Report generation: starting narrative + dataviz in parallel")

        parallel_ids = ["narrative_agent", "dataviz_agent"]

        # --- Emit "in_progress" sub-agents to UI BEFORE running ---
        sub_agents_before = _make_sub_agent_entries(
            REPORTING_SUB_AGENTS, parallel_ids, status="in_progress"
        )
        tasks_before = _set_task_sub_agents(
            state.get("plan_tasks", []),
            agent_name="report_generation",
            sub_agents=sub_agents_before,
            task_status="in_progress",
        )
        await _emit_task_list_update(tasks_before)

        # Run narrative and dataviz concurrently
        results = await asyncio.gather(
            narrative_node(state),
            dataviz_node(state),
        )

        # Merge parallel outputs
        merged = _merge_parallel_outputs(state, list(results))

        # Build sub-agent entries with parallel results
        sub_agents = []
        for agent_id, result in zip(parallel_ids, results):
            meta = REPORTING_SUB_AGENTS[agent_id]
            output_summary = ""
            for r in result.get("reasoning", []):
                output_summary = r.get("step_text", "")
            sub_agents.append({
                "id": agent_id,
                "title": meta["title"],
                "detail": output_summary[:120] if output_summary else meta["detail"],
                "status": "done",
            })
        # Add formatting as in_progress
        fmt_meta = REPORTING_SUB_AGENTS["formatting_agent"]
        sub_agents.append({
            "id": "formatting_agent",
            "title": fmt_meta["title"],
            "detail": fmt_meta["detail"],
            "status": "in_progress",
        })

        # --- Emit "parallel done, formatting in_progress" to UI ---
        tasks = _set_task_sub_agents(
            state.get("plan_tasks", []),
            agent_name="report_generation",
            sub_agents=sub_agents,
            task_status="in_progress",
        )
        await _emit_task_list_update(tasks)

        # Build intermediate state for formatting
        fmt_state = dict(state)
        fmt_state.update(merged)

        # Run formatting agent on merged outputs
        logger.info("Report generation: running formatting agent")
        fmt_result = await formatting_node(fmt_state)

        # Update formatting sub-agent to done
        fmt_summary = ""
        for r in fmt_result.get("reasoning", []):
            fmt_summary = r.get("step_text", "")
        sub_agents[-1]["status"] = "done"
        sub_agents[-1]["detail"] = fmt_summary[:120] if fmt_summary else sub_agents[-1]["detail"]

        tasks = _set_task_sub_agents(
            tasks,
            agent_name="report_generation",
            sub_agents=sub_agents,
            task_status="done",
        )

        # Merge formatting output into final delta
        final = _merge_parallel_outputs(fmt_state, [merged, fmt_result])
        final["plan_tasks"] = tasks
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

    # Composite subgraph nodes (internal parallelism via asyncio.gather)
    graph.add_node("friction_analysis", friction_analysis_node)
    graph.add_node("report_generation", report_generation_node)

    # -- Entry edge ------------------------------------------------------------
    graph.add_edge(START, "supervisor")

    # -- Supervisor routing (conditional) --------------------------------------
    def route_from_supervisor(state: AnalyticsState) -> str:
        """Route based on supervisor's next_agent decision.

        The supervisor sets next_agent via structured JSON decisions:
        - answer/clarify → END (response already in messages)
        - extract → data_analyst
        - analyse → planner
        - execute → follows plan_tasks (may trigger subgraphs)
        - friction_analysis → composite friction node
        - report_generation → composite reporting node
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

    # -- Direct agent → Supervisor return edges --------------------------------
    graph.add_edge("data_analyst", "supervisor")
    graph.add_edge("planner", "supervisor")
    graph.add_edge("report_analyst", "supervisor")
    graph.add_edge("critique", "supervisor")

    # -- User checkpoint → Supervisor (after user responds) --------------------
    graph.add_edge("user_checkpoint", "supervisor")

    # -- Compile with checkpoint interrupt -------------------------------------
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["user_checkpoint"],
    )
    # Safety: explicit recursion limit to prevent infinite loops
    compiled.recursion_limit = 25

    return compiled

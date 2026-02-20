"""Main LangGraph StateGraph assembly.

Defines the full analytics pipeline graph with:
- Supervisor, Data Analyst, Business Analyst, Report Analyst, Critique nodes
- Scope Detector for Q&A phase routing
- User checkpoint interrupts
- Conditional edges for routing and phase management
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.nodes import (
    make_agent_node,
    scope_detector_node,
    user_checkpoint_node,
)
from agents.state import AnalyticsState
from core.agent_factory import AgentFactory
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY


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
    data_analyst_node = make_agent_node(agent_factory, "data_analyst")
    business_analyst_node = make_agent_node(
        agent_factory, "business_analyst", skill_loader=skill_loader
    )
    report_analyst_node = make_agent_node(agent_factory, "report_analyst")
    critique_node = make_agent_node(agent_factory, "critique")

    # -- Build graph -----------------------------------------------------------
    graph = StateGraph(AnalyticsState)

    # Add nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("data_analyst", data_analyst_node)
    graph.add_node("business_analyst", business_analyst_node)
    graph.add_node("report_analyst", report_analyst_node)
    graph.add_node("critique", critique_node)
    graph.add_node("scope_detector", scope_detector_node)
    graph.add_node("user_checkpoint", user_checkpoint_node)

    # -- Entry edge ------------------------------------------------------------
    graph.add_edge(START, "supervisor")

    # -- Supervisor routing (conditional) --------------------------------------
    def route_from_supervisor(state: AnalyticsState) -> str:
        """Route based on supervisor's next_agent decision."""
        phase = state.get("phase", "analysis")

        # In Q&A mode, route through scope detector first
        if phase == "qa" and state.get("analysis_complete", False):
            return "scope_detector"

        next_agent = state.get("next_agent", "")

        if next_agent == "data_analyst":
            return "data_analyst"
        elif next_agent == "business_analyst":
            return "business_analyst"
        elif next_agent == "report_analyst":
            return "report_analyst"
        elif next_agent == "critique":
            return "critique"
        elif next_agent == "user_checkpoint":
            return "user_checkpoint"
        elif next_agent == "__end__":
            return END
        else:
            return END

    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "data_analyst": "data_analyst",
            "business_analyst": "business_analyst",
            "report_analyst": "report_analyst",
            "critique": "critique",
            "scope_detector": "scope_detector",
            "user_checkpoint": "user_checkpoint",
            END: END,
        },
    )

    # -- Scope Detector routing ------------------------------------------------
    def route_from_scope_detector(state: AnalyticsState) -> str:
        """Route based on scope detection result."""
        next_agent = state.get("next_agent", "")
        if next_agent == "__end__":
            return END
        return "supervisor"

    graph.add_conditional_edges(
        "scope_detector",
        route_from_scope_detector,
        {"supervisor": "supervisor", END: END},
    )

    # -- Agent → Supervisor return edges ---------------------------------------
    graph.add_edge("data_analyst", "supervisor")
    graph.add_edge("business_analyst", "supervisor")
    graph.add_edge("report_analyst", "supervisor")
    graph.add_edge("critique", "supervisor")

    # -- User checkpoint → Supervisor (after user responds) --------------------
    graph.add_edge("user_checkpoint", "supervisor")

    # -- Compile with checkpoint interrupt -------------------------------------
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["user_checkpoint"],
    )

    return compiled

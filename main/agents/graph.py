"""Main LangGraph StateGraph assembly.

Defines the full analytics pipeline graph with:
- Supervisor (intent routing + plan execution)
- Planner (creates execution plans)
- Data Analyst (filter mapping + data prep)
- Report Analyst, Critique nodes
- 4 parallel friction lens agents (Digital, Operations, Communication, Policy)
- Synthesizer for root-cause merging
- 3 reporting agents (Narrative, DataViz, Formatting)
- User checkpoint interrupts
- Send API fan-out for parallel analysis and reporting subgraphs
"""

from __future__ import annotations

from typing import Any, Union

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents.nodes import (
    make_agent_node,
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

    # -- Build graph -----------------------------------------------------------
    graph = StateGraph(AnalyticsState)

    # Add all nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    graph.add_node("data_analyst", data_analyst_node)
    graph.add_node("report_analyst", report_analyst_node)
    graph.add_node("critique", critique_node)
    graph.add_node("user_checkpoint", user_checkpoint_node)

    # Friction lens agents
    graph.add_node("digital_friction_agent", digital_node)
    graph.add_node("operations_agent", operations_node)
    graph.add_node("communication_agent", communication_node)
    graph.add_node("policy_agent", policy_node)
    graph.add_node("synthesizer_agent", synthesizer_node)

    # Reporting agents
    graph.add_node("narrative_agent", narrative_node)
    graph.add_node("dataviz_agent", dataviz_node)
    graph.add_node("formatting_agent", formatting_node)

    # -- Entry edge ------------------------------------------------------------
    graph.add_edge(START, "supervisor")

    # -- Supervisor routing (conditional) --------------------------------------
    def route_from_supervisor(
        state: AnalyticsState,
    ) -> Union[str, list[Send]]:
        """Route based on supervisor's next_agent decision.

        The supervisor sets next_agent via structured JSON decisions:
        - answer/clarify → END (response already in messages)
        - extract → data_analyst
        - analyse → planner
        - execute → follows plan_tasks (may trigger subgraphs)

        Returns Send objects for parallel fan-out (friction_analysis,
        report_generation) or a string for single-agent routing.
        """
        next_agent = state.get("next_agent", "")

        # Fan-out: 4 parallel friction agents
        if next_agent == "friction_analysis":
            return [
                Send("digital_friction_agent", state),
                Send("operations_agent", state),
                Send("communication_agent", state),
                Send("policy_agent", state),
            ]

        # Fan-out: Narrative + DataViz in parallel
        if next_agent == "report_generation":
            return [
                Send("narrative_agent", state),
                Send("dataviz_agent", state),
            ]

        # Single-agent routing
        route_map = {
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
            "data_analyst": "data_analyst",
            "planner": "planner",
            "report_analyst": "report_analyst",
            "critique": "critique",
            "user_checkpoint": "user_checkpoint",
            "digital_friction_agent": "digital_friction_agent",
            "operations_agent": "operations_agent",
            "communication_agent": "communication_agent",
            "policy_agent": "policy_agent",
            "narrative_agent": "narrative_agent",
            "dataviz_agent": "dataviz_agent",
            END: END,
        },
    )

    # -- Analysis subgraph edges -----------------------------------------------
    # All 4 friction agents converge at Synthesizer
    graph.add_edge("digital_friction_agent", "synthesizer_agent")
    graph.add_edge("operations_agent", "synthesizer_agent")
    graph.add_edge("communication_agent", "synthesizer_agent")
    graph.add_edge("policy_agent", "synthesizer_agent")
    # Synthesizer returns to Supervisor
    graph.add_edge("synthesizer_agent", "supervisor")

    # -- Reporting subgraph edges ----------------------------------------------
    # Narrative + DataViz converge at Formatting
    graph.add_edge("narrative_agent", "formatting_agent")
    graph.add_edge("dataviz_agent", "formatting_agent")
    # Formatting returns to Supervisor
    graph.add_edge("formatting_agent", "supervisor")

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

    return compiled

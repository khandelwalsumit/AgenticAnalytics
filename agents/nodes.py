"""Node functions for each agent in the analytics graph.

Each node is a thin async wrapper that:
1. Records start time for ExecutionTrace
2. Invokes the agent (via AgentFactory or direct LLM call)
3. Updates state with results and trace info
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents.state import AnalyticsState, ExecutionTrace, ScopeDecision
from core.agent_factory import AgentFactory
from core.llm import get_llm
from core.skill_loader import SkillLoader


# ------------------------------------------------------------------
# Scope Detector (lightweight classification — not a full agent)
# ------------------------------------------------------------------


class ScopeDecisionModel(BaseModel):
    """Structured output for scope detection."""

    in_scope: bool = Field(description="Whether the question is within the current analysis scope")
    reason: str = Field(description="Brief explanation of why the question is in or out of scope")


SCOPE_DETECTOR_PROMPT = """You are a scope detector for a customer experience analytics system.
You determine whether a user's follow-up question falls within the scope of the completed analysis.

## Current Analysis Scope
Dataset: {dataset_path}
Filters applied: {filters}
Skills used: {skills_used}
Buckets created: {buckets_created}
Focus column: {focus_column}

## Rules
IN-SCOPE: Questions that drill into existing findings, ask for clarification,
request comparisons within the analyzed data, or want different views of
already-bucketed data.

OUT-OF-SCOPE: Requests requiring new data, different filters not already applied,
or a fundamentally different analysis focus.

Determine if the following question is in-scope or out-of-scope."""


async def scope_detector_node(state: AnalyticsState) -> dict[str, Any]:
    """Lightweight classification node using structured output."""
    scope = state.get("analysis_scope", {})
    messages = state["messages"]
    last_message = messages[-1] if messages else None

    if not last_message:
        return {"next_agent": "supervisor"}

    prompt = SCOPE_DETECTOR_PROMPT.format(
        dataset_path=scope.get("dataset_path", "N/A"),
        filters=scope.get("filters", {}),
        skills_used=scope.get("skills_used", []),
        buckets_created=scope.get("buckets_created", []),
        focus_column=scope.get("focus_column", "N/A"),
    )

    llm = get_llm(temperature=0.0, max_tokens=256)
    structured_llm = llm.with_structured_output(ScopeDecisionModel)

    question = last_message.content if hasattr(last_message, "content") else str(last_message)
    result = await structured_llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=question),
    ])

    if result.in_scope:
        return {
            "next_agent": "supervisor",
            "agent_reasoning": state.get("agent_reasoning", []) + [{
                "step_name": "Scope Detector",
                "step_text": f"In-scope: {result.reason}",
                "agent": "scope_detector",
            }],
        }
    else:
        # Out-of-scope: add a message explaining and suggest new chat
        return {
            "next_agent": "__end__",
            "messages": [AIMessage(content=(
                f"This question falls outside the current analysis scope.\n\n"
                f"**Reason:** {result.reason}\n\n"
                f"The current analysis covers: {', '.join(scope.get('skills_used', []))}\n"
                f"with filters: {scope.get('filters', {})}\n\n"
                f"To explore this topic, please start a **New Chat** with a fresh analysis scope."
            ))],
            "agent_reasoning": state.get("agent_reasoning", []) + [{
                "step_name": "Scope Detector",
                "step_text": f"Out-of-scope: {result.reason}",
                "agent": "scope_detector",
            }],
        }


# ------------------------------------------------------------------
# User Checkpoint node
# ------------------------------------------------------------------


async def user_checkpoint_node(state: AnalyticsState) -> dict[str, Any]:
    """Checkpoint node — graph pauses here for user input via interrupt_before."""
    return {
        "requires_user_input": True,
        "agent_reasoning": state.get("agent_reasoning", []) + [{
            "step_name": "User Checkpoint",
            "step_text": state.get("checkpoint_message", "Awaiting your input..."),
            "agent": "checkpoint",
        }],
    }


# ------------------------------------------------------------------
# Agent node factory
# ------------------------------------------------------------------


def make_agent_node(
    agent_factory: AgentFactory,
    agent_name: str,
    skill_loader: SkillLoader | None = None,
):
    """Create an async node function for a named agent.

    Args:
        agent_factory: AgentFactory instance with tool registry.
        agent_name: Name matching the .md definition file.
        skill_loader: Optional SkillLoader for skill injection.

    Returns:
        Async node function compatible with LangGraph StateGraph.
    """

    async def node_fn(state: AnalyticsState) -> dict[str, Any]:
        start_ms = int(time.time() * 1000)
        step_id = str(uuid.uuid4())[:8]

        # Build extra context for business_analyst (skill injection)
        extra_context = ""
        if agent_name == "business_analyst" and skill_loader:
            selected = state.get("selected_skills", [])
            if selected:
                extra_context = (
                    "\n\n## Loaded Skills\n"
                    "Use the following domain/operational skills to guide your analysis:\n\n"
                    + skill_loader.load_skills(selected)
                )

        agent = agent_factory.make_agent(agent_name, extra_context=extra_context)
        result = await agent.ainvoke({"messages": state["messages"]})

        elapsed_ms = int(time.time() * 1000) - start_ms
        last_msg = result["messages"][-1] if result["messages"] else None
        output_summary = ""
        if last_msg and hasattr(last_msg, "content"):
            output_summary = last_msg.content[:200]

        # Build tools_used from the message sequence
        tools_used = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls"):
                for tc in msg.tool_calls:
                    tools_used.append(tc.get("name", "unknown"))

        trace = ExecutionTrace(
            step_id=step_id,
            agent=agent_name,
            input_summary=state["messages"][-1].content[:200] if state["messages"] else "",
            output_summary=output_summary,
            tools_used=tools_used,
            latency_ms=elapsed_ms,
            success=True,
        )

        updates: dict[str, Any] = {
            "messages": result["messages"],
            "execution_trace": state.get("execution_trace", []) + [trace],
            "agent_reasoning": state.get("agent_reasoning", []) + [{
                "step_name": agent_name.replace("_", " ").title(),
                "step_text": output_summary,
                "agent": agent_name,
            }],
        }

        # Update plan progress
        completed = state.get("plan_steps_completed", 0) + 1
        updates["plan_steps_completed"] = completed

        return updates

    node_fn.__name__ = f"{agent_name}_node"
    return node_fn

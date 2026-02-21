"""Node functions for each agent in the analytics graph.

Each node is a thin async wrapper that:
1. Records start time for ExecutionTrace
2. Invokes the agent (via AgentFactory or direct LLM call)
3. Updates state with results and trace info
4. Captures verbose details (tool calls, AI messages) when VERBOSE is on
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents.state import AnalyticsState, ExecutionTrace, ScopeDecision
from config.settings import (
    ALL_DOMAIN_SKILLS,
    FRICTION_AGENTS,
    LOG_LEVEL,
    MAX_DISPLAY_LENGTH,
    REPORTING_AGENTS,
    VERBOSE,
)
from core.agent_factory import AgentFactory
from core.llm import get_llm
from core.skill_loader import SkillLoader

logger = logging.getLogger("agenticanalytics.nodes")
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))


# ------------------------------------------------------------------
# Agent → state field mapping (for dedicated output fields)
# ------------------------------------------------------------------

AGENT_STATE_FIELDS: dict[str, str] = {
    "digital_friction_agent": "digital_analysis",
    "operations_agent": "operations_analysis",
    "communication_agent": "communication_analysis",
    "policy_agent": "policy_analysis",
    "synthesizer_agent": "synthesis_result",
    "narrative_agent": "narrative_output",
    "dataviz_agent": "dataviz_output",
    "formatting_agent": "formatting_output",
}


# ------------------------------------------------------------------
# Helpers: extract verbose details from agent message history
# ------------------------------------------------------------------


def _extract_text(content: Any) -> str:
    """Normalise LangChain message content to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return " ".join(parts)
    return str(content)


def _truncate(text: str, limit: int = MAX_DISPLAY_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... (truncated, {len(text)} chars total)"


def _extract_verbose_details(messages: list) -> dict[str, Any]:
    """Walk through agent message history and extract structured details.

    Returns a dict with:
      - tool_calls: list of {name, args_preview, result_preview}
      - ai_messages: list of plain-text AI responses
      - message_count: total messages
    """
    tool_calls: list[dict[str, str]] = []
    ai_messages: list[str] = []
    tool_result_map: dict[str, str] = {}  # tool_call_id → result preview

    for msg in messages:
        # Collect tool results first (ToolMessage)
        if msg.type == "tool" and hasattr(msg, "content"):
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                tool_result_map[tool_call_id] = _truncate(
                    _extract_text(msg.content), 500
                )

        # AI messages with tool_calls
        if msg.type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc.get("id", "")
                args_raw = tc.get("args", {})
                args_preview = _truncate(json.dumps(args_raw, default=str), 500)
                tool_calls.append({
                    "name": tc.get("name", "unknown"),
                    "args_preview": args_preview,
                    "result_preview": tool_result_map.get(tc_id, "(pending)"),
                })

        # Plain AI messages (no tool calls = final response or intermediate thought)
        if msg.type == "ai" and hasattr(msg, "content") and msg.content:
            if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                text = _extract_text(msg.content)
                if text.strip():
                    ai_messages.append(text)

    return {
        "tool_calls": tool_calls,
        "ai_messages": ai_messages,
        "message_count": len(messages),
    }


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
# Plan task helpers
# ------------------------------------------------------------------


def _update_task_status(
    plan_tasks: list[dict[str, str]],
    agent_name: str,
    status: str,
) -> list[dict[str, str]]:
    """Return a copy of plan_tasks with the matching agent's status updated."""
    updated = []
    for task in plan_tasks:
        task_copy = dict(task)
        if task_copy.get("agent") == agent_name:
            task_copy["status"] = status
        updated.append(task_copy)
    return updated


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

        logger.info("Node [%s] starting (step_id=%s)", agent_name, step_id)

        # Mark task as running in plan_tasks
        plan_tasks = list(state.get("plan_tasks", []))
        plan_tasks = _update_task_status(plan_tasks, agent_name, "running")

        # -- Build extra context based on agent type -----------------------
        extra_context = ""

        # Friction agents: inject all 6 domain skills
        if agent_name in FRICTION_AGENTS and skill_loader:
            extra_context = (
                "\n\n## Loaded Domain Skills\n"
                "Apply these domain skills through your specific analytical lens:\n\n"
                + skill_loader.load_skills(ALL_DOMAIN_SKILLS)
            )

        # Synthesizer: inject 4 friction agent outputs
        elif agent_name == "synthesizer_agent":
            agent_outputs = {
                "digital": state.get("digital_analysis", {}),
                "operations": state.get("operations_analysis", {}),
                "communication": state.get("communication_analysis", {}),
                "policy": state.get("policy_analysis", {}),
            }
            extra_context = (
                "\n\n## Friction Agent Outputs\n"
                "Synthesize the following 4 independent analyses:\n\n"
                + json.dumps(agent_outputs, indent=2, default=str)
            )

        # Reporting agents: inject synthesis result + findings
        elif agent_name in REPORTING_AGENTS:
            report_context: dict[str, Any] = {
                "synthesis": state.get("synthesis_result", {}),
                "findings": state.get("findings", []),
            }
            if agent_name == "formatting_agent":
                report_context["narrative"] = state.get("narrative_output", {})
                report_context["charts"] = state.get("dataviz_output", {})
            extra_context = (
                "\n\n## Analysis Context\n"
                + json.dumps(report_context, indent=2, default=str)
            )

        # Business analyst (legacy path): inject selected skills if any
        elif agent_name == "business_analyst" and skill_loader:
            selected = state.get("selected_skills", [])
            if selected:
                extra_context = (
                    "\n\n## Loaded Skills\n"
                    "Use the following domain/operational skills to guide your analysis:\n\n"
                    + skill_loader.load_skills(selected)
                )

        config = agent_factory.parse_agent_md(agent_name)
        system_msg_content = config.system_prompt
        if extra_context:
            system_msg_content += f"\n\n{extra_context}"
            
        logger.info("Node [%s] System Message payload:\n%s", agent_name, system_msg_content)
        logger.info("Node [%s] LLM calls starting (Input Messages: %d)", agent_name, len(state["messages"]))

        agent = agent_factory.make_agent(agent_name, extra_context=extra_context)
        result = await agent.ainvoke({"messages": state["messages"]})

        elapsed_ms = int(time.time() * 1000) - start_ms
        last_msg = result["messages"][-1] if result["messages"] else None
        
        if last_msg and hasattr(last_msg, "content"):
            logger.info("Node [%s] LLM calls generated response:\n%s", agent_name, _truncate(_extract_text(last_msg.content), 500))

        # -- Summarise output -----------------------------------------------
        output_summary = ""
        if last_msg and hasattr(last_msg, "content"):
            output_summary = _truncate(_extract_text(last_msg.content), 200)

        # -- Build tools_used list ------------------------------------------
        tools_used = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls"):
                for tc in msg.tool_calls:
                    tools_used.append(tc.get("name", "unknown"))

        # -- Verbose details ------------------------------------------------
        verbose_details: dict[str, Any] = {}
        if VERBOSE:
            verbose_details = _extract_verbose_details(result["messages"])
            verbose_details["elapsed_ms"] = elapsed_ms
            verbose_details["step_id"] = step_id
            logger.debug(
                "Node [%s] verbose: %d tool calls, %d AI messages, %dms",
                agent_name,
                len(verbose_details["tool_calls"]),
                len(verbose_details["ai_messages"]),
                elapsed_ms,
            )

        trace = ExecutionTrace(
            step_id=step_id,
            agent=agent_name,
            input_summary=state["messages"][-1].content[:200] if state["messages"] else "",
            output_summary=output_summary,
            tools_used=tools_used,
            latency_ms=elapsed_ms,
            success=True,
        )

        reasoning_entry: dict[str, Any] = {
            "step_name": agent_name.replace("_", " ").title(),
            "step_text": output_summary,
            "agent": agent_name,
        }
        if VERBOSE:
            reasoning_entry["verbose"] = verbose_details

        updates: dict[str, Any] = {
            "messages": result["messages"],
            "execution_trace": state.get("execution_trace", []) + [trace],
            "agent_reasoning": state.get("agent_reasoning", []) + [reasoning_entry],
        }

        # Write to dedicated state field if agent has one
        if agent_name in AGENT_STATE_FIELDS:
            updates[AGENT_STATE_FIELDS[agent_name]] = {
                "output": output_summary,
                "full_response": str(last_msg.content) if last_msg else "",
                "agent": agent_name,
            }

        # Update plan progress
        completed = state.get("plan_steps_completed", 0) + 1
        updates["plan_steps_completed"] = completed

        # Mark task as done in plan_tasks
        plan_tasks = _update_task_status(plan_tasks, agent_name, "done")
        updates["plan_tasks"] = plan_tasks

        logger.info(
            "Node [%s] finished in %dms (tools: %s)",
            agent_name, elapsed_ms, ", ".join(tools_used) or "none",
        )

        return updates

    node_fn.__name__ = f"{agent_name}_node"
    return node_fn

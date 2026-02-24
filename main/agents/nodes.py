"""Node functions for each agent in the analytics graph.

Each node is a thin async wrapper that:
1. Invokes the agent (pre-bound structured chain or per-call ReAct agent)
2. Applies structured-output → state mapping for decision agents
3. Tracks plan progress (only for agents listed in plan_tasks)
4. Records ExecutionTrace + reasoning for the Chainlit UI
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage

from agents.schemas import (
    CritiqueOutput,
    DataAnalystOutput,
    PlannerOutput,
    STRUCTURED_OUTPUT_SCHEMAS,
    SupervisorOutput,
    SynthesizerOutput,
)
from agents.state import AnalyticsState, ExecutionTrace
from config import (
    ALL_DOMAIN_SKILLS,
    FRICTION_AGENTS,
    LOG_LEVEL,
    MAX_DISPLAY_LENGTH,
    REPORTING_AGENTS,
    VERBOSE,
)
from core.agent_factory import AgentFactory
from core.skill_loader import SkillLoader

logger = logging.getLogger("agenticanalytics.nodes")
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))


# ------------------------------------------------------------------
# Agent → dedicated state field
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

# Supervisor decision → next node routing
_DECISION_TO_NEXT: dict[str, str] = {
    "answer": "__end__",
    "clarify": "__end__",
    "extract": "data_analyst",
    "analyse": "planner",
    "execute": "",  # resolved from plan_tasks
}

# Safety: max consecutive supervisor→data_analyst loops before forcing progress
MAX_SUPERVISOR_LOOPS = 2


# ------------------------------------------------------------------
# Text helpers
# ------------------------------------------------------------------


def _text(content: Any) -> str:
    """Normalise LangChain message content to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)


def _trunc(text: str, limit: int = MAX_DISPLAY_LENGTH) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text)} chars)"


# ------------------------------------------------------------------
# JSON fallback parser (legacy: non-structured agents only)
# ------------------------------------------------------------------


def _parse_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from raw LLM text."""
    text = text.strip()
    # Try fenced code blocks first
    if "```" in text:
        for part in text.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except (json.JSONDecodeError, ValueError):
                continue
    # Try full text, then brace extraction
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return {}


# ------------------------------------------------------------------
# Plan helpers
# ------------------------------------------------------------------


def _find_next_plan_agent(plan_tasks: list[dict]) -> tuple[list[dict], str]:
    """Find the first pending task, mark it in_progress, return (updated_tasks, agent).

    Returns ("__end__", ...) if no pending task is found.
    """
    updated = [dict(t) for t in plan_tasks]
    for task in updated:
        if task.get("status") in ("ready", "todo"):
            task["status"] = "in_progress"
            return updated, task.get("agent", "__end__")
    return updated, "__end__"


def _clear_checkpoint_fields() -> dict[str, Any]:
    return {
        "requires_user_input": False,
        "checkpoint_message": "",
        "checkpoint_prompt": "",
        "checkpoint_token": "",
        "pending_input_for": "",
    }


# ------------------------------------------------------------------
# Verbose extraction (only runs when VERBOSE is on)
# ------------------------------------------------------------------


def _verbose_details(messages: list) -> dict[str, Any]:
    """Extract tool calls and AI messages for debug display."""
    tool_calls: list[dict] = []
    ai_msgs: list[str] = []
    tool_results: dict[str, str] = {}

    for msg in messages:
        if msg.type == "tool" and hasattr(msg, "content"):
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id:
                tool_results[tc_id] = _trunc(_text(msg.content), 500)

        if msg.type == "ai":
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "name": tc.get("name", "?"),
                        "args_preview": _trunc(json.dumps(tc.get("args", {}), default=str), 500),
                        "result_preview": tool_results.get(tc.get("id", ""), "(pending)"),
                    })
            elif hasattr(msg, "content") and msg.content:
                t = _text(msg.content).strip()
                if t:
                    ai_msgs.append(t)

    return {"tool_calls": tool_calls, "ai_messages": ai_msgs, "message_count": len(messages)}


# ------------------------------------------------------------------
# Node I/O trace (graph contract)
# ------------------------------------------------------------------


def _trace_io(state: AnalyticsState, node: str, inp: dict, out: dict) -> dict[str, Any]:
    entry = {"node": node, "input": inp, "output": {k: v for k, v in out.items() if k != "messages"}}
    return {
        "node_io": entry,
        "io_trace": state.get("io_trace", []) + [entry],
        "last_completed_node": node,
    }


# ------------------------------------------------------------------
# User checkpoint node
# ------------------------------------------------------------------


async def user_checkpoint_node(state: AnalyticsState) -> dict[str, Any]:
    """Graph pauses here for user input via interrupt_before."""
    return {
        "requires_user_input": True,
        "reasoning": [{
            "step_name": "User Checkpoint",
            "step_text": state.get("checkpoint_message", "Awaiting your input..."),
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
    """Create an async node function for *agent_name*.

    Structured-output agents (supervisor, planner, data_analyst, synthesizer,
    critique) have their LLM chain bound **once** here at graph-build time.
    ReAct agents are built per-invocation via ``agent_factory.make_agent``.
    """
    from core.agent_factory import StructuredOutputAgent

    # -- Eager chain creation for structured agents ------------------------
    is_structured = agent_name in STRUCTURED_OUTPUT_SCHEMAS
    structured_chain = None
    output_schema = None

    if is_structured:
        structured_chain, output_schema = agent_factory.create_structured_chain(agent_name)
        logger.info("Pre-created structured chain for [%s] → %s", agent_name, output_schema.__name__)

    # -- Closure: the actual node function ---------------------------------
    async def node_fn(state: AnalyticsState) -> dict[str, Any]:
        start_ms = int(time.time() * 1000)
        step_id = str(uuid.uuid4())[:8]
        logger.info("Node [%s] starting (step=%s)", agent_name, step_id)

        # -- Build dynamic context ----------------------------------------
        extra_context = _build_extra_context(agent_name, state, skill_loader)

        config = agent_factory.parse_agent_md(agent_name)
        system_prompt = config.system_prompt
        if extra_context:
            system_prompt += f"\n\n{extra_context}"

        logger.info("Node [%s] system prompt length=%d, input messages=%d",
                     agent_name, len(system_prompt), len(state["messages"]))

        # -- Invoke agent --------------------------------------------------
        if is_structured and structured_chain is not None:
            agent = StructuredOutputAgent(
                name=agent_name,
                system_prompt=system_prompt,
                chain=structured_chain,
                output_schema=output_schema,
            )
            result = await agent.ainvoke({"messages": state["messages"]})
        else:
            agent = agent_factory.make_agent(agent_name, extra_context=extra_context)
            result = await agent.ainvoke({"messages": state["messages"]})

        elapsed = int(time.time() * 1000) - start_ms
        msgs = result["messages"]
        last_msg = msgs[-1] if msgs else None
        summary = _trunc(_text(last_msg.content), 200) if last_msg and hasattr(last_msg, "content") else ""

        # -- Build tools_used list -----------------------------------------
        tools_used = [
            tc.get("name", "?")
            for m in msgs if hasattr(m, "tool_calls")
            for tc in m.tool_calls
        ]

        # -- Base updates --------------------------------------------------
        updates: dict[str, Any] = {
            "messages": msgs,
            "execution_trace": state.get("execution_trace", []) + [ExecutionTrace(
                step_id=step_id,
                agent=agent_name,
                input_summary=state["messages"][-1].content[:200] if state["messages"] else "",
                output_summary=summary,
                tools_used=tools_used,
                latency_ms=elapsed,
                success=True,
            )],
            "reasoning": [{
                "step_name": agent_name.replace("_", " ").title(),
                "step_text": summary,
                "agent": agent_name,
                **({"verbose": _verbose_details(msgs)} if VERBOSE else {}),
            }],
            **_clear_checkpoint_fields(),
        }

        # Node I/O trace
        updates.update(_trace_io(state, agent_name, {
            "messages_count": len(state.get("messages", [])),
            "plan_steps_completed": state.get("plan_steps_completed", 0),
        }, {"output_summary": summary, "tools_used": tools_used, "elapsed_ms": elapsed}))

        # Dedicated state field (friction/reporting agents)
        if agent_name in AGENT_STATE_FIELDS:
            updates[AGENT_STATE_FIELDS[agent_name]] = {
                "output": summary,
                "full_response": str(last_msg.content) if last_msg else "",
                "agent": agent_name,
            }

        # -- Structured output → state mapping -----------------------------
        structured = result.get("structured_output")
        plan_agents = {t.get("agent", "") for t in state.get("plan_tasks", [])}

        _apply_structured_updates(agent_name, structured, last_msg, state, updates)

        # -- Plan progress (only for agents that ARE in the plan) -----------
        if agent_name in plan_agents:
            _advance_plan(agent_name, state, updates)

        logger.info("Node [%s] done in %dms (tools: %s)", agent_name, elapsed, ", ".join(tools_used) or "none")
        return updates

    node_fn.__name__ = f"{agent_name}_node"
    return node_fn


# ------------------------------------------------------------------
# Extra context builders
# ------------------------------------------------------------------


def _build_extra_context(
    agent_name: str,
    state: AnalyticsState,
    skill_loader: SkillLoader | None,
) -> str:
    """Build agent-specific context to append to the system prompt."""
    if agent_name in FRICTION_AGENTS and skill_loader:
        return (
            "\n\n## Loaded Domain Skills\n"
            "Apply these domain skills through your specific analytical lens:\n\n"
            + skill_loader.load_skills(ALL_DOMAIN_SKILLS)
        )

    if agent_name == "synthesizer_agent":
        return (
            "\n\n## Friction Agent Outputs\n"
            "Synthesize the following 4 independent analyses:\n\n"
            + json.dumps({
                "digital": state.get("digital_analysis", {}),
                "operations": state.get("operations_analysis", {}),
                "communication": state.get("communication_analysis", {}),
                "policy": state.get("policy_analysis", {}),
            }, indent=2, default=str)
        )

    if agent_name in REPORTING_AGENTS:
        ctx: dict[str, Any] = {
            "synthesis": state.get("synthesis_result", {}),
            "findings": state.get("findings", []),
        }
        if agent_name == "formatting_agent":
            ctx["narrative"] = state.get("narrative_output", {})
            ctx["charts"] = state.get("dataviz_output", {})
        return "\n\n## Analysis Context\n" + json.dumps(ctx, indent=2, default=str)

    if agent_name == "supervisor":
        return (
            "\n\n## Current State Context\n"
            + json.dumps({
                "filters_applied": state.get("filters_applied", {}),
                "themes_for_analysis": state.get("themes_for_analysis", []),
                "navigation_log": state.get("navigation_log", []),
                "analysis_objective": state.get("analysis_objective", ""),
                "plan_tasks": state.get("plan_tasks", []),
                "plan_steps_completed": state.get("plan_steps_completed", 0),
                "plan_steps_total": state.get("plan_steps_total", 0),
            }, indent=2, default=str)
        )

    if agent_name == "planner":
        return (
            "\n\n## Planning Context\n"
            + json.dumps({
                "filters_applied": state.get("filters_applied", {}),
                "themes_for_analysis": state.get("themes_for_analysis", []),
                "navigation_log": state.get("navigation_log", []),
                "analysis_objective": state.get("analysis_objective", ""),
                "critique_enabled": state.get("critique_enabled", False),
            }, indent=2, default=str)
        )

    return ""


# ------------------------------------------------------------------
# Structured output → state mapping
# ------------------------------------------------------------------


def _apply_structured_updates(
    agent_name: str,
    structured: Any,
    last_msg: Any,
    state: AnalyticsState,
    updates: dict[str, Any],
) -> None:
    """Map structured/fallback output to state updates. Mutates *updates*."""

    # === SUPERVISOR ===
    if agent_name == "supervisor":
        if isinstance(structured, SupervisorOutput):
            _apply_supervisor(structured, state, updates)
        elif last_msg and hasattr(last_msg, "content"):
            _apply_supervisor_fallback(_text(last_msg.content), state, updates)

    # === PLANNER ===
    elif agent_name == "planner":
        if isinstance(structured, PlannerOutput):
            updates.update({
                "plan_tasks": [t.model_dump() for t in structured.plan_tasks],
                "plan_steps_total": structured.plan_steps_total,
                "plan_steps_completed": 0,
                "analysis_objective": structured.analysis_objective,
                "reasoning": [{"step_name": "Planner", "step_text": structured.reasoning}],
            })
            logger.info("Planner: %d tasks, objective=%r", len(structured.plan_tasks), structured.analysis_objective[:80])
        elif last_msg and hasattr(last_msg, "content"):
            data = _parse_json(_text(last_msg.content))
            if data.get("plan_tasks"):
                updates.update({
                    "plan_tasks": data["plan_tasks"],
                    "plan_steps_total": data.get("plan_steps_total", len(data["plan_tasks"])),
                    "plan_steps_completed": 0,
                })
                if data.get("analysis_objective"):
                    updates["analysis_objective"] = data["analysis_objective"]

    # === DATA ANALYST (ReAct agent — extracts state from tool results) ===
    elif agent_name == "data_analyst":
        # Parse the last AI message for JSON summary (fallback)
        da_data = {}
        if last_msg and hasattr(last_msg, "content"):
            da_data = _parse_json(_text(last_msg.content))

        da_decision = da_data.get("decision", "success")
        da_response = da_data.get("response", _text(last_msg.content) if last_msg else "")
        da_confidence = da_data.get("confidence", 80)

        # Ensure da_response is a string (tool results can be dicts)
        if not isinstance(da_response, str):
            da_response = json.dumps(da_response, indent=2, default=str)

        updates["reasoning"] = [{"step_name": "Data Analyst", "step_text": da_response}]
        if da_response:
            updates["messages"] = [AIMessage(content=da_response)]

        # Extract filters_applied and themes from tool result messages
        # (filter_data and bucket_data tools populate these)
        _extract_data_analyst_state(state, updates)

        logger.info("Data Analyst: decision=%s, confidence=%s", da_decision, da_confidence)

    # === SYNTHESIZER ===
    elif agent_name == "synthesizer_agent":
        if isinstance(structured, SynthesizerOutput):
            narrative = structured.summary.executive_narrative
            updates.update({
                "synthesis_result": structured.summary.model_dump(),
                "findings": [f.model_dump() for f in structured.findings],
                "reasoning": [{"step_name": "Synthesizer Agent", "step_text": narrative}],
            })
            if narrative:
                updates["messages"] = [AIMessage(content=narrative)]
            logger.info("Synthesizer: %d findings, confidence=%d", len(structured.findings), structured.confidence)
        elif last_msg and hasattr(last_msg, "content"):
            # ReAct fallback: parse JSON from last message
            data = _parse_json(_text(last_msg.content))
            if data.get("summary"):
                updates["synthesis_result"] = data["summary"]
            if data.get("findings"):
                updates["findings"] = data["findings"]
            narrative = data.get("summary", {}).get("executive_narrative", _text(last_msg.content))
            updates["reasoning"] = [{"step_name": "Synthesizer Agent", "step_text": narrative}]
            if narrative:
                updates["messages"] = [AIMessage(content=narrative)]
            logger.info("Synthesizer (fallback): %d findings", len(data.get("findings", [])))

    # === CRITIQUE ===
    elif agent_name == "critique":
        if isinstance(structured, CritiqueOutput):
            text = f"Grade: {structured.grade} | Score: {structured.quality_score:.2f} | Decision: {structured.decision}\n{structured.summary}"
            updates.update({
                "critique_feedback": structured.model_dump(),
                "quality_score": structured.quality_score,
                "reasoning": [{"step_name": "Critique Agent", "step_text": text}],
                "messages": [AIMessage(content=text)],
            })
            logger.info("Critique: grade=%s, score=%.2f, issues=%d", structured.grade, structured.quality_score, len(structured.issues))
        elif last_msg and hasattr(last_msg, "content"):
            # ReAct fallback: parse JSON from last message
            data = _parse_json(_text(last_msg.content))
            quality_score = data.get("quality_score", data.get("overall_quality_score", 0.0))
            grade = data.get("grade", "C")
            decision = data.get("decision", "needs_revision")
            summary_text = data.get("summary", _text(last_msg.content))
            text = f"Grade: {grade} | Score: {quality_score:.2f} | Decision: {decision}\n{summary_text}"
            updates.update({
                "critique_feedback": data,
                "quality_score": float(quality_score),
                "reasoning": [{"step_name": "Critique Agent", "step_text": text}],
                "messages": [AIMessage(content=text)],
            })
            logger.info("Critique (fallback): grade=%s, score=%.2f", grade, quality_score)


def _extract_data_analyst_state(
    state: AnalyticsState, updates: dict[str, Any]
) -> None:
    """Extract filters_applied and themes_for_analysis from tool results.

    Scans messages for tool result messages from filter_data / bucket_data
    and populates the corresponding state fields so the supervisor knows
    extraction is complete.
    """
    messages = updates.get("messages", [])
    for msg in messages:
        if not hasattr(msg, "content"):
            continue
        content = _text(msg.content)
        data = _parse_json(content)
        if not data:
            continue

        # filter_data tool typically returns applied filters
        if "filters" in data or "product" in data or "call_theme" in data:
            filters = data.get("filters", {})
            if not filters:
                filters = {}
                if data.get("product"):
                    filters["product"] = data["product"]
                if data.get("call_theme"):
                    filters["call_theme"] = data["call_theme"]
            if filters:
                updates["filters_applied"] = filters
                logger.info("Data Analyst: extracted filters_applied=%s", filters)

        # bucket_data or distribution results may contain themes
        if "themes" in data:
            updates["themes_for_analysis"] = data["themes"]
            logger.info("Data Analyst: extracted themes_for_analysis=%s", data["themes"])
        if "buckets" in data:
            updates["data_buckets"] = data["buckets"]

    # If no tool results found, still mark that data_analyst ran
    # by setting a minimal filters_applied so the supervisor knows.
    if "filters_applied" not in updates and not state.get("filters_applied"):
        updates["filters_applied"] = {"status": "extraction_attempted"}
        logger.info("Data Analyst: no filter results found in tool messages, marking extraction_attempted")


def _apply_supervisor(s: SupervisorOutput, state: AnalyticsState, updates: dict) -> None:
    """Map SupervisorOutput → state updates."""
    updates["supervisor_decision"] = s.decision
    updates["reasoning"] = [{"step_name": "Supervisor", "step_text": s.reasoning}]

    target_agent = _DECISION_TO_NEXT.get(s.decision, "__end__")

    if s.decision == "execute":
        plan, agent = _find_next_plan_agent(state.get("plan_tasks", []))
        updates["next_agent"] = agent
        updates["plan_tasks"] = plan
    elif s.decision == "extract":
        # Loop detection: count how many consecutive supervisor→data_analyst
        # round-trips have already happened.
        trace = state.get("execution_trace", [])
        consecutive = 0
        for entry in reversed(trace):
            agent = entry.get("agent", "") if isinstance(entry, dict) else getattr(entry, "agent", "")
            if agent == "data_analyst":
                consecutive += 1
            elif agent == "supervisor":
                continue  # skip supervisor entries between
            else:
                break

        if consecutive >= MAX_SUPERVISOR_LOOPS:
            logger.warning(
                "Supervisor loop detected: %d consecutive extract→data_analyst cycles. "
                "Forcing transition to 'analyse' (planner).",
                consecutive,
            )
            updates["next_agent"] = "planner"
            updates["supervisor_decision"] = "analyse"
        else:
            updates["next_agent"] = target_agent
    else:
        updates["next_agent"] = target_agent

    if s.response:
        updates["messages"] = [AIMessage(content=s.response)]

    logger.info("Supervisor (structured): %s → %s (confidence=%d)", s.decision, updates["next_agent"], s.confidence)


def _apply_supervisor_fallback(raw: str, state: AnalyticsState, updates: dict) -> None:
    """Map legacy JSON supervisor output → state updates."""
    data = _parse_json(raw)
    decision = data.get("decision", "")
    if decision not in _DECISION_TO_NEXT:
        logger.warning("Supervisor fallback: unrecognised decision %r", decision)
        return

    updates["supervisor_decision"] = decision
    if decision == "execute":
        plan, agent = _find_next_plan_agent(state.get("plan_tasks", []))
        updates["next_agent"] = agent
        updates["plan_tasks"] = plan
    elif decision == "extract":
        # Same loop detection as the structured path
        trace = state.get("execution_trace", [])
        consecutive = 0
        for entry in reversed(trace):
            agent = entry.get("agent", "") if isinstance(entry, dict) else getattr(entry, "agent", "")
            if agent == "data_analyst":
                consecutive += 1
            elif agent == "supervisor":
                continue
            else:
                break
        if consecutive >= MAX_SUPERVISOR_LOOPS:
            logger.warning(
                "Supervisor fallback loop detected: %d consecutive extract→data_analyst cycles. "
                "Forcing transition to 'analyse' (planner).",
                consecutive,
            )
            updates["next_agent"] = "planner"
            updates["supervisor_decision"] = "analyse"
        else:
            updates["next_agent"] = _DECISION_TO_NEXT[decision]
    else:
        updates["next_agent"] = _DECISION_TO_NEXT[decision]

    if decision in ("answer", "clarify") and data.get("response"):
        updates["messages"] = [AIMessage(content=data["response"])]

    logger.info("Supervisor (fallback): %s → %s (confidence=%s)", decision, updates.get("next_agent", "?"), data.get("confidence", "?"))


# ------------------------------------------------------------------
# Plan progress
# ------------------------------------------------------------------


def _advance_plan(agent_name: str, state: AnalyticsState, updates: dict) -> None:
    """Mark the agent's task done and check pipeline completion."""
    tasks = [dict(t) for t in updates.get("plan_tasks", state.get("plan_tasks", []))]
    for t in tasks:
        if t.get("agent") == agent_name and t.get("status") != "done":
            t["status"] = "done"
            break
    updates["plan_tasks"] = tasks

    completed = state.get("plan_steps_completed", 0) + 1
    total = state.get("plan_steps_total", 0)
    updates["plan_steps_completed"] = completed
    logger.info("Plan progress: %d/%d (agent=%s)", completed, total, agent_name)

    if total > 0 and completed >= total:
        updates["analysis_complete"] = True
        updates["phase"] = "qa"
        logger.info("Pipeline complete — entering Q&A mode.")

"""Node functions for each agent in the analytics graph.

Each node is a thin async wrapper that:
1. Invokes the agent (pre-bound structured chain or per-call ReAct agent)
2. Applies structured-output -> state mapping for decision agents
3. Tracks plan progress (only for agents listed in plan_tasks)
4. Records ExecutionTrace + reasoning for the Chainlit UI
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from difflib import get_close_matches
from typing import Any

from langchain_core.messages import AIMessage

from agents.schemas import (
    CritiqueOutput,
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
# Agent -> dedicated state field
# ------------------------------------------------------------------

AGENT_STATE_FIELDS: dict[str, str] = {
    "digital_friction_agent": "digital_analysis",
    "operations_agent": "operations_analysis",
    "communication_agent": "communication_analysis",
    "policy_agent": "policy_analysis",
    "synthesizer_agent": "synthesis_result",
    "narrative_agent": "narrative_output",
    "formatting_agent": "formatting_output",
}

# Supervisor decision -> next node routing
_DECISION_TO_NEXT: dict[str, str] = {
    "answer": "__end__",
    "clarify": "__end__",
    "extract": "data_analyst",
    "analyse": "planner",
    "execute": "",  # resolved from plan_tasks
    "report_generation": "report_generation",
}

# Safety: max consecutive supervisor->data_analyst loops before forcing progress
MAX_SUPERVISOR_LOOPS = 2


LLM_INPUT_FIELDS: dict[str, list[str]] = {
    "supervisor": [
        "messages", "dataset_schema", "filters_applied", "data_buckets",
        "themes_for_analysis", "plan_tasks", "analysis_objective",
        "selected_friction_agents", "expected_friction_lenses",
    ],
    "planner": [
        "messages", "filters_applied", "themes_for_analysis",
        "navigation_log", "analysis_objective", "plan_tasks",
    ],
    "data_analyst": [
        "messages", "dataset_path", "dataset_schema", "analysis_objective",
    ],
    "digital_friction_agent": [
        "messages", "data_buckets", "_focus_bucket", "filters_applied", "analysis_objective",
    ],
    "operations_agent": [
        "messages", "data_buckets", "_focus_bucket", "filters_applied", "analysis_objective",
    ],
    "communication_agent": [
        "messages", "data_buckets", "_focus_bucket", "filters_applied", "analysis_objective",
    ],
    "policy_agent": [
        "messages", "data_buckets", "_focus_bucket", "filters_applied", "analysis_objective",
    ],
    "synthesizer_agent": [
        "messages", "friction_md_paths", "lens_synthesis_paths",
        "expected_friction_lenses", "selected_friction_agents",
    ],
    "narrative_agent": [
        "messages", "synthesis_result", "synthesis_output_file", "findings", "filters_applied",
    ],
    "formatting_agent": [
        "messages", "narrative_output", "synthesis_result", "findings", "filters_applied",
    ],
    "report_analyst": [
        "messages", "report_file_path", "data_file_path", "markdown_file_path",
        "narrative_output", "formatting_output",
    ],
    "critique": [
        "messages", "narrative_output", "formatting_output", "synthesis_result", "findings",
    ],
}


def _present_field_names(state: AnalyticsState, fields: list[str]) -> list[str]:
    present: list[str] = []
    for field in fields:
        value = state.get(field)  # type: ignore[arg-type]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
            continue
        present.append(field)
    return present


def _skills_for_agent(agent_name: str, state: AnalyticsState) -> list[str]:
    if agent_name not in FRICTION_AGENTS:
        return []
    raw_buckets = state.get("data_buckets", {})
    focus_bucket = str(state.get("_focus_bucket", "") or "")
    skills: list[str] = []
    if isinstance(raw_buckets, dict) and focus_bucket and isinstance(raw_buckets.get(focus_bucket), dict):
        skills = list(raw_buckets[focus_bucket].get("assigned_skills", []) or [])
    elif isinstance(raw_buckets, dict):
        for binfo in raw_buckets.values():
            if not isinstance(binfo, dict):
                continue
            for skill in binfo.get("assigned_skills", []) or []:
                if isinstance(skill, str) and skill and skill not in skills:
                    skills.append(skill)
    return [s for s in skills if isinstance(s, str) and s]


def _log_llm_input_signature(
    agent_name: str,
    state: AnalyticsState,
    *,
    prompt_chars: int,
    context_chars: int,
) -> None:
    configured = LLM_INPUT_FIELDS.get(agent_name, ["messages"])
    fields = _present_field_names(state, configured)
    skills = _skills_for_agent(agent_name, state)
    skills_text = ", ".join(skills) if skills else "none"
    fields_text = ", ".join(fields) if fields else "messages"

    logger.info("[LLM][%s] input = agent_prompt + skills[%s] + <%s>", agent_name, skills_text, fields_text)
    logger.info(
        "[LLM][%s] size  = prompt_chars=%d extra_context_chars=%d messages=%d",
        agent_name, prompt_chars, context_chars, len(state.get("messages", [])),
    )


def _PRELIMINARY_PLAN_TASKS() -> list[dict[str, str]]:
    """Return a preliminary task list shown as soon as extraction starts."""
    return [
        {"title": "Data extraction & bucketing", "agent": "data_analyst", "status": "in_progress"},
        {"title": "Multi-dimensional friction analysis", "agent": "friction_analysis", "status": "ready"},
        {"title": "Generate analysis report", "agent": "report_generation", "status": "ready"},
        {"title": "Deliver report and downloads", "agent": "report_analyst", "status": "ready"},
    ]


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

    Resume any existing in-progress task first.
    Returns ("__end__", ...) if no task is actionable.
    """
    updated = [dict(t) for t in plan_tasks]

    # Resume interrupted work before advancing to the next ready task.
    for task in updated:
        if task.get("status") == "in_progress":
            return updated, task.get("agent", "__end__")

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
# Thin invocation helpers (replace make_agent_node factory)
# ------------------------------------------------------------------


async def _run_structured_node(
    agent_name: str,
    chain: Any,
    output_schema: type,
    system_prompt: str,
    state: AnalyticsState,
    *,
    extra_context: str = "",
) -> tuple[dict[str, Any], Any, Any]:
    """Invoke a structured-output LLM chain and return mechanical base updates.

    Returns ``(base_updates, structured_output, last_new_msg)``.

    ``base_updates`` contains the boilerplate every node needs:
      - ``messages``         – new messages only (input messages filtered out)
      - ``execution_trace``  – appended ExecutionTrace entry
      - ``io_trace`` / ``node_io`` / ``last_completed_node``
      - checkpoint field resets

    The CALLER writes: reasoning, next_agent, plan_tasks, and all other
    agent-specific state fields.
    """
    from core.agent_factory import StructuredOutputAgent

    start_ms = int(time.time() * 1000)
    step_id = str(uuid.uuid4())[:8]
    logger.info(
        "[NODE][START] %s step=%s msgs_in=%d plan=%d/%d",
        agent_name, step_id, len(state["messages"]),
        state.get("plan_steps_completed", 0), state.get("plan_steps_total", 0),
    )
    _log_llm_input_signature(
        agent_name,
        state,
        prompt_chars=len(system_prompt),
        context_chars=len(extra_context),
    )

    agent = StructuredOutputAgent(
        name=agent_name,
        system_prompt=system_prompt,
        chain=chain,
        output_schema=output_schema,
    )
    result = await agent.ainvoke({"messages": state["messages"]})
    structured = result.get("structured_output")
    elapsed = int(time.time() * 1000) - start_ms

    input_ids = {m.id for m in state["messages"] if hasattr(m, "id") and m.id}
    new_msgs = [
        m for m in result["messages"]
        if not (hasattr(m, "id") and m.id and m.id in input_ids)
    ]
    last_msg = new_msgs[-1] if new_msgs else None
    summary = _trunc(_text(last_msg.content), 200) if last_msg and hasattr(last_msg, "content") else ""
    tools_used = [tc.get("name", "?") for m in new_msgs if hasattr(m, "tool_calls") for tc in m.tool_calls]
    input_summary = _text(state["messages"][-1].content)[:200] if state["messages"] else ""

    base: dict[str, Any] = {
        "messages": new_msgs,
        "execution_trace": state.get("execution_trace", []) + [ExecutionTrace(
            step_id=step_id, agent=agent_name, input_summary=input_summary,
            output_summary=summary, tools_used=tools_used, latency_ms=elapsed, success=True,
        )],
        **_clear_checkpoint_fields(),
    }
    base.update(_trace_io(
        state, agent_name,
        {"messages_count": len(state["messages"]), "plan_steps_completed": state.get("plan_steps_completed", 0)},
        {"output_summary": summary, "tools_used": tools_used, "elapsed_ms": elapsed},
    ))
    logger.info(
        "[NODE][DONE ] %s elapsed_ms=%d structured=%s tools=%s new_msgs=%d",
        agent_name,
        elapsed,
        type(structured).__name__ if structured else "None",
        ", ".join(tools_used) or "none",
        len(new_msgs),
    )
    return base, structured, last_msg


async def _run_react_node(
    agent_name: str,
    agent_factory: AgentFactory,
    extra_context: str,
    state: AnalyticsState,
) -> tuple[dict[str, Any], Any]:
    """Invoke a ReAct (tool-calling) agent and return mechanical base updates.

    Returns ``(base_updates, last_new_msg)``.

    ``base_updates`` contains: messages (all new), execution_trace, io_trace,
    last_completed_node, and checkpoint field resets.

    The CALLER writes: reasoning and all agent-specific state field updates.
    """
    start_ms = int(time.time() * 1000)
    step_id = str(uuid.uuid4())[:8]
    logger.info(
        "[NODE][START] %s step=%s msgs_in=%d plan=%d/%d",
        agent_name, step_id, len(state["messages"]),
        state.get("plan_steps_completed", 0), state.get("plan_steps_total", 0),
    )
    base_prompt_chars = len(agent_factory.parse_agent_md(agent_name).system_prompt)
    _log_llm_input_signature(
        agent_name,
        state,
        prompt_chars=base_prompt_chars,
        context_chars=len(extra_context or ""),
    )

    agent = agent_factory.make_agent(agent_name, extra_context=extra_context)
    result = await agent.ainvoke({"messages": state["messages"]})
    elapsed = int(time.time() * 1000) - start_ms

    input_ids = {m.id for m in state["messages"] if hasattr(m, "id") and m.id}
    new_msgs = [
        m for m in result["messages"]
        if not (hasattr(m, "id") and m.id and m.id in input_ids)
    ]
    last_msg = new_msgs[-1] if new_msgs else None
    summary = _trunc(_text(last_msg.content), 200) if last_msg and hasattr(last_msg, "content") else ""
    tools_used = [tc.get("name", "?") for m in new_msgs if hasattr(m, "tool_calls") for tc in m.tool_calls]
    input_summary = _text(state["messages"][-1].content)[:200] if state["messages"] else ""

    base: dict[str, Any] = {
        "messages": new_msgs,
        "execution_trace": state.get("execution_trace", []) + [ExecutionTrace(
            step_id=step_id, agent=agent_name, input_summary=input_summary,
            output_summary=summary, tools_used=tools_used, latency_ms=elapsed, success=True,
        )],
        **_clear_checkpoint_fields(),
    }
    base.update(_trace_io(
        state, agent_name,
        {"messages_count": len(state["messages"]), "plan_steps_completed": state.get("plan_steps_completed", 0)},
        {"output_summary": summary, "tools_used": tools_used, "elapsed_ms": elapsed},
    ))
    logger.info(
        "[NODE][DONE ] %s elapsed_ms=%d tools=%s new_msgs=%d",
        agent_name,
        elapsed,
        ", ".join(tools_used) or "none",
        len(new_msgs),
    )
    return base, last_msg


def _agent_output_field(agent_name: str, new_msgs: list, summary: str) -> dict[str, str]:
    """Build the standard state-field dict stored for friction / reporting agents.

    Shape: ``{"output": <summary>, "full_response": <all AI text>, "agent": <name>}``
    Used by ``digital_analysis``, ``operations_analysis``, ``narrative_output``, etc.
    """
    full_response = "\n\n".join(
        _text(m.content)
        for m in new_msgs
        if getattr(m, "type", "") == "ai" and _text(m.content)
    )
    return {"output": summary, "full_response": full_response, "agent": agent_name}



# ------------------------------------------------------------------
# Extra context builders
# ------------------------------------------------------------------


def _extract_agent_json(payload: Any) -> dict[str, Any]:
    """Parse JSON payload from an agent state field."""
    if not isinstance(payload, dict):
        return {}
    return _parse_json(payload.get("full_response", "")) or _parse_json(payload.get("output", ""))


def _build_formatting_context(summary_ctx: dict[str, Any], state: AnalyticsState) -> dict[str, Any]:
    """Build compact assembly context for formatting agent."""
    narrative_payload = state.get("narrative_output", {})
    narrative_markdown = ""
    if isinstance(narrative_payload, dict):
        narrative_markdown = str(narrative_payload.get("full_response", "")).strip()
    elif narrative_payload:
        narrative_markdown = str(narrative_payload)

    chart_placeholders = [
        "{{chart.friction_distribution}}",
        "{{chart.impact_ease_scatter}}",
        "{{chart.driver_breakdown}}",
    ]

    return {
        "summary": summary_ctx,
        "filters_applied": state.get("filters_applied", {}),
        "narrative_markdown": narrative_markdown,
        "narrative": {"full_response": narrative_markdown},
        "chart_placeholders": chart_placeholders,
    }


def _write_versioned_md(base_name: str, content: str, metadata: dict) -> str:
    """Write content to a versioned markdown file in the session cache.

    Uses the session DataStore (which is keyed to the thread_id) so the file
    lands in data/.cache/<thread_id>/<base_name>_v<n>.md.

    Returns the absolute file path (use as completion flag — if it exists, step is done).
    """
    import chainlit as cl
    data_store = cl.user_session.get("data_store")
    if data_store:
        _key, path = data_store.store_versioned_md(base_name, content, metadata)
        return path
    return ""


def _build_extra_context(
    agent_name: str,
    state: AnalyticsState,
    skill_loader: SkillLoader | None,
) -> str:
    """Build agent-specific context to append to the system prompt."""
    if agent_name in FRICTION_AGENTS and skill_loader:
        focus_bucket = state.get("_focus_bucket", "")
        raw_buckets = state.get("data_buckets", {})
        bucket_context = ""

        if focus_bucket and isinstance(raw_buckets, dict) and focus_bucket in raw_buckets:
            # Single-bucket mode: load only this bucket's assigned skills
            binfo = raw_buckets[focus_bucket]
            skills_to_load: list[str] = binfo.get("assigned_skills", []) if isinstance(binfo, dict) else []
            bucket_name = binfo.get("bucket_name", focus_bucket) if isinstance(binfo, dict) else focus_bucket
            row_count = binfo.get("row_count", 0) if isinstance(binfo, dict) else 0
            bucket_context = (
                f"\n\n## Active Bucket\n"
                f"You are analyzing bucket: **{bucket_name}** ({row_count} rows). "
                f"Key: `{focus_bucket}`\n"
                f"Use `analyze_bucket(bucket='{focus_bucket}')` for this bucket's data.\n"
            )
        else:
            # All-buckets mode: union of all assigned skills across active buckets
            skills_to_load = []
            if isinstance(raw_buckets, dict):
                for binfo in raw_buckets.values():
                    if isinstance(binfo, dict):
                        for s in binfo.get("assigned_skills", []):
                            if s not in skills_to_load:
                                skills_to_load.append(s)

        # Fall back to full catalog only if bucketing ran without skill assignment
        if not skills_to_load:
            skills_to_load = list(ALL_DOMAIN_SKILLS)

        # Load: single skill → direct load (no list iteration); multiple → batch load
        if len(skills_to_load) == 1:
            loaded_skills = skill_loader.load_skill(skills_to_load[0])
        else:
            loaded_skills = skill_loader.load_skills(skills_to_load)

        return (
            bucket_context
            + "\n\n## Loaded Domain Skills\n"
            "Apply these domain skills through your specific analytical lens:\n\n"
            + loaded_skills
        )

    if agent_name == "synthesizer_agent":
        from pathlib import Path as _Path

        expected = state.get("expected_friction_lenses", []) or state.get("selected_friction_agents", [])
        expected = list(dict.fromkeys([a for a in expected if a]))
        parts = [
            "\n\n## Friction Agent Outputs\n",
            "Synthesize the following lens analyses into 10-12 top themes:\n",
        ]
        if expected:
            parts.append(
                "\nExpected lenses for this run: "
                + ", ".join(expected)
                + ". Set decision='complete' when all expected lenses have outputs.\n"
            )

        dimension_labels = {
            "digital_friction_agent": "Digital Friction",
            "operations_agent": "Operations",
            "communication_agent": "Communication",
            "policy_agent": "Policy",
        }

        # Phase 2 path: read per-lens synthesis files (one aggregated file per lens)
        lens_synthesis_paths = state.get("lens_synthesis_paths", {})
        if lens_synthesis_paths:
            for agent_id, label in dimension_labels.items():
                path = lens_synthesis_paths.get(agent_id, "")
                if path and _Path(path).exists():
                    content = _Path(path).read_text(encoding="utf-8")
                    logger.info("Synthesizer context (Phase 2): read %s (%d chars)", agent_id, len(content))
                    parts.append(f"\n### {label} Analysis\n{content}\n")
                else:
                    parts.append(f"\n### {label} Analysis\n(No output available)\n")
            return "\n".join(parts)

        # Nested friction_md_paths: {agent_id: {bucket_key: path}} or flat {agent_id: path}
        friction_md = state.get("friction_md_paths", {})
        for agent_id, label in dimension_labels.items():
            content = ""
            md_val = friction_md.get(agent_id, "")

            if isinstance(md_val, dict):
                # Nested: {bucket_key: md_path} — concatenate all bucket outputs
                bucket_parts = []
                for bk in sorted(md_val.keys()):
                    bpath = md_val[bk]
                    if bpath and _Path(bpath).exists():
                        bucket_parts.append(_Path(bpath).read_text(encoding="utf-8"))
                content = "\n\n".join(bucket_parts)
                logger.info("Synthesizer context: read %s from %d bucket files (%d chars)",
                            agent_id, len(bucket_parts), len(content))
            elif isinstance(md_val, str) and md_val and _Path(md_val).exists():
                # Flat legacy: single path string
                content = _Path(md_val).read_text(encoding="utf-8")
                logger.info("Synthesizer context: read %s from file (%d chars)", agent_id, len(content))

            parts.append(f"\n### {label} Agent Output\n{content}\n" if content
                         else f"\n### {label} Agent Output\n(No output available)\n")

        return "\n".join(parts)

    if agent_name in REPORTING_AGENTS:
        synthesis = state.get("synthesis_result", {})
        if not synthesis and state.get("synthesis_output_file"):
            import chainlit as cl
            data_store = cl.user_session.get("data_store")
            if data_store:
                loaded = data_store.get_text(state["synthesis_output_file"])
                if loaded:
                    synthesis = json.loads(loaded)
        findings = state.get("findings", [])
        retry_ctx = state.get("report_retry_context", {})
        def _clip(value: Any, limit: int = 240) -> str:
            text = str(value or "")
            return text if len(text) <= limit else text[:limit] + "..."

        summary_ctx = {
            "executive_narrative": _clip(synthesis.get("executive_narrative", ""), 700),
            "total_calls_analyzed": synthesis.get("total_calls_analyzed", 0),
            "total_themes": synthesis.get("total_themes", 0),
            "overall_preventability": synthesis.get("overall_preventability", 0),
            "dominant_drivers": synthesis.get("dominant_drivers", {}),
            "quick_wins_count": synthesis.get("quick_wins_count", 0),
        }

        compact_themes: list[dict[str, Any]] = []
        for t in synthesis.get("themes", []) if isinstance(synthesis, dict) else []:
            if not isinstance(t, dict):
                continue
            compact_themes.append({
                "theme": t.get("theme", ""),
                "call_count": t.get("call_count", 0),
                "call_percentage": t.get("call_percentage", 0.0),
                "impact_score": t.get("impact_score", 0.0),
                "ease_score": t.get("ease_score", 0.0),
                "priority_score": t.get("priority_score", 0.0),
                "priority_quadrant": t.get("priority_quadrant", ""),
                "dominant_driver": t.get("dominant_driver", ""),
                "contributing_factors": [_clip(x, 120) for x in (t.get("contributing_factors", []) or [])[:6]],
                "quick_wins": [_clip(x, 180) for x in (t.get("quick_wins", []) or [])[:6]],
                "all_drivers": [
                    {
                        "driver": _clip(d.get("driver", ""), 180),
                        "call_count": d.get("call_count", 0),
                        "contribution_pct": d.get("contribution_pct", 0.0),
                        "type": d.get("type", ""),
                        "dimension": d.get("dimension", ""),
                        "recommended_solution": _clip(d.get("recommended_solution", ""), 180),
                    }
                    for d in (t.get("all_drivers", []) or [])[:8]
                    if isinstance(d, dict)
                ],
            })

        compact_findings: list[dict[str, Any]] = []
        if isinstance(findings, list):
            for f in findings[:30]:
                if not isinstance(f, dict):
                    continue
                compact_findings.append({
                    "finding": _clip(f.get("finding", ""), 180),
                    "theme": _clip(f.get("theme", ""), 120),
                    "category": _clip(f.get("category", ""), 80),
                    "call_count": f.get("call_count", 0),
                    "call_percentage": f.get("call_percentage", 0.0),
                    "impact_score": f.get("impact_score", 0.0),
                    "ease_score": f.get("ease_score", 0.0),
                    "dominant_driver": f.get("dominant_driver", ""),
                    "priority_quadrant": f.get("priority_quadrant", ""),
                    "recommended_action": _clip(f.get("recommended_action", ""), 180),
                })

        if agent_name == "report_analyst":
            # Give report_analyst rich, structured context for report generation
            ctx: dict[str, Any] = {
                **summary_ctx,
                "themes": compact_themes,
                "findings": compact_findings,
                "filters_applied": state.get("filters_applied", {}),
                "report_file_path": state.get("report_file_path", ""),
                "markdown_file_path": state.get("markdown_file_path", ""),
                "data_file_path": state.get("data_file_path", ""),
            }
            parts = [
                "\n\n## Analysis Context\nUse this data to verify and deliver report artifacts.\n",
                json.dumps(ctx, indent=2, default=str),
            ]
            if isinstance(retry_ctx, dict) and retry_ctx.get("agent") == agent_name:
                parts.append("\n\n## Retry Requirements (Mandatory)\n")
                parts.append(json.dumps(retry_ctx, indent=2, default=str))
            return "".join(parts)

        ctx: dict[str, Any] = {
            "summary": summary_ctx,
            "themes": compact_themes,
            "findings": compact_findings,
            "filters_applied": state.get("filters_applied", {}),
        }
        if agent_name == "formatting_agent":
            ctx = _build_formatting_context(summary_ctx, state)

        rules = ""
        if agent_name == "narrative_agent":
            rules = (
                "\n\n## Tool Execution Requirements (Mandatory)\n"
                "- Call `get_findings_summary` before final output.\n"
                "- Final output must be pure markdown.\n"
                "- Include explicit `<!-- SLIDE: ... -->` boundary tags for every slide.\n"
                "- Do not return JSON.\n"
            )
        elif agent_name == "formatting_agent":
            rules = (
                "\n\n## Output Contract (Mandatory)\n"
                "- Return ONLY valid JSON matching the structured slide blueprint schema.\n"
                "- Include deck-level fields plus slide-level `slide_number`, `section_type`, `layout`, and `title`.\n"
                "- Use explicit `image_prompt.placeholder_id` values from `chart_placeholders`.\n"
                "- Do not call export tools from this agent.\n"
            )

        parts = ["\n\n## Analysis Context\n", json.dumps(ctx, indent=2, default=str), rules]
        if isinstance(retry_ctx, dict) and retry_ctx.get("agent") == agent_name:
            parts.append("\n\n## Retry Requirements (Mandatory)\n")
            parts.append(json.dumps(retry_ctx, indent=2, default=str))
            parts.append(
                "\nRetry now. Do not provide an empty response. Satisfy all mandatory constraints before finalizing.\n"
            )
        return "".join(parts)

    if agent_name == "supervisor":
        parts = []
        # Inject available filters so supervisor can match user queries to real columns
        schema = state.get("dataset_schema", {})
        if schema:
            parts.append("## Available Dataset Filters\n")
            parts.append("Use these to match user queries to actual data columns and values.\n\n")
            for col, values in schema.items():
                if len(values) <= 20:
                    parts.append(f"- **{col}**: {values}\n")
                else:
                    parts.append(f"- **{col}**: {values[:20]} ... ({len(values)} total)\n")
            parts.append("\n")

        parts.append("## Current State Context\n")
        # Build data_buckets summary for insight presentation
        raw_buckets = state.get("data_buckets", {})
        bucket_summary = {}
        if isinstance(raw_buckets, dict):
            for bname, binfo in raw_buckets.items():
                if isinstance(binfo, dict):
                    bucket_summary[bname] = {
                        "row_count": binfo.get("row_count", binfo.get("count", "?")),
                    }
                else:
                    bucket_summary[bname] = {"row_count": "?"}
        state_ctx: dict[str, Any] = {
            "filters_applied": state.get("filters_applied", {}),
            "themes_for_analysis": state.get("themes_for_analysis", []),
            "top_themes": state.get("top_themes", []),
            "data_buckets": bucket_summary,
            "navigation_log": state.get("navigation_log", []),
            "analysis_objective": state.get("analysis_objective", ""),
            "plan_tasks": state.get("plan_tasks", []),
            "plan_steps_completed": state.get("plan_steps_completed", 0),
            "plan_steps_total": state.get("plan_steps_total", 0),
        }
        # Inject compact analytics insights when synthesizer has run — allows
        # supervisor to answer questions like "what are the top issues?" without
        # re-running the full pipeline.
        insights = state.get("analytics_insights", {})
        if insights:
            state_ctx["analytics_insights"] = insights
            parts.insert(0, "## Analysis Insights Available\nYou can answer factual questions about the analysis results using `analytics_insights` below.\n\n")
        parts.append(json.dumps(state_ctx, indent=2, default=str))
        return "\n\n" + "\n".join(parts)

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

    if agent_name == "data_analyst":
        parts = []
        # Inject available filters from dataset schema
        schema = state.get("dataset_schema", {})
        if schema:
            parts.append("## Available Filters (from loaded dataset)\n")
            parts.append("Use ONLY these exact column names and values when calling filter_data.\n")
            parts.append("Do NOT guess column names -- use the ones listed here.\n\n")
            for col, values in schema.items():
                if len(values) <= 20:
                    parts.append(f"- **{col}**: {values}\n")
                else:
                    parts.append(f"- **{col}**: {values[:20]} ... ({len(values)} total)\n")
        else:
            parts.append("## Available Filters\n")
            parts.append("No filter catalog available yet. Use load_dataset first to discover the schema.\n")

        # Also inject current state context
        parts.append("\n## Current Data State\n")
        parts.append(json.dumps({
            "filters_applied": state.get("filters_applied", {}),
            "dataset_path": state.get("dataset_path", ""),
            "analysis_objective": state.get("analysis_objective", ""),
        }, indent=2, default=str))
        return "\n\n" + "\n".join(parts)

    return ""




def _extract_formatting_state(
    state: AnalyticsState, updates: dict[str, Any]
) -> None:
    """Extract report artifact paths from tool-result messages.

    Used primarily by report_analyst when it performs tool-based recovery.
    It scans tool JSON payloads and updates report/ppt/csv/markdown paths.
    """
    messages = updates.get("messages", [])
    logger.info(
        "Formatting extraction: scanning %d messages for tool result paths", len(messages),
    )
    for msg in messages:
        if not hasattr(msg, "content"):
            continue
        content = _text(msg.content)
        data = _parse_json(content)
        if not data:
            continue

        logger.debug("Formatting extraction: parsed JSON keys=%s", list(data.keys()))

        # export_to_pptx returns {"pptx_path": "..."}
        if "pptx_path" in data:
            updates["report_file_path"] = data["pptx_path"]
            logger.info("Formatting Agent: extracted report_file_path=%s", data["pptx_path"])

        # export_filtered_csv returns {"csv_path": "..."}
        if "csv_path" in data:
            updates["data_file_path"] = data["csv_path"]
            logger.info("Formatting Agent: extracted data_file_path=%s", data["csv_path"])

        # markdown artifact payload returns {"report_key": "...", "markdown_path": "..."}
        if "report_key" in data:
            updates["report_markdown_key"] = data["report_key"]
            logger.info("Formatting Agent: extracted report_markdown_key=%s", data["report_key"])
        if "markdown_path" in data:
            updates["markdown_file_path"] = data["markdown_path"]
            logger.info("Formatting Agent: extracted markdown_file_path=%s", data["markdown_path"])


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

        if "filtered_rows" in data:
            logger.info(
                "[DATA][filter_data] rows original=%s filtered=%s reduction_pct=%s filters=%s",
                data.get("original_rows", "?"),
                data.get("filtered_rows", "?"),
                data.get("reduction_pct", "?"),
                list((data.get("filters_applied") or {}).keys()),
            )

        # filter_data tool returns "filters_applied" key with the applied filters
        if "filters_applied" in data:
            filters = data["filters_applied"]
            if filters and isinstance(filters, dict):
                updates["filters_applied"] = filters
                logger.info("[DATA][filter_data] filters_applied=%s", filters)

        # filter_data returns filtered_parquet_path — completion flag for data_analyst step
        if "filtered_parquet_path" in data:
            updates["filtered_parquet_path"] = data["filtered_parquet_path"]
            logger.info("[DATA][filter_data] filtered_parquet_path=%s", data["filtered_parquet_path"])

        # bucket_data returns themes and bucket paths
        if "themes" in data:
            updates["themes_for_analysis"] = data["themes"]
            logger.info("[DATA][bucket_data] themes_for_analysis=%s", data["themes"])
        if "buckets" in data:
            updates["data_buckets"] = data["buckets"]
            # Top-level theme names for supervisor quick-answers
            bucket_names = [
                info.get("bucket_name", key)
                for key, info in data["buckets"].items()
                if isinstance(info, dict)
            ]
            if bucket_names and "themes_for_analysis" not in updates:
                updates["themes_for_analysis"] = bucket_names
            updates["top_themes"] = bucket_names
            bucket_rows: list[tuple[str, int]] = []
            for key, info in data["buckets"].items():
                if not isinstance(info, dict):
                    continue
                name = str(info.get("bucket_name", key))
                count_raw = info.get("row_count", info.get("count", 0))
                try:
                    count = int(count_raw)
                except (TypeError, ValueError):
                    count = 0
                bucket_rows.append((name, count))
            bucket_rows.sort(key=lambda x: x[1], reverse=True)
            calls_by_theme = ", ".join([f"{name}:{count}" for name, count in bucket_rows]) or "none"
            logger.info(
                "[DATA][bucket_data] themes=%d calls_by_theme=%s",
                len(bucket_rows),
                calls_by_theme,
            )
        if "bucket_paths" in data:
            updates["bucket_paths"] = data["bucket_paths"]
            logger.info("[DATA][bucket_data] bucket_paths=%s", list(data["bucket_paths"].keys()))

    # If no tool results found, still mark that data_analyst ran
    # by setting a minimal filters_applied so the supervisor knows.
    if "filters_applied" not in updates and not state.get("filters_applied"):
        updates["filters_applied"] = {"status": "extraction_attempted"}
        logger.info("[DATA][filter_data] no filter results found, marking extraction_attempted")


def _parse_dimension_preferences(
    state: AnalyticsState, updates: dict[str, Any]
) -> None:
    """Parse user's last message for friction dimension preferences.

    If the user mentions specific dimensions (e.g., "digital and operations"),
    update selected_friction_agents to run only those.  If the user says
    "all" / "yes" / "proceed" or doesn't mention specifics, keep all 4.
    """
    lens_order = [
        "digital_friction_agent",
        "operations_agent",
        "communication_agent",
        "policy_agent",
    ]
    dimension_aliases: dict[str, set[str]] = {
        "digital_friction_agent": {
            "digital", "degital", "digtal", "digitel", "ux", "ui", "app", "web", "website",
        },
        "operations_agent": {
            "operations", "operation", "operational", "process", "workflow", "handoff", "sla",
        },
        "communication_agent": {
            "communication", "communications", "comms", "messaging", "notification",
            "communcation", "cmmunication", "comunication", "communicaton", "communiction",
        },
        "policy_agent": {
            "policy", "policies", "governance", "regulatory", "compliance", "rule", "rules",
        },
    }
    all_markers = (
        "all",
        "all dimensions",
        "all lenses",
        "run all",
        "everything",
    )

    last_user_msg = ""
    for m in reversed(state.get("messages", [])):
        if getattr(m, "type", "") == "human":
            last_user_msg = _text(m.content).lower()
            break

    if not last_user_msg:
        return

    normalized = re.sub(r"[^a-z0-9\s]", " ", last_user_msg)
    tokens = set(re.findall(r"[a-z]+", normalized))

    if any(marker in normalized for marker in all_markers):
        updates["selected_friction_agents"] = list(lens_order)
        updates["expected_friction_lenses"] = list(lens_order)
        logger.info("Supervisor: user selected dimensions=all (%s)", lens_order)
        return

    def _matches_aliases(aliases: set[str]) -> bool:
        # Direct phrase match for multi-word aliases.
        for alias in aliases:
            if " " in alias and alias in normalized:
                return True

        single_word_aliases = [a for a in aliases if " " not in a]
        if tokens.intersection(single_word_aliases):
            return True

        # Tolerate common misspellings: e.g., "cmmunication", "degital".
        fuzzy_aliases = [a for a in single_word_aliases if len(a) >= 5]
        for token in tokens:
            if len(token) < 5:
                continue
            if get_close_matches(token, fuzzy_aliases, n=1, cutoff=0.82):
                return True
        return False

    mentioned = [
        agent_id
        for agent_id in lens_order
        if _matches_aliases(dimension_aliases.get(agent_id, set()))
    ]

    if mentioned:
        selected_unique = list(dict.fromkeys(mentioned))
        updates["selected_friction_agents"] = selected_unique
        updates["expected_friction_lenses"] = selected_unique
        logger.info("Supervisor: user selected dimensions=%s", selected_unique)


def _enforce_synthesis_completeness_guard(
    state: AnalyticsState,
    updates: dict[str, Any],
    planned_next_agent: str,
) -> bool:
    """Before report_generation, reroute if synthesis is incomplete.

    Returns True if routing was overridden.
    """
    if planned_next_agent != "report_generation":
        return False

    expected = state.get("expected_friction_lenses", []) or state.get("selected_friction_agents", [])
    expected = list(dict.fromkeys([a for a in expected if a]))

    # Primary source: per-lens synthesis files produced by friction_analysis phase 1.
    available = list((state.get("lens_synthesis_paths", {}) or {}).keys())
    if not available:
        # Legacy fallback for older sessions.
        available = list((state.get("friction_output_files", {}) or {}).keys())

    if expected:
        missing = [a for a in expected if a not in available]
    else:
        # If expected lenses are unknown, fall back to explicit synthesizer output.
        missing = state.get("missing_friction_lenses", []) or []
    missing = list(dict.fromkeys([a for a in missing if a]))

    synthesis = state.get("synthesis_result", {})
    decision = synthesis.get("decision", "") if isinstance(synthesis, dict) else ""
    # Deterministic gate: if all expected lens outputs are present, allow progress.
    if not missing:
        if expected or decision != "incomplete":
            return False
        # decision is incomplete and expected lenses are unknown -> ask user to clarify.
        updates["next_agent"] = "user_checkpoint"
        updates["requires_user_input"] = True
        updates["checkpoint_message"] = (
            "Synthesis is incomplete and expected friction lenses are not clearly defined."
        )
        updates["checkpoint_prompt"] = (
            "Reply 'rerun all lenses' to rerun friction analysis, or specify lenses to rerun "
            "(digital, operations, communication, policy)."
        )
        updates["pending_input_for"] = "synthesis_completion_check"
        updates["checkpoint_token"] = str(uuid.uuid4())[:8]
        updates["plan_tasks"] = state.get("plan_tasks", [])
        logger.warning(
            "Supervisor guard: synthesis incomplete with unknown expected lenses; requesting user checkpoint."
        )
        return True

    if missing:
        updates["next_agent"] = "friction_analysis"
        updates["selected_friction_agents"] = missing
        updates["expected_friction_lenses"] = expected or missing
        updates["missing_friction_lenses"] = missing
        updates["plan_tasks"] = state.get("plan_tasks", [])
        updates["reasoning"] = [{
            "step_name": "Supervisor",
            "step_text": f"Synthesis incomplete. Re-running missing friction lenses: {', '.join(missing)}.",
        }]
        logger.warning(
            "Supervisor guard: blocked report_generation due incomplete synthesis; rerouting to friction_analysis with missing=%s",
            missing,
        )
        return True

    return False


def _has_real_filters(state: AnalyticsState) -> bool:
    existing_filters = state.get("filters_applied", {})
    return bool(
        existing_filters
        and isinstance(existing_filters, dict)
        and existing_filters.get("status") != "extraction_attempted"
        and any(k != "status" for k in existing_filters)
    )


def _count_consecutive_data_analyst_loops(state: AnalyticsState) -> int:
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
    return consecutive


def _apply_analyse_transition(state: AnalyticsState, updates: dict[str, Any], target_agent: str) -> None:
    updates["next_agent"] = target_agent
    _parse_dimension_preferences(state, updates)
    if "expected_friction_lenses" not in updates:
        current = state.get("selected_friction_agents", [])
        updates["expected_friction_lenses"] = list(dict.fromkeys([a for a in current if a]))
    updates["missing_friction_lenses"] = []


def _apply_extract_transition(
    state: AnalyticsState,
    updates: dict[str, Any],
    *,
    target_agent: str,
    log_prefix: str,
    bootstrap_tasks: bool,
) -> None:
    if _has_real_filters(state):
        logger.info(
            "%s: filters already applied (%s), forcing extract -> analyse",
            log_prefix,
            state.get("filters_applied", {}),
        )
        updates["next_agent"] = "planner"
        updates["supervisor_decision"] = "analyse"
        return

    consecutive = _count_consecutive_data_analyst_loops(state)
    if consecutive >= MAX_SUPERVISOR_LOOPS:
        logger.warning(
            "%s loop detected: %d consecutive extract->data_analyst cycles. "
            "Forcing transition to 'analyse' (planner).",
            log_prefix,
            consecutive,
        )
        updates["next_agent"] = "planner"
        updates["supervisor_decision"] = "analyse"
        return

    updates["next_agent"] = target_agent
    if bootstrap_tasks and not state.get("plan_tasks"):
        updates["plan_tasks"] = _PRELIMINARY_PLAN_TASKS()
        updates["plan_steps_total"] = len(updates["plan_tasks"])


def _apply_supervisor(s: SupervisorOutput, state: AnalyticsState, updates: dict) -> None:
    """Map SupervisorOutput -> state updates."""
    updates["supervisor_decision"] = s.decision
    updates["reasoning"] = [{"step_name": "Supervisor", "step_text": s.reasoning}]
    suppress_model_response = False

    target_agent = _DECISION_TO_NEXT.get(s.decision, "__end__")

    if s.decision == "execute":
        plan, agent = _find_next_plan_agent(state.get("plan_tasks", []))
        updates["next_agent"] = agent
        updates["plan_tasks"] = plan
        if _enforce_synthesis_completeness_guard(state, updates, agent):
            suppress_model_response = True
    elif s.decision == "extract":
        _apply_extract_transition(
            state,
            updates,
            target_agent=target_agent,
            log_prefix="Supervisor",
            bootstrap_tasks=True,
        )
    elif s.decision == "analyse":
        _apply_analyse_transition(state, updates, target_agent)
    else:
        updates["next_agent"] = target_agent

    # Only emit supervisor chat text for direct user answers/clarifications.
    # For orchestration decisions (extract/analyse/execute), keep reasoning trace
    # but suppress extra chat chatter to avoid repetitive status messages.
    if s.response and not suppress_model_response and s.decision in ("answer", "clarify"):
        updates["messages"] = [AIMessage(content=s.response)]

    logger.info("Supervisor (structured): %s -> %s (confidence=%d)", s.decision, updates["next_agent"], s.confidence)


def _apply_supervisor_fallback(raw: str, state: AnalyticsState, updates: dict) -> None:
    """Map legacy JSON supervisor output -> state updates."""
    data = _parse_json(raw)
    decision = data.get("decision", "")
    if decision not in _DECISION_TO_NEXT:
        logger.warning("Supervisor fallback: unrecognised decision %r", decision)
        return

    updates["supervisor_decision"] = decision
    suppress_model_response = False
    if decision == "execute":
        plan, agent = _find_next_plan_agent(state.get("plan_tasks", []))
        updates["next_agent"] = agent
        updates["plan_tasks"] = plan
        if _enforce_synthesis_completeness_guard(state, updates, agent):
            suppress_model_response = True
    elif decision == "extract":
        _apply_extract_transition(
            state,
            updates,
            target_agent=_DECISION_TO_NEXT[decision],
            log_prefix="Supervisor fallback",
            bootstrap_tasks=False,
        )
    elif decision == "analyse":
        _apply_analyse_transition(state, updates, _DECISION_TO_NEXT[decision])
    else:
        updates["next_agent"] = _DECISION_TO_NEXT[decision]

    if decision in ("answer", "clarify") and data.get("response") and not suppress_model_response:
        updates["messages"] = [AIMessage(content=data["response"])]

    logger.info("Supervisor (fallback): %s -> %s (confidence=%s)", decision, updates.get("next_agent", "?"), data.get("confidence", "?"))


# ------------------------------------------------------------------
# Plan progress
# ------------------------------------------------------------------


def _advance_plan(agent_name: str, state: AnalyticsState, updates: dict) -> None:
    """Mark the agent's task done and check pipeline completion."""
    tasks = [dict(t) for t in updates.get("plan_tasks", state.get("plan_tasks", []))]
    status_changed = False
    for t in tasks:
        if t.get("agent") == agent_name and t.get("status") != "done":
            t["status"] = "done"
            status_changed = True
            break
    updates["plan_tasks"] = tasks

    total = max(state.get("plan_steps_total", 0), len(tasks))
    done_count = len([t for t in tasks if t.get("status") == "done"])
    completed = max(state.get("plan_steps_completed", 0), done_count)

    updates["plan_steps_total"] = total
    updates["plan_steps_completed"] = completed
    logger.info(
        "Plan progress: %d/%d (agent=%s%s)",
        completed, total, agent_name, "" if status_changed else ", no status change",
    )

    if total > 0 and completed >= total:
        updates["analysis_complete"] = True
        updates["phase"] = "qa"
        logger.info("Pipeline complete -- entering Q&A mode.")

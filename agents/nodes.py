"""Node functions for each agent in the analytics graph.

Each node is a thin async wrapper that:
1. Invokes the agent (pre-bound structured chain or per-call ReAct agent)
2. Applies structured-output -> state mapping for decision agents
3. Tracks plan progress (only for agents listed in plan_tasks)
4. Records execution_trace for the Chainlit UI

State rule enforced here: nothing large lives in state.
Agents read files, write files, update path fields only.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

from agents.schemas import (
    CritiqueOutput,
    PlannerOutput,
    STRUCTURED_OUTPUT_SCHEMAS,
    SupervisorOutput,
    SynthesizerOutput,
)
from agents.state import AnalyticsState
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


# Supervisor decision -> next node routing
_DECISION_TO_NEXT: dict[str, str] = {
    "answer": "__end__",
    "plan": "planner",
    "execute": "",  # resolved from plan_tasks
}

MAX_SUPERVISOR_LOOPS = 2
ANALYSIS_START_NODES = {"planner", "friction_analysis"}
ANALYSIS_CONFIRMATION_PENDING = "analysis_dimension_confirmation"

LLM_INPUT_FIELDS: dict[str, list[str]] = {
    "supervisor": [
        "messages", "dataset_schema", "filters_applied",
        "themes_for_analysis", "plan_tasks", "analysis_objective",
        "analysis_scope_reply", "pending_input_for",
    ],
    "planner": [
        "filters_applied", "analysis_objective", "analysis_scope_reply", "critique_enabled",
    ],
    "data_analyst": [
        "messages", "dataset_path", "dataset_schema", "analysis_objective",
    ],
    "digital_friction_agent": [
        "messages", "bucket_manifest_path", "_focus_bucket_id", "filters_applied", "analysis_objective",
    ],
    "operations_agent": [
        "messages", "bucket_manifest_path", "_focus_bucket_id", "filters_applied", "analysis_objective",
    ],
    "communication_agent": [
        "messages", "bucket_manifest_path", "_focus_bucket_id", "filters_applied", "analysis_objective",
    ],
    "policy_agent": [
        "messages", "bucket_manifest_path", "_focus_bucket_id", "filters_applied", "analysis_objective",
    ],
    "specialist_agent": [
        "messages", "bucket_manifest_path", "_focus_bucket_id", "filters_applied", "analysis_objective",
    ],
    "synthesizer_agent": [
        "messages", "lens_outputs_dir", "selected_agents",
    ],
    "solutioning_agent": [
        "messages", "synthesis_path",
    ],
    "narrative_agent": [
        "messages", "classified_solutions_path", "synthesis_path", "filters_applied",
    ],
    "report_analyst": [
        "messages", "artifacts_dir",
    ],
    "critique": [
        "messages", "synthesis_path",
    ],
    "qna_agent": [
        "messages", "artifacts_dir",
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
    """Return skill names for a lens agent based on the focused bucket's manifest entry."""
    if agent_name not in FRICTION_AGENTS:
        return []
    focus_bucket_id = str(state.get("_focus_bucket_id", "") or "")
    manifest_path = state.get("bucket_manifest_path", "")
    if not manifest_path or not Path(manifest_path).exists():
        return []
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        for bucket in manifest.get("buckets", []):
            if bucket.get("bucket_id") == focus_bucket_id:
                return list(bucket.get("skills", []) or [])
    except Exception:
        pass
    return []


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
        {"title": "Solution classification", "agent": "solutioning_agent", "status": "ready"},
        {"title": "Generate report drafts", "agent": "report_drafts", "status": "ready"},
        {"title": "Create report artifacts", "agent": "artifact_writer", "status": "ready"},
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
    if "```" in text:
        for part in text.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except (json.JSONDecodeError, ValueError):
                continue
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
    """Find the first pending task, mark it in_progress, return (updated_tasks, agent)."""
    updated = [dict(t) for t in plan_tasks]
    for task in updated:
        if task.get("status") == "in_progress":
            return updated, task.get("agent", "__end__")
    for task in updated:
        if task.get("status") in ("ready", "todo"):
            task["status"] = "in_progress"
            return updated, task.get("agent", "__end__")
    return updated, "__end__"


def _peek_next_plan_agent(plan_tasks: list[dict]) -> str:
    """Return next actionable plan agent without mutating task statuses."""
    for task in plan_tasks:
        if task.get("status") == "in_progress":
            return task.get("agent", "__end__")
    for task in plan_tasks:
        if task.get("status") in ("ready", "todo"):
            return task.get("agent", "__end__")
    return "__end__"


def _clear_checkpoint_fields() -> dict[str, Any]:
    return {
        "checkpoint_message": "",
        "checkpoint_prompt": "",
        "pending_input_for": "",
    }


def _advance_plan(agent_name: str, state: AnalyticsState, updates: dict[str, Any]) -> None:
    """Mark the current task done and compute next step counts."""
    tasks = [dict(t) for t in (updates.get("plan_tasks") or state.get("plan_tasks") or [])]
    for t in tasks:
        if t.get("agent") == agent_name and t.get("status") == "in_progress":
            t["status"] = "done"
            break
    done = len([t for t in tasks if t.get("status") == "done"])
    updates["plan_tasks"] = tasks
    updates["plan_steps_completed"] = done
    updates["plan_steps_total"] = len(tasks)


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
# Blocked response sentinel check
# ------------------------------------------------------------------

_BLOCKED_SENTINEL = "[Model returned no response"


def _check_blocked_response(agent_name: str, messages: list) -> None:
    """Raise if the last AI message is the 'model blocked' sentinel."""
    for m in reversed(messages):
        if getattr(m, "type", "") == "ai" and hasattr(m, "content"):
            text = str(m.content or "")
            if text.startswith(_BLOCKED_SENTINEL):
                raise RuntimeError(
                    f"[{agent_name}] Model response was blocked by Vertex AI safety filters. "
                    f"Full response: {text}"
                )
            break


# ------------------------------------------------------------------
# Thin invocation helpers
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
        agent_name, state,
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

    trace_entry = {
        "step_id": step_id,
        "agent": agent_name,
        "input_summary": input_summary,
        "output_summary": summary,
        "tools_used": tools_used,
        "latency_ms": elapsed,
        "success": True,
    }

    base: dict[str, Any] = {
        "messages": new_msgs,
        "execution_trace": [trace_entry],
        "last_completed_node": agent_name,
        **_clear_checkpoint_fields(),
    }
    logger.info(
        "[NODE][DONE ] %s elapsed_ms=%d structured=%s tools=%s new_msgs=%d",
        agent_name, elapsed,
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
        agent_name, state,
        prompt_chars=base_prompt_chars,
        context_chars=len(extra_context or ""),
    )

    agent = agent_factory.make_agent(agent_name, extra_context=extra_context)
    result = await agent.ainvoke({"messages": state["messages"]})
    elapsed = int(time.time() * 1000) - start_ms

    _check_blocked_response(agent_name, result.get("messages", []))

    input_ids = {m.id for m in state["messages"] if hasattr(m, "id") and m.id}
    new_msgs = [
        m for m in result["messages"]
        if not (hasattr(m, "id") and m.id and m.id in input_ids)
    ]
    last_msg = new_msgs[-1] if new_msgs else None
    summary = _trunc(_text(last_msg.content), 200) if last_msg and hasattr(last_msg, "content") else ""
    tools_used = [tc.get("name", "?") for m in new_msgs if hasattr(m, "tool_calls") for tc in m.tool_calls]
    input_summary = _text(state["messages"][-1].content)[:200] if state["messages"] else ""

    trace_entry = {
        "step_id": step_id,
        "agent": agent_name,
        "input_summary": input_summary,
        "output_summary": summary,
        "tools_used": tools_used,
        "latency_ms": elapsed,
        "success": True,
    }

    base: dict[str, Any] = {
        "messages": new_msgs,
        "execution_trace": [trace_entry],
        "last_completed_node": agent_name,
        **_clear_checkpoint_fields(),
    }
    logger.info(
        "[NODE][DONE ] %s elapsed_ms=%d tools=%s new_msgs=%d",
        agent_name, elapsed,
        ", ".join(tools_used) or "none",
        len(new_msgs),
    )
    return base, last_msg


def _write_versioned(base_name: str, content: str, metadata: dict, ext: str = "md") -> str:
    """Write content to a versioned file in the session cache.

    File lands in data/.cache/<thread_id>/<base_name>_v<n>.<ext>.
    Pass ext="json" for JSON data, ext="md" for markdown.

    Returns the absolute file path (use as completion flag).
    """
    import chainlit as cl
    data_store = cl.user_session.get("data_store")
    if data_store:
        _key, path = data_store.store_versioned(base_name, content, metadata, ext=ext)
        return path
    return ""


def _read_text(path: str | Path) -> str:
    """Read a text or markdown file. Returns empty string if path is missing."""
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _read_json(path: str | Path) -> Any:
    """Read and parse a JSON file. Returns empty dict if path is missing or invalid."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}


def _write_file(dest_path: str | Path, content: str) -> str:
    """Write content to a fixed path (not versioned). Returns the path string."""
    p = Path(dest_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p)


# ------------------------------------------------------------------
# Extra context builders
# ------------------------------------------------------------------


def _build_extra_context(
    agent_name: str,
    state: AnalyticsState,
    skill_loader: SkillLoader | None,
) -> str:
    """Build agent-specific context to append to the system prompt."""

    # ── Lens agents (digital, ops, comms, policy, specialist) ──────────
    if agent_name in FRICTION_AGENTS or agent_name == "specialist_agent":
        focus_bucket_id = str(state.get("_focus_bucket_id", "") or "")
        manifest_path = state.get("bucket_manifest_path", "")
        bucket_context = ""

        # Read bucket metadata from manifest
        skills_to_load: list[str] = []
        specialist_skill: str | None = None
        if manifest_path and Path(manifest_path).exists():
            try:
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                for bucket in manifest.get("buckets", []):
                    if bucket.get("bucket_id") == focus_bucket_id:
                        bucket_name = bucket.get("bucket_name", focus_bucket_id)
                        row_count = bucket.get("row_count", 0)
                        skills_to_load = list(bucket.get("skills", []) or [])
                        specialist_skill = bucket.get("specialist_skill")
                        bucket_context = (
                            f"\n\n## Active Bucket\n"
                            f"You are analyzing bucket: **{bucket_name}** ({row_count} rows). "
                            f"Bucket ID: `{focus_bucket_id}`\n"
                            f"Use `analyze_bucket(bucket='{focus_bucket_id}')` for this bucket's data.\n"
                        )
                        break
                if not skills_to_load and not focus_bucket_id:
                    # All-buckets mode: union of all skills
                    for bucket in manifest.get("buckets", []):
                        for s in bucket.get("skills", []) or []:
                            if s and s not in skills_to_load:
                                skills_to_load.append(s)
            except Exception:
                pass

        if agent_name == "specialist_agent" and specialist_skill and skill_loader:
            loaded_skills = skill_loader.load_skill(specialist_skill)
            return (
                bucket_context
                + "\n\n## Specialist Domain Knowledge\n"
                "You are the specialist agent. Apply the deep domain knowledge below:\n\n"
                + loaded_skills
            )

        if not skills_to_load:
            skills_to_load = list(ALL_DOMAIN_SKILLS)

        if skill_loader:
            if len(skills_to_load) == 1:
                loaded_skills = skill_loader.load_skill(skills_to_load[0])
            else:
                loaded_skills = skill_loader.load_skills(skills_to_load)
        else:
            loaded_skills = ""

        return (
            bucket_context
            + "\n\n## Loaded Domain Skills\n"
            "Apply these domain skills through your specific analytical lens:\n\n"
            + loaded_skills
        )

    # ── Synthesizer ────────────────────────────────────────────────────
    if agent_name == "synthesizer_agent":
        lens_outputs_dir = state.get("lens_outputs_dir", "")
        parts = ["\n\n## Friction Agent Outputs\nSynthesize the following lens analyses:\n"]
        if lens_outputs_dir and Path(lens_outputs_dir).is_dir():
            # Read per-lens synthesis files (*_synthesis.md)
            synthesis_files = sorted(Path(lens_outputs_dir).glob("*_synthesis.md"))
            for sf in synthesis_files:
                content = sf.read_text(encoding="utf-8")
                label = sf.stem.replace("_synthesis", "").replace("_", " ").title()
                parts.append(f"\n### {label}\n{content}\n")
        return "\n".join(parts)

    # ── Solutioning agent ──────────────────────────────────────────────
    if agent_name == "solutioning_agent":
        from config import SOLUTIONS_REGISTRY_PATH
        parts = []
        synthesis_path = state.get("synthesis_path", "")
        if synthesis_path and Path(synthesis_path).exists():
            content = Path(synthesis_path).read_text(encoding="utf-8")
            parts.append("\n\n## Friction Synthesis\n" + content)
        registry_path = Path(SOLUTIONS_REGISTRY_PATH)
        if registry_path.exists():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            parts.append("\n\n## Solutions Registry\n" + json.dumps(registry, indent=2))
        return "\n".join(parts)

    # ── Narrative agent ────────────────────────────────────────────────
    if agent_name == "narrative_agent":
        parts = []
        classified_path = state.get("classified_solutions_path", "")
        if classified_path and Path(classified_path).exists():
            classified = json.loads(Path(classified_path).read_text(encoding="utf-8"))
            parts.append("\n\n## Classified Solutions\n" + json.dumps(classified, indent=2, default=str))
        synthesis_path = state.get("synthesis_path", "")
        if synthesis_path and Path(synthesis_path).exists():
            parts.append("\n\n## Synthesis Summary\n" + Path(synthesis_path).read_text(encoding="utf-8"))
        ctx = {
            "filters_applied": state.get("filters_applied", {}),
        }
        parts.append("\n\n## Context\n" + json.dumps(ctx, indent=2, default=str))
        return "".join(parts)

    # ── Report analyst ─────────────────────────────────────────────────
    if agent_name == "report_analyst":
        artifacts_dir = state.get("artifacts_dir", "")
        parts = ["\n\n## Report Artifacts"]
        if artifacts_dir and Path(artifacts_dir).is_dir():
            files = list(Path(artifacts_dir).iterdir())
            file_list = {f.name: str(f) for f in files if f.is_file()}
            parts.append(json.dumps(file_list, indent=2))
        else:
            parts.append(f"Artifacts directory: {artifacts_dir or '(not yet created)'}")
        return "\n".join(parts)

    # ── QnA agent ──────────────────────────────────────────────────────
    if agent_name == "qna_agent":
        artifacts_dir = state.get("artifacts_dir", "")
        md_path = Path(artifacts_dir) / "complete_analysis.md" if artifacts_dir else None
        if md_path and md_path.exists():
            return (
                "\n\n## Analysis Report\n"
                "Use ONLY the content below to answer the user's question.\n\n"
                + md_path.read_text(encoding="utf-8")
            )
        return "\n\n## Analysis Report\nNo report has been generated yet."

    # ── Supervisor ─────────────────────────────────────────────────────
    if agent_name == "supervisor":
        parts = []
        schema = state.get("dataset_schema", {})
        parts.append("## Available Dataset Filters\n")
        for col, values in schema.items():
            if len(values) <= 20:
                parts.append(f"- **{col}**: {values}\n")
            else:
                parts.append(f"- **{col}**: {values[:20]} ... ({len(values)} total)\n")

        parts.append("\n## Current State Context\n")
        state_ctx: dict[str, Any] = {
            "filters_applied": state.get("filters_applied", {}),
            "themes_for_analysis": state.get("themes_for_analysis", []),
            "analysis_objective": state.get("analysis_objective", ""),
            "plan_tasks": state.get("plan_tasks", []),
            "plan_steps_completed": state.get("plan_steps_completed", 0),
            "plan_steps_total": state.get("plan_steps_total", 0),
        }
        if state.get("artifacts_dir") and Path(state["artifacts_dir"]).is_dir():
            md = Path(state["artifacts_dir"]) / "complete_analysis.md"
            state_ctx["report_generated"] = md.exists()
        parts.append(json.dumps(state_ctx, indent=2, default=str))
        return "\n\n" + "\n".join(parts)

    # ── Planner ────────────────────────────────────────────────────────
    if agent_name == "planner":
        ctx: dict[str, Any] = {
            "filters_applied": state.get("filters_applied", {}),
            "analysis_objective": state.get("analysis_objective", ""),
            "analysis_scope_reply": state.get("analysis_scope_reply", ""),
            "critique_enabled": state.get("critique_enabled", False),
            "plan_tasks": state.get("plan_tasks", []),
            "allowed_selected_agents": list(FRICTION_AGENTS),
        }
        manifest_path = state.get("bucket_manifest_path", "")
        if manifest_path and Path(manifest_path).exists():
            try:
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                ctx["bucket_summary"] = {
                    b["bucket_id"]: {"bucket_name": b["bucket_name"], "row_count": b["row_count"]}
                    for b in manifest.get("buckets", [])
                }
            except Exception:
                pass
        if state.get("synthesis_path") and Path(state["synthesis_path"]).exists():
            ctx["synthesis_done"] = True
        if state.get("classified_solutions_path"):
            ctx["solutioning_done"] = True
        if state.get("narrative_path"):
            ctx["narrative_done"] = True
        if state.get("blueprint_path"):
            ctx["blueprint_done"] = True
        return "\n\n## Planning Context\n" + json.dumps(ctx, indent=2, default=str)

    # ── Data analyst ───────────────────────────────────────────────────
    if agent_name == "data_analyst":
        parts = []
        schema = state.get("dataset_schema", {})
        if schema:
            parts.append("## Available Filters (from loaded dataset)\n")
            parts.append("Use ONLY these exact column names and values when calling filter_data.\n\n")
            for col, values in schema.items():
                if len(values) <= 20:
                    parts.append(f"- **{col}**: {values}\n")
                else:
                    parts.append(f"- **{col}**: {values[:20]} ... ({len(values)} total)\n")
        else:
            parts.append("## Available Filters\nNo filter catalog available yet. Use load_dataset first.\n")
        parts.append("\n## Current Data State\n")
        parts.append(json.dumps({
            "filters_applied": state.get("filters_applied", {}),
            "dataset_path": state.get("dataset_path", ""),
            "analysis_objective": state.get("analysis_objective", ""),
        }, indent=2, default=str))
        return "\n\n" + "\n".join(parts)

    # ── Formatting agent ───────────────────────────────────────────────
    if agent_name == "formatting_agent":
        parts: list[str] = []
        synthesis_path = state.get("synthesis_path", "")
        if synthesis_path and Path(synthesis_path).exists():
            parts.append("\n\n## Synthesis Summary\n" + Path(synthesis_path).read_text(encoding="utf-8")[:3000])
        narrative_path = state.get("narrative_path", "")
        if narrative_path and Path(narrative_path).exists():
            parts.append("\n\n## Narrative (for blueprint alignment)\n" + Path(narrative_path).read_text(encoding="utf-8")[:2000])
        if not parts:
            parts.append("\n\n## Formatting Context\nCreate the deck blueprint based on the synthesis in the conversation.")
        return "".join(parts)

    # ── Critique ───────────────────────────────────────────────────────
    if agent_name == "critique":
        synthesis_path = state.get("synthesis_path", "")
        if synthesis_path and Path(synthesis_path).exists():
            return "\n\n## Synthesis (for QA grading)\n" + Path(synthesis_path).read_text(encoding="utf-8")
        return "\n\n## Critique Context\nNo synthesis file available yet. Validate findings from message history."

    return ""


# ------------------------------------------------------------------
# Data analyst state extraction
# ------------------------------------------------------------------


def _extract_data_analyst_state(state: AnalyticsState, updates: dict[str, Any]) -> None:
    """Extract filters_applied, bucket_manifest_path etc. from tool results."""
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

        if "filters_applied" in data:
            filters = data["filters_applied"]
            if filters and isinstance(filters, dict):
                updates["filters_applied"] = filters
                logger.info("[DATA][filter_data] filters_applied=%s", filters)

        if "filtered_parquet_path" in data:
            updates["filtered_parquet_path"] = data["filtered_parquet_path"]
            logger.info("[DATA][filter_data] filtered_parquet_path=%s", data["filtered_parquet_path"])

        # bucket_data returns bucket_manifest_path + buckets summary
        if "bucket_manifest_path" in data:
            updates["bucket_manifest_path"] = data["bucket_manifest_path"]
            logger.info("[DATA][bucket_data] bucket_manifest_path=%s", data["bucket_manifest_path"])

        if "buckets" in data and isinstance(data["buckets"], dict):
            # Extract theme names for supervisor context (from bucket_id -> metadata dict)
            bucket_names = [
                info.get("bucket_name", bid)
                for bid, info in data["buckets"].items()
                if isinstance(info, dict)
            ]
            updates["themes_for_analysis"] = bucket_names
            logger.info("[DATA][bucket_data] themes_for_analysis=%d buckets", len(bucket_names))

    if "filters_applied" not in updates and not state.get("filters_applied"):
        updates["filters_applied"] = {"status": "extraction_attempted"}
        logger.info("[DATA][filter_data] no filter results found, marking extraction_attempted")


# ------------------------------------------------------------------
# Artifact path extraction (for report_analyst recovery)
# ------------------------------------------------------------------


def _extract_formatting_state(state: AnalyticsState, updates: dict[str, Any]) -> None:
    """Extract artifact paths from tool-result messages (report_analyst recovery path)."""
    messages = updates.get("messages", [])
    for msg in messages:
        if not hasattr(msg, "content"):
            continue
        content = _text(msg.content)
        data = _parse_json(content)
        if not data:
            continue
        # New model: all artifacts go to artifacts_dir
        for key in ("pptx_path", "csv_path", "markdown_path", "docx_path"):
            if key in data:
                p = Path(data[key])
                artifacts_dir = str(p.parent)
                if not updates.get("artifacts_dir"):
                    updates["artifacts_dir"] = artifacts_dir
                    logger.info("Formatting extraction: artifacts_dir=%s", artifacts_dir)


# ------------------------------------------------------------------
# Supervisor applier
# ------------------------------------------------------------------


def _apply_supervisor(
    structured: SupervisorOutput,
    state: AnalyticsState,
    base: dict[str, Any],
) -> None:
    """Apply structured supervisor output to base updates."""
    decision = structured.decision
    base["supervisor_decision"] = decision
    base["reasoning"] = [{"step_name": "Supervisor", "step_text": structured.reasoning}]

    if decision == "answer":
        if structured.response:
            base["messages"] = [AIMessage(content=structured.response)]
        base["next_agent"] = "__end__"
        return

    if decision == "plan":
        if structured.proposed_filters:
            base["proposed_filters"] = structured.proposed_filters
        # Route to data_analyst if no filtered data yet
        if not state.get("filtered_parquet_path"):
            base["next_agent"] = "data_analyst"
            base["analysis_objective"] = (
                state.get("analysis_objective", "")
                or _text(state["messages"][-1].content) if state.get("messages") else ""
            )
        else:
            base["next_agent"] = "planner"
        return

    if decision == "execute":
        tasks = state.get("plan_tasks", [])
        if tasks:
            _, next_agent = _find_next_plan_agent(tasks)
            base["next_agent"] = next_agent
        else:
            base["next_agent"] = "planner"
        return

    base["next_agent"] = "__end__"


# ------------------------------------------------------------------
# Guard helpers
# ------------------------------------------------------------------


def _has_bucketed_output(state: AnalyticsState) -> bool:
    manifest_path = state.get("bucket_manifest_path", "")
    themes = state.get("themes_for_analysis", [])
    has_manifest = bool(manifest_path) and Path(manifest_path).exists()
    has_themes = isinstance(themes, list) and bool(themes)
    return has_manifest or has_themes


def _enforce_analysis_start_guard(state: AnalyticsState, updates: dict[str, Any]) -> None:
    """Prevent analysis start before bucketed data exists."""
    next_agent = str(updates.get("next_agent", "") or "")
    if next_agent not in ANALYSIS_START_NODES:
        return
    if not _has_bucketed_output(state):
        logger.warning("Supervisor guard: blocked %s - no bucket data yet.", next_agent)
        updates["next_agent"] = "data_analyst"
        updates["supervisor_decision"] = "plan"
        updates["analysis_scope_reply"] = ""

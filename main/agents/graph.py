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
import json
import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import AIMessage, HumanMessage

from agents.nodes import (
    make_agent_node,
    user_checkpoint_node,
    AGENT_STATE_FIELDS,
)
from agents.state import AnalyticsState
from config import DATA_DIR
from core.agent_factory import AgentFactory
from core.skill_loader import SkillLoader
from tools import TOOL_REGISTRY

import chainlit as cl
from ui.components import sync_task_list

logger = logging.getLogger("agenticanalytics.graph")


MAX_REPORT_RETRIES = 3


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}

    if "```" in text:
        for part in text.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                parsed = json.loads(part)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, ValueError):
                continue

    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            continue
    return {}


def _tools_used_in_call(base_state: dict[str, Any], result: dict[str, Any]) -> list[str]:
    base_len = len(base_state.get("execution_trace", []))
    trace = result.get("execution_trace", [])
    if not isinstance(trace, list) or not trace:
        return []
    delta = trace[base_len:] if len(trace) > base_len else trace[-1:]
    tools: list[str] = []
    for entry in delta:
        if isinstance(entry, dict):
            tools.extend([t for t in entry.get("tools_used", []) if isinstance(t, str)])
    return tools


def _path_exists(raw_path: str) -> bool:
    if not raw_path:
        return False
    p = Path(raw_path)
    if p.exists():
        return True
    if not p.is_absolute():
        alt = Path(DATA_DIR) / p.name
        if alt.exists():
            return True
    return False


def _validate_narrative(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    payload = result.get("narrative_output", {})
    full = payload.get("full_response", "") if isinstance(payload, dict) else ""
    data = _extract_json(full)
    sections = data.get("sections", []) if isinstance(data, dict) else []
    if not data:
        errors.append("narrative_output.full_response is missing valid JSON.")
    if not isinstance(sections, list) or len(sections) < 4:
        errors.append("Narrative JSON must include at least 4 sections.")
    return errors


def _validate_dataviz(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    payload = result.get("dataviz_output", {})
    full = payload.get("full_response", "") if isinstance(payload, dict) else ""
    data = _extract_json(full)
    charts = data.get("charts", []) if isinstance(data, dict) else []
    if not isinstance(charts, list) or len(charts) < 3:
        errors.append("DataViz output must include 3 charts.")
        return errors

    required_types = {"friction_distribution", "impact_ease_scatter", "driver_breakdown"}
    found_types = {str(c.get("type", "")) for c in charts if isinstance(c, dict)}
    missing_types = sorted(required_types - found_types)
    if missing_types:
        errors.append(f"DataViz output missing chart types: {missing_types}")

    for chart in charts:
        if not isinstance(chart, dict):
            continue
        path = str(chart.get("file_path", "")).strip()
        if path and not _path_exists(path):
            errors.append(f"Chart file not found on disk: {path}")

    return errors


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_dataviz_fallback(state: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Generate required charts deterministically when dataviz agent fails retries."""
    synthesis = state.get("synthesis_result", {})
    themes_raw = synthesis.get("themes", []) if isinstance(synthesis, dict) else []

    themes: list[str] = []
    call_counts: list[int] = []
    ease_scores: list[float] = []
    impact_scores: list[float] = []
    primary_counts: list[int] = []
    secondary_counts: list[int] = []

    for item in themes_raw[:8] if isinstance(themes_raw, list) else []:
        if not isinstance(item, dict):
            continue
        theme_name = str(item.get("theme", "")).strip() or "Unknown"
        total_calls = max(0, _safe_int(item.get("call_count", 0), 0))
        ease = max(0.0, _safe_float(item.get("ease_score", 0.0), 0.0))
        impact = max(0.0, _safe_float(item.get("impact_score", 0.0), 0.0))

        primary = 0
        secondary = 0
        drivers = item.get("all_drivers", [])
        if isinstance(drivers, list):
            for driver in drivers:
                if not isinstance(driver, dict):
                    continue
                driver_calls = max(0, _safe_int(driver.get("call_count", 0), 0))
                if str(driver.get("type", "")).strip().lower() == "primary":
                    primary += driver_calls
                else:
                    secondary += driver_calls
        if primary == 0 and secondary == 0:
            primary = total_calls

        themes.append(theme_name)
        call_counts.append(total_calls)
        ease_scores.append(min(ease, 10.0))
        impact_scores.append(min(impact, 10.0))
        primary_counts.append(primary)
        secondary_counts.append(secondary)

    if not themes:
        themes = ["No matching data"]
        call_counts = [0]
        ease_scores = [0.0]
        impact_scores = [0.0]
        primary_counts = [0]
        secondary_counts = [0]

    chart_specs = [
        {
            "type": "friction_distribution",
            "title": "Customer Call Volume by Theme",
            "description": "Horizontal bar chart showing themes sorted by call volume",
            "output_filename": "friction_distribution.png",
            "code": (
                "import numpy as np\n"
                f"labels = {json.dumps(themes)}\n"
                f"values = {json.dumps(call_counts)}\n"
                "if not labels:\n"
                "    labels = ['No matching data']\n"
                "    values = [0]\n"
                "order = np.argsort(values)\n"
                "labels = [labels[i] for i in order]\n"
                "values = [values[i] for i in order]\n"
                "fig, ax = plt.subplots(figsize=(10, max(4, 0.45 * len(labels) + 1.5)))\n"
                "bars = ax.barh(labels, values, color='#4361ee')\n"
                "max_value = max(values) if values else 1\n"
                "for bar, val in zip(bars, values):\n"
                "    ax.text(val + max(0.2, max_value * 0.02), bar.get_y() + bar.get_height() / 2, str(int(val)), va='center', fontsize=9)\n"
                "ax.set_title('Customer Call Volume by Theme')\n"
                "ax.set_xlabel('Number of Calls')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            ),
        },
        {
            "type": "impact_ease_scatter",
            "title": "Impact vs Ease Prioritization Matrix",
            "description": "Bubble scatter plot with quadrant guides",
            "output_filename": "impact_ease_scatter.png",
            "code": (
                f"labels = {json.dumps(themes)}\n"
                f"ease = {json.dumps(ease_scores)}\n"
                f"impact = {json.dumps(impact_scores)}\n"
                f"calls = {json.dumps(call_counts)}\n"
                "sizes = [max(80, c * 16 + 80) for c in calls]\n"
                "fig, ax = plt.subplots(figsize=(9, 6))\n"
                "ax.scatter(ease, impact, s=sizes, alpha=0.7, c='#4361ee', edgecolors='#1a1a2e')\n"
                "for x, y, label in zip(ease, impact, labels):\n"
                "    ax.text(x + 0.1, y + 0.1, label, fontsize=8)\n"
                "ax.axhline(5.5, linestyle='--', linewidth=1, color='#bbbbbb')\n"
                "ax.axvline(5.5, linestyle='--', linewidth=1, color='#bbbbbb')\n"
                "ax.set_xlim(0, 10.5)\n"
                "ax.set_ylim(0, 10.5)\n"
                "ax.set_title('Impact vs Ease Prioritization Matrix')\n"
                "ax.set_xlabel('Ease of Implementation (1-10)')\n"
                "ax.set_ylabel('Customer Impact (1-10)')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            ),
        },
        {
            "type": "driver_breakdown",
            "title": "Driver Breakdown by Theme",
            "description": "Stacked horizontal bar chart of primary vs secondary drivers",
            "output_filename": "driver_breakdown.png",
            "code": (
                "import numpy as np\n"
                f"labels = {json.dumps(themes)}\n"
                f"primary = {json.dumps(primary_counts)}\n"
                f"secondary = {json.dumps(secondary_counts)}\n"
                "totals = [p + s for p, s in zip(primary, secondary)]\n"
                "order = np.argsort(totals)\n"
                "labels = [labels[i] for i in order]\n"
                "primary = [primary[i] for i in order]\n"
                "secondary = [secondary[i] for i in order]\n"
                "fig, ax = plt.subplots(figsize=(10, max(4, 0.5 * len(labels) + 1.5)))\n"
                "ax.barh(labels, primary, color='#4361ee', label='Primary Driver')\n"
                "ax.barh(labels, secondary, left=primary, color='#4cc9f0', label='Secondary Drivers')\n"
                "ax.set_title('Driver Breakdown by Theme')\n"
                "ax.set_xlabel('Number of Calls')\n"
                "ax.legend(loc='best')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            ),
        },
    ]

    chart_tool = TOOL_REGISTRY["execute_chart_code"]
    charts: list[dict[str, Any]] = []
    for spec in chart_specs:
        raw_result = chart_tool.invoke({
            "code": spec["code"],
            "output_filename": spec["output_filename"],
        })
        parsed = _extract_json(str(raw_result))
        chart_path = str(parsed.get("chart_path", "")).strip()
        if not chart_path:
            chart_path = str(Path(DATA_DIR) / spec["output_filename"])

        if not _path_exists(chart_path):
            logger.warning(
                "DataViz fallback chart generation missed file %s; retrying with placeholder.",
                chart_path,
            )
            placeholder = (
                "fig, ax = plt.subplots(figsize=(8, 4))\n"
                "ax.text(0.5, 0.5, 'No chart data available', ha='center', va='center', fontsize=14)\n"
                "ax.axis('off')\n"
                "fig.tight_layout()\n"
                "fig.savefig(output_path, dpi=180, bbox_inches='tight')\n"
            )
            raw_result = chart_tool.invoke({
                "code": placeholder,
                "output_filename": spec["output_filename"],
            })
            parsed = _extract_json(str(raw_result))
            chart_path = str(parsed.get("chart_path", "")).strip() or chart_path

        charts.append({
            "type": spec["type"],
            "title": spec["title"],
            "file_path": chart_path,
            "html_path": str(Path(chart_path).with_suffix(".html")),
            "description": spec["description"],
        })

    payload = {"charts": charts}
    payload_json = json.dumps(payload, indent=2)
    logger.warning("DataViz fallback generated charts due to retries failure: %s", reason)
    return {
        "messages": [AIMessage(content=payload_json)],
        "reasoning": [{
            "step_name": "DataViz Fallback",
            "step_text": "DataViz agent failed validation after retries; generated required charts via deterministic fallback.",
            "agent": "dataviz_agent",
        }],
        "dataviz_output": {
            "output": payload_json[:200],
            "full_response": payload_json,
            "agent": "dataviz_agent",
        },
    }


def _validate_formatting(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rpt = str(result.get("report_file_path", "")).strip()
    dat = str(result.get("data_file_path", "")).strip()
    md = str(result.get("markdown_file_path", "")).strip()

    if not rpt:
        errors.append("Missing report_file_path.")
    elif not _path_exists(rpt):
        errors.append(f"report_file_path does not exist: {rpt}")

    if not dat:
        errors.append("Missing data_file_path.")
    elif not _path_exists(dat):
        errors.append(f"data_file_path does not exist: {dat}")

    if not md:
        errors.append("Missing markdown_file_path.")
    elif not _path_exists(md):
        errors.append(f"markdown_file_path does not exist: {md}")

    return errors


def _build_retry_instruction(
    *,
    agent_id: str,
    attempt: int,
    max_attempts: int,
    required_tools: list[str],
    previous_errors: list[str],
) -> str:
    lines = [
        f"Execution contract for {agent_id} (attempt {attempt}/{max_attempts}).",
        f"Required tool calls in this attempt: {', '.join(required_tools)}.",
        "Do not return an empty response.",
    ]

    if agent_id == "dataviz_agent":
        lines.extend([
            "Call execute_chart_code three times: friction_distribution, impact_ease_scatter, driver_breakdown.",
            "After tool calls, return a JSON object with charts[] containing all three chart types and file paths.",
        ])
    elif agent_id == "formatting_agent":
        lines.extend([
            "Call tools in this exact order: generate_markdown_report -> export_to_pptx -> export_filtered_csv.",
            "Return only after all three paths exist in state: markdown_file_path, report_file_path, data_file_path.",
        ])
    elif agent_id == "narrative_agent":
        lines.extend([
            "Call get_findings_summary before final output.",
            "Return valid JSON with report_title, report_subtitle, and at least 4 sections.",
        ])

    if previous_errors:
        lines.append(f"Previous attempt failed validation: {json.dumps(previous_errors)}")
        lines.append("Fix every validation error in this attempt.")

    return "\n".join(lines)


async def _run_agent_with_retries(
    *,
    agent_id: str,
    node_fn: Any,
    base_state: dict[str, Any],
    required_tools: list[str],
    validator: Any,
    max_attempts: int = MAX_REPORT_RETRIES,
) -> dict[str, Any]:
    previous_errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        attempt_state = dict(base_state)
        attempt_state["report_retry_context"] = {
            "agent": agent_id,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "required_tools": required_tools,
            "previous_errors": previous_errors,
        }
        base_messages = list(base_state.get("messages", []))
        base_messages.append(HumanMessage(content=_build_retry_instruction(
            agent_id=agent_id,
            attempt=attempt,
            max_attempts=max_attempts,
            required_tools=required_tools,
            previous_errors=previous_errors,
        )))
        attempt_state["messages"] = base_messages
        result = await node_fn(attempt_state)

        errors: list[str] = []
        tools_used = _tools_used_in_call(base_state, result)
        missing_tools = [t for t in required_tools if t not in tools_used]
        if missing_tools:
            errors.append(f"Missing required tool calls: {missing_tools}")

        errors.extend(validator(result))
        if not errors:
            logger.info(
                "Report generation: %s succeeded on attempt %d/%d (tools=%s)",
                agent_id, attempt, max_attempts, tools_used,
            )
            return result

        previous_errors = errors
        logger.warning(
            "Report generation: %s attempt %d/%d failed validation: %s",
            agent_id, attempt, max_attempts, errors,
        )

    raise RuntimeError(
        f"{agent_id} failed after {max_attempts} attempts. Last validation errors: {previous_errors}"
    )


# -- Sub-agent catalog (drives TaskList UI) ------------------------------------
# Each entry maps agent_id -> {title, detail} for display in the Chainlit task list.

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
        tasks_before = _set_task_sub_agents(
            state.get("plan_tasks", []),
            agent_name="friction_analysis",
            sub_agents=sub_agents_before,
            task_status="in_progress",
        )
        await _emit_task_list_update(tasks_before)

        # Run selected lens agents concurrently
        node_fns = [_LENS_NODE_MAP[aid] for aid in lens_ids]
        results = await asyncio.gather(*(fn(state) for fn in node_fns))

        # Log what each agent produced
        for agent_id, result in zip(lens_ids, results):
            msg_count = len(result.get("messages", []))
            field = result.get(agent_id.replace("_agent", "_analysis") if "friction" not in agent_id
                               else "digital_analysis", {})
            has_output = bool(result.get("digital_analysis") or result.get("operations_analysis")
                              or result.get("communication_analysis") or result.get("policy_analysis"))
            logger.info(
                "  Friction [%s]: msgs=%d, has_state_field=%s",
                agent_id, msg_count, has_output,
            )

        # Merge parallel outputs into state
        merged = _merge_parallel_outputs(state, list(results))
        logger.info(
            "  Merged friction outputs: keys=%s, msgs=%d",
            [k for k in merged if merged[k] and k != "messages"],
            len(merged.get("messages", [])),
        )

        # --- Dump each friction agent's full output to DataStore ---
        data_store = cl.user_session.get("data_store")
        friction_output_files: dict[str, str] = {}
        if data_store:
            for agent_id, result in zip(lens_ids, results):
                field = AGENT_STATE_FIELDS.get(agent_id, "")
                if not field:
                    continue
                agent_output = result.get(field, {})
                full_response = agent_output.get("full_response", "") if isinstance(agent_output, dict) else ""
                if full_response:
                    key = f"{agent_id}_output"
                    data_store.store_text(key, full_response, {"agent": agent_id, "type": "friction_output"})
                    friction_output_files[agent_id] = key
                    logger.info("  DataStore: wrote %s (%d chars)", key, len(full_response))
        merged["friction_output_files"] = friction_output_files
        merged["expected_friction_lenses"] = lens_ids
        merged["missing_friction_lenses"] = [aid for aid in lens_ids if aid not in friction_output_files]

        # Build sub-agent entries with results (use static descriptions for clean UI)
        sub_agents = []
        for agent_id, result in zip(lens_ids, results):
            meta = FRICTION_SUB_AGENTS[agent_id]
            sub_agents.append({
                "id": agent_id,
                "title": meta["title"],
                "detail": meta["detail"],
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

        # Build intermediate state for synthesizer â€” keep full message context
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

        logger.info(
            "Friction analysis: synthesizer done | findings=%d synthesis=%s msgs=%d",
            len(synth_result.get("findings", [])),
            bool(synth_result.get("synthesis_result")),
            len(synth_result.get("messages", [])),
        )

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

        # Build final delta: all analysis fields from sub-agents, only synth messages for UI
        list_keys = {"reasoning", "execution_trace", "io_trace"}
        final: dict[str, Any] = {}
        for src in (merged, synth_result):
            for k, v in src.items():
                if k == "messages":
                    continue  # handled below
                if k in list_keys and isinstance(v, list):
                    final.setdefault(k, [])
                    final[k].extend(v)
                else:
                    final[k] = v
        # Only synthesizer message goes to UI (friction agent messages are internal)
        final["messages"] = synth_result.get("messages", [])
        final["plan_tasks"] = tasks

        # Advance plan_steps_completed for this composite node
        completed = state.get("plan_steps_completed", 0) + 1
        total = state.get("plan_steps_total", 0)
        final["plan_steps_completed"] = completed
        logger.info("Plan progress: %d/%d (agent=friction_analysis)", completed, total)

        return final

    # -- Composite node: report_generation ------------------------------------
    # Runs Narrative + DataViz in parallel via asyncio.gather, then Formatting.
    async def report_generation_node(state: AnalyticsState) -> dict[str, Any]:
        """Run narrative + dataviz in parallel, then formatting."""
        logger.info("Report generation: starting narrative + dataviz in parallel")
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

        # Run narrative and dataviz concurrently with strict tool enforcement.
        narrative_state = dict(state)
        narrative_state["messages"] = [HumanMessage(content=(
            "Generate the 4-section narrative report JSON now. "
            "You must call get_findings_summary before finalizing."
        ))]

        dataviz_state = dict(state)
        dataviz_state["messages"] = [HumanMessage(content=(
            "Generate charts now. You must call execute_chart_code for "
            "friction_distribution.png, impact_ease_scatter.png, and driver_breakdown.png, "
            "then return the final charts JSON."
        ))]

        results = await asyncio.gather(
            _run_agent_with_retries(
                agent_id="narrative_agent",
                node_fn=narrative_node,
                base_state=narrative_state,
                required_tools=["get_findings_summary"],
                validator=_validate_narrative,
            ),
            _run_agent_with_retries(
                agent_id="dataviz_agent",
                node_fn=dataviz_node,
                base_state=dataviz_state,
                required_tools=["execute_chart_code"],
                validator=_validate_dataviz,
            ),
            return_exceptions=True,
        )

        narrative_result, dataviz_result = results
        if isinstance(narrative_result, Exception):
            raise narrative_result
        if isinstance(dataviz_result, Exception):
            dataviz_error = dataviz_result
            dataviz_result = _build_dataviz_fallback(state, reason=str(dataviz_error))
            fallback_errors = _validate_dataviz(dataviz_result)
            if fallback_errors:
                raise RuntimeError(
                    "dataviz_agent failed and fallback charts validation failed: "
                    f"{fallback_errors}"
                ) from dataviz_error
        results = [narrative_result, dataviz_result]

        # Merge parallel outputs
        merged = _merge_parallel_outputs(state, list(results))

        # Build sub-agent entries with parallel results
        sub_agents = []
        for agent_id, result in zip(parallel_ids, results):
            meta = REPORTING_SUB_AGENTS[agent_id]
            sub_agents.append({
                "id": agent_id,
                "title": meta["title"],
                "detail": meta["detail"],
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

        # Build intermediate state for formatting â€” keep full message context
        fmt_state = dict(state)
        for k, v in merged.items():
            if k == "messages":
                continue  # handle separately
            fmt_state[k] = v
        # Formatting agent needs original conversation + parallel agent context
        fmt_state["messages"] = [HumanMessage(content=("Assemble final report artifacts from analysis context. " "Use tools in order: generate_markdown_report, export_to_pptx, export_filtered_csv."))]

        # Run formatting agent on merged outputs (must call all export tools).
        logger.info("Report generation: running formatting agent")
        fmt_result = await _run_agent_with_retries(
            agent_id="formatting_agent",
            node_fn=formatting_node,
            base_state=fmt_state,
            required_tools=["generate_markdown_report", "export_to_pptx", "export_filtered_csv"],
            validator=_validate_formatting,
        )

        # Log what the formatting agent produced for debugging downloads
        logger.info(
            "Report generation: fmt_result keys=%s | report_file_path=%r | data_file_path=%r | markdown_file_path=%r | msgs=%d",
            [k for k in fmt_result if fmt_result[k] and k != "messages"],
            fmt_result.get("report_file_path", ""),
            fmt_result.get("data_file_path", ""),
            fmt_result.get("markdown_file_path", ""),
            len(fmt_result.get("messages", [])),
        )

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

        # Build final delta: all fields from sub-agents, only formatter messages for UI
        list_keys = {"reasoning", "execution_trace", "io_trace"}
        final: dict[str, Any] = {}
        for src in (merged, fmt_result):
            for k, v in src.items():
                if k == "messages":
                    continue  # handled below
                if k in list_keys and isinstance(v, list):
                    final.setdefault(k, [])
                    final[k].extend(v)
                else:
                    final[k] = v

        # Build a clean user-facing summary message (tool call/result messages
        # are filtered by _message_text in app.py, so add an explicit summary)
        report_path = final.get("report_file_path", "")
        data_path = final.get("data_file_path", "")
        summary_parts = ["Report generation complete."]
        if report_path:
            summary_parts.append(f"PPTX report saved.")
        if data_path:
            summary_parts.append(f"Filtered CSV exported.")
        summary_msg = AIMessage(content=" ".join(summary_parts))
        final["messages"] = [summary_msg]

        final["plan_tasks"] = tasks

        # Advance plan_steps_completed for this composite node
        completed = state.get("plan_steps_completed", 0) + 1
        total = state.get("plan_steps_total", 0)
        final["plan_steps_completed"] = completed
        logger.info("Plan progress: %d/%d (agent=report_generation)", completed, total)

        # Check pipeline completion
        if total > 0 and completed >= total:
            final["analysis_complete"] = True
            final["phase"] = "qa"
            logger.info("Pipeline complete -- entering Q&A mode.")

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


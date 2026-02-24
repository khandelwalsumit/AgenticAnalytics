"""Production-like mock graph for orchestration validation.

This graph emulates real-world multi-agent behavior while staying fully local.
Key goals:
- strict node input/output delta contract
- optional checkpoints (not every step blocks for user input)
- async fan-out via asyncio.gather (no Send API dependency)
- resilient invoke wrapper for timeout/auth/token failures
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


class AnalyticsState(TypedDict, total=False):
    messages: list[Any]

    # Plan and progress
    plan_tasks: list[dict[str, Any]]
    plan_steps_total: int
    plan_steps_completed: int

    # Node telemetry for UI
    reasoning: list[dict[str, Any]]
    node_io: dict[str, Any]
    io_trace: list[dict[str, Any]]
    last_completed_node: str

    # Checkpoint control
    requires_user_input: bool
    checkpoint_message: str
    checkpoint_prompt: str
    checkpoint_token: str
    pending_input_for: str

    # Lifecycle
    analysis_complete: bool
    phase: str
    next_agent: str
    critique_enabled: bool
    selected_agents: list[str]
    selected_friction_agents: list[str]
    auto_approve_checkpoints: bool

    # Artifacts
    report_file_path: str
    data_file_path: str

    # Analytical outputs (emulated)
    digital_analysis: dict[str, Any]
    operations_analysis: dict[str, Any]
    communication_analysis: dict[str, Any]
    policy_analysis: dict[str, Any]
    synthesis_result: dict[str, Any]
    narrative_output: dict[str, Any]
    dataviz_output: dict[str, Any]
    formatting_output: dict[str, Any]

    # Failure simulation and recovery
    fault_injection: dict[str, str]
    error_count: int
    recoverable_error: str


class RecoverableInvokeError(Exception):
    """Raised when mock model invocation fails after resilience logic."""

    def __init__(self, kind: str, detail: str):
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}")


FRICTION_LENS_CATALOG: dict[str, dict[str, str]] = {
    "digital_friction_agent": {
        "title": "Digital Friction Agent",
        "detail": "6 findability failures, 3 UX gaps.",
        "field": "digital_analysis",
    },
    "operations_agent": {
        "title": "Operations Agent",
        "detail": "2 SLA breaches, 4 manual dependencies.",
        "field": "operations_analysis",
    },
    "communication_agent": {
        "title": "Communication Agent",
        "detail": "8 missing notifications.",
        "field": "communication_analysis",
    },
    "policy_agent": {
        "title": "Policy Agent",
        "detail": "3 regulatory constraints.",
        "field": "policy_analysis",
    },
}


def _with_trace(
    state: AnalyticsState,
    *,
    node_name: str,
    node_input: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(output)
    merged.update(_trace_io(state, node_name=node_name, node_input=node_input, node_output=output))
    return merged


def _set_task_sub_agents(
    tasks: list[dict[str, Any]],
    *,
    task_id: str,
    sub_agents: list[dict[str, Any]],
    task_status: str | None = None,
) -> None:
    for task in tasks:
        if task.get("id") != task_id:
            continue
        if task_status is not None:
            task["status"] = task_status
        task["sub_agents"] = sub_agents
        return


def _last_user_text(state: AnalyticsState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return ""
    last = messages[-1]
    if hasattr(last, "content"):
        return str(last.content or "")
    return str(last)


def _trace_io(
    state: AnalyticsState,
    node_name: str,
    node_input: dict[str, Any],
    node_output: dict[str, Any],
) -> dict[str, Any]:
    entry = {
        "node": node_name,
        "input": node_input,
        "output": node_output,
    }
    return {
        "node_io": entry,
        "io_trace": state.get("io_trace", []) + [entry],
        "last_completed_node": node_name,
    }


def _clear_checkpoint_fields() -> dict[str, Any]:
    return {
        "requires_user_input": False,
        "checkpoint_message": "",
        "checkpoint_prompt": "",
        "checkpoint_token": "",
        "pending_input_for": "",
    }


def _make_checkpoint(
    *,
    target_node: str,
    message: str,
    prompt: str,
) -> dict[str, Any]:
    return {
        "requires_user_input": True,
        "checkpoint_message": message,
        "checkpoint_prompt": prompt,
        "checkpoint_token": str(uuid.uuid4())[:8],
        "pending_input_for": target_node,
    }


def _new_plan_tasks() -> list[dict[str, Any]]:
    return [
        {"id": "1", "title": "Data Discovery", "status": "todo"},
        {"id": "2", "title": "Data Preparation", "status": "todo"},
        {"id": "3", "title": "Friction Analysis", "status": "todo"},
        {"id": "4", "title": "Synthesis", "status": "todo"},
        {"id": "5", "title": "Report Generation", "status": "todo"},
    ]


def _task_updates(tasks: list[dict[str, Any]], updates: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for task in tasks:
        copy = dict(task)
        if copy.get("id") in updates:
            copy["status"] = updates[copy["id"]]
        out.append(copy)
    return out


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in msg or "deadline" in msg:
        return "timeout"
    if "unauth" in msg or "401" in msg or "api key" in msg or "token expired" in msg:
        return "auth"
    if "token" in msg and ("limit" in msg or "too many" in msg or "context" in msg):
        return "token"
    return "unknown"


def _trim_messages(state: AnalyticsState) -> bool:
    messages = state.get("messages", [])
    if len(messages) <= 8:
        return False
    state["messages"] = messages[-8:]
    return True


def _consume_fault_for_op(state: AnalyticsState, op_name: str) -> str:
    fault = state.get("fault_injection", {})
    next_error = fault.get("next_error", "")
    target = fault.get("target", "any")
    if not next_error:
        return ""
    if target not in ("any", op_name):
        return ""
    state["fault_injection"] = {"next_error": "", "target": "any"}
    return next_error


async def _mock_model_call(
    op_name: str,
    response: str,
    *,
    injected_error: str = "",
    delay_s: float = 0.8,
) -> str:
    await asyncio.sleep(delay_s)
    if injected_error == "timeout":
        raise asyncio.TimeoutError(f"{op_name} deadline exceeded")
    if injected_error == "auth":
        raise RuntimeError(f"{op_name} unauthenticated: token expired")
    if injected_error == "token":
        raise RuntimeError(f"{op_name} token limit exceeded for model context")
    return response


async def _invoke_with_resilience(
    state: AnalyticsState,
    op_name: str,
    response: str,
    *,
    allow_context_trim: bool = True,
) -> str:
    max_timeout_retries = 2
    timeout_tries = 0
    auth_tries = 0
    token_tries = 0

    while True:
        injected = _consume_fault_for_op(state, op_name)
        try:
            return await asyncio.wait_for(
                _mock_model_call(op_name, response, injected_error=injected),
                timeout=5.0,
            )
        except Exception as exc:  # noqa: PERF203
            kind = _classify_error(exc)

            if kind == "timeout" and timeout_tries < max_timeout_retries:
                timeout_tries += 1
                await asyncio.sleep(0.4 * timeout_tries)
                continue

            if kind == "auth" and auth_tries < 1:
                # Emulate auth/token refresh then retry once.
                auth_tries += 1
                await asyncio.sleep(0.5)
                continue

            if kind == "token" and allow_context_trim and token_tries < 1:
                token_tries += 1
                if _trim_messages(state):
                    await asyncio.sleep(0.2)
                    continue

            raise RecoverableInvokeError(
                kind=kind,
                detail=str(exc),
            ) from exc


def _recoverable_checkpoint(state: AnalyticsState, node_name: str, err: RecoverableInvokeError) -> dict[str, Any]:
    message = (
        f"**Temporary model issue in `{node_name}`**\n"
        f"- type: `{err.kind}`\n"
        f"- detail: `{err.detail}`\n\n"
        "No progress was lost. You can retry this step."
    )
    output = {
        "reasoning": [{
            "step_name": node_name.replace("_", " ").title(),
            "step_text": f"Encountered recoverable {err.kind} error. Waiting for user retry.",
        }],
        "recoverable_error": err.kind,
        "error_count": state.get("error_count", 0) + 1,
        **_make_checkpoint(
            target_node=node_name,
            message=message,
            prompt="Reply `retry` to retry this step, or `skip` to move ahead with partial output.",
        ),
    }
    return _with_trace(
        state,
        node_name=node_name,
        node_input={
            "plan_steps_completed": state.get("plan_steps_completed", 0),
            "phase": state.get("phase", "analysis"),
        },
        output=output,
    )


async def supervisor(state: AnalyticsState) -> dict[str, Any]:
    await asyncio.sleep(0.2)
    idx = state.get("plan_steps_completed", 0)
    tasks = state.get("plan_tasks", [])
    user_text = _last_user_text(state).strip().lower()

    if state.get("analysis_complete"):
        return _with_trace(
            state,
            node_name="supervisor",
            node_input={"analysis_complete": True, "phase": state.get("phase", "analysis")},
            output={
            "reasoning": [{
                "step_name": "Scope Detector",
                "step_text": "Analysis already complete. Routing through scope classification for Q&A.",
            }],
            "next_agent": "scope_detector",
            **_clear_checkpoint_fields(),
            },
        )

    # Resume from an outstanding checkpoint or recoverable error.
    pending = state.get("pending_input_for", "")
    if state.get("requires_user_input") and pending:
        if "skip" in user_text:
            skip_to = "reporting" if pending == "synthesizer" else "supervisor"
            return _with_trace(
                state,
                node_name="supervisor",
                node_input={"pending_input_for": pending, "user_reply": user_text},
                output={
                "reasoning": [{
                    "step_name": "Supervisor",
                    "step_text": f"User requested skip for `{pending}`. Continuing to `{skip_to}`.",
                    "verbose": True,
                }],
                "next_agent": skip_to,
                "recoverable_error": "",
                **_clear_checkpoint_fields(),
                },
            )

        return _with_trace(
            state,
            node_name="supervisor",
            node_input={"pending_input_for": pending, "user_reply": user_text},
            output={
            "reasoning": [{
                "step_name": "Supervisor",
                "step_text": f"Checkpoint response received. Resuming `{pending}`.",
                "verbose": True,
            }],
            "next_agent": pending,
            "recoverable_error": "",
            **_clear_checkpoint_fields(),
            },
        )

    if not tasks:
        tasks = _new_plan_tasks()
        tasks[0]["status"] = "in_progress"
        return _with_trace(
            state,
            node_name="supervisor",
            node_input={"plan_tasks_present": False},
            output={
            "reasoning": [{"step_name": "Supervisor", "step_text": "Generating analysis plan...", "verbose": True}],
            "plan_tasks": tasks,
            "plan_steps_total": 5,
            "next_agent": "data_discovery",
            **_clear_checkpoint_fields(),
            },
        )

    if idx == 1:
        next_agent = "data_prep"
    elif idx == 2:
        next_agent = "friction"
    elif idx == 4:
        selected_agents = state.get("selected_agents", [])
        critique_selected = "critique" in selected_agents or state.get("critique_enabled", False)
        next_agent = "critique" if critique_selected else "reporting"
    else:
        next_agent = "end"

    return _with_trace(
        state,
        node_name="supervisor",
        node_input={
            "plan_steps_completed": idx,
            "critique_enabled": state.get("critique_enabled", False),
            "selected_agents": state.get("selected_agents", []),
        },
        output={
        "reasoning": [{
            "step_name": "Supervisor",
            "step_text": f"Routing to `{next_agent}`.",
            "verbose": True,
        }],
        "next_agent": next_agent,
        **_clear_checkpoint_fields(),
        },
    )


def route_supervisor(state: AnalyticsState) -> str:
    next_agent = state.get("next_agent", "end")
    if next_agent == "end":
        return END
    return next_agent


def _route_after_node(default_next: str):
    def _route(state: AnalyticsState) -> str:
        if state.get("requires_user_input", False):
            return END
        return default_next
    return _route


async def data_discovery(state: AnalyticsState) -> dict[str, Any]:
    tasks = _task_updates(state.get("plan_tasks", []), {"1": "in_progress"})
    try:
        summary = await _invoke_with_resilience(
            state,
            op_name="data_discovery",
            response="Loaded CSV and discovered schema for 300,412 records across 13 columns.",
        )
    except RecoverableInvokeError as err:
        return _recoverable_checkpoint(state, "data_discovery", err)

    tasks = _task_updates(tasks, {"1": "done", "2": "in_progress"})
    output = {
        "reasoning": [{
            "step_name": "Data Analyst",
            "step_text": summary,
        }],
        "plan_tasks": tasks,
        "plan_steps_completed": 1,
        **_make_checkpoint(
            target_node="data_prep",
            message=(
                "**Data Discovery Complete**\n"
                "Found **300,412 records** across 13 columns.\n"
                "Key fields: `exact_problem_statement`, `digital_friction`, `call_reason (L1-L5)`."
            ),
            prompt="Do you confirm this scope and proceed to preparation?",
        ),
    }
    return _with_trace(
        state,
        node_name="data_discovery",
        node_input={"dataset_path": state.get("dataset_path", ""), "messages_count": len(state.get("messages", []))},
        output=output,
    )


async def data_prep(state: AnalyticsState) -> dict[str, Any]:
    try:
        prep = await _invoke_with_resilience(
            state,
            op_name="data_prep",
            response="Applied filters and created 5 production-aligned buckets by domain and intent.",
        )
    except RecoverableInvokeError as err:
        return _recoverable_checkpoint(state, "data_prep", err)

    tasks = _task_updates(state.get("plan_tasks", []), {"2": "done", "3": "in_progress"})
    checkpoint_needed = not state.get("auto_approve_checkpoints", False) and "review prep" in _last_user_text(state).lower()

    output: dict[str, Any] = {
        "reasoning": [{"step_name": "Data Analyst", "step_text": prep}],
        "plan_tasks": tasks,
        "plan_steps_completed": 2,
    }

    if checkpoint_needed:
        output.update(_make_checkpoint(
            target_node="friction",
            message=(
                "**Data Preparation Review**\n"
                "Buckets prepared: Payment & Transfer (38%), Authentication (22%), Fraud & Dispute (18%), "
                "Rewards (12%), Profile & Settings (10%)."
            ),
            prompt="Reply `continue` to run friction analysis.",
        ))
    else:
        output.update(_clear_checkpoint_fields())

    return _with_trace(
        state,
        node_name="data_prep",
        node_input={"checkpoint_policy": "optional", "auto_approve_checkpoints": state.get("auto_approve_checkpoints", False)},
        output=output,
    )


async def _run_lens(state: AnalyticsState, lens_key: str, title: str, detail: str) -> dict[str, Any]:
    try:
        response = await _invoke_with_resilience(
            state,
            op_name=lens_key,
            response=detail,
        )
        return {"id": lens_key, "title": title, "status": "done", "detail": response, "ok": True}
    except RecoverableInvokeError as err:
        return {"id": lens_key, "title": title, "status": "failed", "detail": f"{err.kind}: {err.detail}", "ok": False}


async def _run_reporting_branch(state: AnalyticsState, op_name: str, title: str, text: str) -> dict[str, Any]:
    try:
        resp = await _invoke_with_resilience(state, op_name=op_name, response=text)
        return {"id": op_name, "title": title, "status": "done", "detail": resp, "ok": True}
    except RecoverableInvokeError as err:
        return {"id": op_name, "title": title, "status": "failed", "detail": f"{err.kind}: {err.detail}", "ok": False}


async def friction(state: AnalyticsState) -> dict[str, Any]:
    tasks = _task_updates(state.get("plan_tasks", []), {"3": "in_progress"})
    selected = state.get("selected_friction_agents", [])
    if not selected:
        selected = [agent_id for agent_id in state.get("selected_agents", []) if agent_id in FRICTION_LENS_CATALOG]

    _set_task_sub_agents(
        tasks,
        task_id="3",
        sub_agents=[
            {
                "id": agent_id,
                "title": FRICTION_LENS_CATALOG[agent_id]["title"],
                "status": "in_progress",
            }
            for agent_id in selected
        ],
    )

    if selected:
        lens_results = await asyncio.gather(*[
            _run_lens(
                state,
                agent_id,
                FRICTION_LENS_CATALOG[agent_id]["title"],
                FRICTION_LENS_CATALOG[agent_id]["detail"],
            )
            for agent_id in selected
        ])
    else:
        lens_results = []

    _set_task_sub_agents(
        tasks,
        task_id="3",
        sub_agents=[
            {
                "id": row["id"],
                "title": row["title"],
                "status": "done" if row["ok"] else "blocked",
                "detail": row["detail"],
            }
            for row in lens_results
        ],
    )

    result_by_id = {row["id"]: row for row in lens_results}
    field_updates: dict[str, dict[str, Any]] = {}
    for agent_id, meta in FRICTION_LENS_CATALOG.items():
        if agent_id in result_by_id:
            field_updates[meta["field"]] = {
                "status": result_by_id[agent_id]["status"],
                "detail": result_by_id[agent_id]["detail"],
            }
        else:
            field_updates[meta["field"]] = {
                "status": "skipped",
                "detail": "Not selected for this session.",
            }

    output = {
        "reasoning": [
            {
                "step_name": "Business Analyst",
                "step_text": (
                    "No friction lens agents selected; skipping lens execution."
                    if not selected
                    else f"Ran {len(selected)} selected friction lenses concurrently via async gather."
                ),
                "verbose": True,
            },
            *[
                {"step_name": row["title"], "step_text": row["detail"]}
                for row in lens_results
            ],
        ],
        "plan_tasks": tasks,
        "plan_steps_completed": 3,
        **field_updates,
        **_clear_checkpoint_fields(),
    }
    return _with_trace(
        state,
        node_name="friction",
        node_input={
            "fan_out_mode": "asyncio.gather",
            "selected_lens_agents": selected,
        },
        output=output,
    )


async def synthesizer(state: AnalyticsState) -> dict[str, Any]:
    try:
        synthesis = await _invoke_with_resilience(
            state,
            op_name="synthesizer",
            response="Dominant driver is Findability. Authentication + Digital contributes 41% of total friction.",
        )
    except RecoverableInvokeError as err:
        return _recoverable_checkpoint(state, "synthesizer", err)

    tasks = _task_updates(state.get("plan_tasks", []), {"3": "done", "4": "in_progress"})
    auto_approve = state.get("auto_approve_checkpoints", False)

    output: dict[str, Any] = {
        "reasoning": [{"step_name": "Synthesizer Agent", "step_text": synthesis}],
        "plan_tasks": tasks,
        "plan_steps_completed": 4,
        "synthesis_result": {
            "dominant_driver": "Findability",
            "impact_x_ease": 8.5,
            "supporting_signal": "Authentication + Digital = 41%",
        },
    }
    if auto_approve:
        output.update(_clear_checkpoint_fields())
    else:
        output.update(_make_checkpoint(
            target_node="supervisor",
            message=(
                "**Synthesis Complete**\n"
                "Dominant driver: **Findability** (Impact x Ease: 8.5).\n"
                "`Authentication + Digital` contributes **41%** of total friction."
            ),
            prompt="Proceed to the next stage?",
        ))

    return _with_trace(
        state,
        node_name="synthesizer",
        node_input={"lens_outputs_available": True, "auto_approve_checkpoints": auto_approve},
        output=output,
    )


async def critique(state: AnalyticsState) -> dict[str, Any]:
    try:
        critique_text = await _invoke_with_resilience(
            state,
            op_name="critique",
            response="Validated findings for consistency, actionability, and bias. Quality score: 9.1/10.",
        )
    except RecoverableInvokeError as err:
        return _recoverable_checkpoint(state, "critique", err)

    output = {
        "reasoning": [{"step_name": "QA Agent", "step_text": critique_text}],
        **_clear_checkpoint_fields(),
    }
    return _with_trace(
        state,
        node_name="critique",
        node_input={"critique_enabled": state.get("critique_enabled", False)},
        output=output,
    )


async def reporting(state: AnalyticsState) -> dict[str, Any]:
    tasks = _task_updates(state.get("plan_tasks", []), {"4": "done", "5": "in_progress"})
    _set_task_sub_agents(
        tasks,
        task_id="5",
        sub_agents=[
            {"id": "narrative_agent", "title": "Narrative Agent", "status": "in_progress"},
            {"id": "dataviz_agent", "title": "DataViz Agent", "status": "in_progress"},
            {"id": "formatting_agent", "title": "Formatting Agent", "status": "todo"},
        ],
    )

    branch_results = await asyncio.gather(
        _run_reporting_branch(state, "narrative_agent", "Narrative Agent", "Executive summary and 4 thematic narratives drafted."),
        _run_reporting_branch(state, "dataviz_agent", "DataViz Agent", "Generated 4 charts: distribution, impact-ease, multi-lens, preventability."),
    )

    try:
        fmt = await _invoke_with_resilience(
            state,
            op_name="formatting_agent",
            response="Assembled markdown report and PPTX package.",
        )
        fmt_row = {"id": "formatting_agent", "title": "Formatting Agent", "status": "done", "detail": fmt, "ok": True}
    except RecoverableInvokeError as err:
        fmt_row = {"id": "formatting_agent", "title": "Formatting Agent", "status": "failed", "detail": f"{err.kind}: {err.detail}", "ok": False}

    _set_task_sub_agents(
        tasks,
        task_id="5",
        task_status="done" if fmt_row["ok"] else "blocked",
        sub_agents=[
            {
                "id": row["id"],
                "title": row["title"],
                "status": "done" if row.get("ok", False) else "blocked",
                "detail": row["detail"],
            }
            for row in [*branch_results, fmt_row]
        ],
    )

    completion_msg = (
        "**Analysis complete!**\n\n"
        "PPTX and filtered CSV are ready for download. Now in **Q&A Mode**."
    )

    output = {
        "reasoning": [
            {"step_name": "Report Analyst", "step_text": "Ran reporting squad with async branches then formatter.", "verbose": True},
            *[
                {"step_name": row["title"], "step_text": row["detail"]}
                for row in [*branch_results, fmt_row]
            ],
        ],
        "plan_tasks": tasks,
        "plan_steps_completed": 5,
        "analysis_complete": True,
        "phase": "qa",
        "report_file_path": "report.pptx",
        "data_file_path": "filtered_data.csv",
        "messages": [AIMessage(content=completion_msg)],
        "narrative_output": {"status": branch_results[0]["status"], "detail": branch_results[0]["detail"]},
        "dataviz_output": {"status": branch_results[1]["status"], "detail": branch_results[1]["detail"]},
        "formatting_output": {"status": fmt_row["status"], "detail": fmt_row["detail"]},
        **_clear_checkpoint_fields(),
    }
    return _with_trace(
        state,
        node_name="reporting",
        node_input={"reporting_mode": "async branches + sequential formatting"},
        output=output,
    )


async def scope_detector(state: AnalyticsState) -> dict[str, Any]:
    question = _last_user_text(state).lower()
    out_of_scope_signals = [
        "new dataset",
        "different csv",
        "credit card data",
        "international transfer",
        "completely new analysis",
    ]
    in_scope = not any(signal in question for signal in out_of_scope_signals)
    if in_scope:
        output = {
            "reasoning": [{
                "step_name": "Scope Detector",
                "step_text": "Query is in scope. Routing to QA agent.",
            }],
            "next_agent": "qa_agent",
            **_clear_checkpoint_fields(),
        }
    else:
        output = {
            "reasoning": [{
                "step_name": "Scope Detector",
                "step_text": "Query is out of scope. Suggesting a new chat.",
            }],
            "next_agent": "end",
            "messages": [AIMessage(content=(
                "This question is outside the current analysis scope.\n\n"
                "Please start a new chat for a fresh dataset/filter scope."
            ))],
            **_clear_checkpoint_fields(),
        }
    return _with_trace(
        state,
        node_name="scope_detector",
        node_input={"question": question[:120]},
        output=output,
    )


async def qa_agent(state: AnalyticsState) -> dict[str, Any]:
    try:
        answer = await _invoke_with_resilience(
            state,
            op_name="qa_agent",
            response=(
                "Based on current artifacts, the highest digital friction is the password reset flow, "
                "with a 23% drop-off at OTP verification."
            ),
            allow_context_trim=False,
        )
    except RecoverableInvokeError as err:
        return _recoverable_checkpoint(state, "qa_agent", err)

    output = {
        "reasoning": [{"step_name": "Supervisor", "step_text": "Answered from existing findings and synthesis artifacts."}],
        "messages": [AIMessage(content=answer)],
        **_clear_checkpoint_fields(),
    }
    return _with_trace(
        state,
        node_name="qa_agent",
        node_input={"analysis_complete": state.get("analysis_complete", False)},
        output=output,
    )


def build_graph(*args, **kwargs):
    graph = StateGraph(AnalyticsState)

    graph.add_node("supervisor", supervisor)
    graph.add_node("data_discovery", data_discovery)
    graph.add_node("data_prep", data_prep)
    graph.add_node("friction", friction)
    graph.add_node("synthesizer", synthesizer)
    graph.add_node("critique", critique)
    graph.add_node("reporting", reporting)
    graph.add_node("scope_detector", scope_detector)
    graph.add_node("qa_agent", qa_agent)

    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "supervisor": "supervisor",
            "data_discovery": "data_discovery",
            "data_prep": "data_prep",
            "friction": "friction",
            "critique": "critique",
            "reporting": "reporting",
            "scope_detector": "scope_detector",
            "qa_agent": "qa_agent",
            END: END,
        },
    )

    graph.add_conditional_edges("data_discovery", _route_after_node("supervisor"), {"supervisor": "supervisor", END: END})
    graph.add_conditional_edges("data_prep", _route_after_node("supervisor"), {"supervisor": "supervisor", END: END})
    graph.add_conditional_edges("friction", _route_after_node("synthesizer"), {"synthesizer": "synthesizer", END: END})
    graph.add_conditional_edges("synthesizer", _route_after_node("supervisor"), {"supervisor": "supervisor", END: END})
    graph.add_conditional_edges("critique", _route_after_node("reporting"), {"reporting": "reporting", END: END})
    graph.add_edge("reporting", END)

    graph.add_conditional_edges(
        "scope_detector",
        lambda state: END if state.get("next_agent") == "end" else "qa_agent",
        {"qa_agent": "qa_agent", END: END},
    )
    graph.add_conditional_edges("qa_agent", _route_after_node(END), {END: END})

    graph.add_edge(START, "supervisor")

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)



"""Mock Graph for Testing (No API calls, realistic delays)."""

import asyncio
from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage


class AnalyticsState(TypedDict, total=False):
    messages: list[Any]
    plan_tasks: list[dict]        # [{id, title, status, sub_agents?}]
    plan_steps_total: int
    plan_steps_completed: int
    reasoning: list[dict]
    requires_user_input: bool
    checkpoint_message: str
    checkpoint_prompt: str
    analysis_complete: bool
    report_file_path: str
    data_file_path: str
    phase: str
    next_agent: str
    critique_enabled: bool


async def supervisor(state: AnalyticsState):
    await asyncio.sleep(1)
    idx = state.get("plan_steps_completed", 0)

    if state.get("analysis_complete"):
        return {
            "reasoning": [{"step_name": "Scope Detector", "step_text": "Query classified as IN-SCOPE. Synthesizing answer from existing artifacts..."}],
            "next_agent": "qa_agent",
            "requires_user_input": False,
        }

    tasks = state.get("plan_tasks", [])
    if not tasks:
        tasks = [
            {"id": "1", "title": "Data Discovery",    "status": "todo"},
            {"id": "2", "title": "Data Preparation",  "status": "todo"},
            {"id": "3", "title": "Friction Analysis", "status": "todo"},
            {"id": "4", "title": "Synthesis",         "status": "todo"},
            {"id": "5", "title": "Report Generation", "status": "todo"},
        ]
        tasks[0]["status"] = "in_progress"
        return {
            "reasoning": [{"step_name": "Supervisor", "step_text": "Generating analysis plan...", "verbose": True}],
            "plan_tasks": tasks,
            "plan_steps_total": 5,
            "next_agent": "data_discovery",
            "requires_user_input": False,
        }

    if idx == 1:
        return {"reasoning": [{"step_name": "Supervisor", "step_text": "Delegating to Data Analyst for filtering.", "verbose": True}], "next_agent": "data_prep", "requires_user_input": False}
    elif idx == 2:
        return {"reasoning": [{"step_name": "Supervisor", "step_text": "Delegating to Business Analyst — spawning 4 friction lens agents.", "verbose": True}], "next_agent": "friction", "requires_user_input": False}
    elif idx == 4:
        next_is = "critique" if state.get("critique_enabled", False) else "reporting"
        return {"reasoning": [{"step_name": "Supervisor", "step_text": f"Delegating to {next_is}.", "verbose": True}], "next_agent": next_is, "requires_user_input": False}

    return {"next_agent": "end", "requires_user_input": False}


def route_supervisor(state: AnalyticsState):
    if state.get("next_agent") == "end":
        return END
    return state.get("next_agent", END)


async def data_discovery(state: AnalyticsState):
    await asyncio.sleep(2)
    return {
        "reasoning": [{"step_name": "Data Analyst", "step_text": "Loading dataset and extracting schema (`exact_problem_statement`, `digital_friction`, `call_reason_l1_l5`)."}],
        "requires_user_input": True,
        "checkpoint_message": "**Data Discovery Complete**\nFound **300,412 records** across 13 columns. Key fields: `exact_problem_statement`, `digital_friction`, `call_reason` (L1–L5).",
        "checkpoint_prompt": "Do you confirm this focus area?",
        "plan_steps_completed": 1,
    }


async def data_prep(state: AnalyticsState):
    await asyncio.sleep(2)
    tasks = [t.copy() for t in state.get("plan_tasks", [])]
    for t in tasks:
        if t["id"] == "1": t["status"] = "done"
        if t["id"] == "2": t["status"] = "in_progress"
    return {
        "reasoning": [{"step_name": "Data Analyst", "step_text": "Applying segment filters and bucketing issues geographically and temporally..."}],
        "requires_user_input": True,
        "checkpoint_message": "**Data Preparation Complete**\nSliced into **5 buckets**: `Payment & Transfer` (38%), `Authentication` (22%), `Fraud & Dispute` (18%), `Rewards` (12%), `Profile & Settings` (10%).",
        "checkpoint_prompt": "Please confirm the slicing to proceed.",
        "plan_tasks": tasks,
        "plan_steps_completed": 2,
    }


async def friction(state: AnalyticsState):
    tasks = [t.copy() for t in state.get("plan_tasks", [])]
    for t in tasks:
        if t["id"] == "2": t["status"] = "done"
        if t["id"] == "3":
            t["status"] = "in_progress"
            t["sub_agents"] = [
                {"id": "f1", "title": "Digital Friction Agent", "status": "in_progress"},
                {"id": "f2", "title": "Operations Agent",       "status": "in_progress"},
                {"id": "f3", "title": "Communication Agent",    "status": "in_progress"},
                {"id": "f4", "title": "Policy Agent",           "status": "in_progress"},
            ]

    await asyncio.sleep(3)

    # All sub-agents done — update with details
    for t in tasks:
        if t["id"] == "3":
            t["sub_agents"] = [
                {"id": "f1", "title": "Digital Friction Agent", "status": "done", "detail": "6 findability failures, 3 UX gaps"},
                {"id": "f2", "title": "Operations Agent",       "status": "done", "detail": "2 SLA breaches, 4 manual dependencies"},
                {"id": "f3", "title": "Communication Agent",    "status": "done", "detail": "8 missing notifications"},
                {"id": "f4", "title": "Policy Agent",           "status": "done", "detail": "3 regulatory constraints"},
            ]

    return {
        "reasoning": [
            {"step_name": "Business Analyst",      "step_text": "Fan-out to 4 friction lens agents (parallel execution).", "verbose": True},
            {"step_name": "Digital Friction Agent","step_text": "6 findability failures, 3 UX gaps identified."},
            {"step_name": "Operations Agent",      "step_text": "2 SLA breaches, 4 manual dependencies flagged."},
            {"step_name": "Communication Agent",   "step_text": "8 missing notification gaps found."},
            {"step_name": "Policy Agent",          "step_text": "3 regulatory constraints flagged."},
        ],
        "plan_tasks": tasks,
        "plan_steps_completed": 3,
    }


async def synthesizer(state: AnalyticsState):
    await asyncio.sleep(3)
    tasks = [t.copy() for t in state.get("plan_tasks", [])]
    for t in tasks:
        # Clear sub_agents from Friction Analysis and mark done
        if t["id"] == "3":
            t["status"] = "done"
            t.pop("sub_agents", None)
        if t["id"] == "4": t["status"] = "in_progress"
    return {
        "reasoning": [{"step_name": "Synthesizer Agent", "step_text": "Merging 4 agent outputs. Top driver: 'Findability' (Impact × Ease: 8.5). Auth + Digital = 41% of total friction."}],
        "requires_user_input": True,
        "checkpoint_message": "**Synthesis Complete**\nDominant driver: **Findability** (Impact × Ease: 8.5). `Authentication + Digital` → 41% of total friction.",
        "checkpoint_prompt": "Proceed to Report Generation?",
        "plan_tasks": tasks,
        "plan_steps_completed": 4,
    }


async def critique(state: AnalyticsState):
    await asyncio.sleep(2)
    return {
        "reasoning": [{"step_name": "QA Agent", "step_text": "Validating findings for accuracy, actionability, and bias... No critical flags. Quality score: 9.1/10."}],
    }


async def reporting(state: AnalyticsState):
    tasks = [t.copy() for t in state.get("plan_tasks", [])]
    for t in tasks:
        if t["id"] == "4": t["status"] = "done"
        if t["id"] == "5":
            t["status"] = "in_progress"
            t["sub_agents"] = [
                {"id": "r1", "title": "Narrative Agent",  "status": "in_progress"},
                {"id": "r2", "title": "DataViz Agent",    "status": "in_progress"},
                {"id": "r3", "title": "Formatting Agent", "status": "todo"},
            ]

    await asyncio.sleep(3)

    for t in tasks:
        if t["id"] == "5":
            t["status"] = "done"
            t["sub_agents"] = [
                {"id": "r1", "title": "Narrative Agent",  "status": "done", "detail": "Executive summary + 4 theme narratives"},
                {"id": "r2", "title": "DataViz Agent",    "status": "done", "detail": "4 charts generated"},
                {"id": "r3", "title": "Formatting Agent", "status": "done", "detail": "PPTX + Markdown assembled"},
            ]

    return {
        "reasoning": [
            {"step_name": "Report Analyst",   "step_text": "Fan-out to Reporting Squad (parallel execution).", "verbose": True},
            {"step_name": "Narrative Agent",  "step_text": "Executive summary written. 4 theme narratives drafted."},
            {"step_name": "DataViz Agent",    "step_text": "4 charts: friction distribution, impact vs ease, multi-lens stacked, preventability."},
            {"step_name": "Formatting Agent", "step_text": "PPTX assembled. Markdown report finalized."},
        ],
        "plan_tasks": tasks,
        "plan_steps_completed": 5,
        "requires_user_input": False,
        "messages": [AIMessage(content="**Analysis complete!**\n\nPPTX and filtered CSV are ready for download. Now in **Q&A Mode** — ask follow-up questions.")],
        "analysis_complete": True,
        "report_file_path": "report.pptx",
        "data_file_path":   "filtered_data.csv",
    }


async def qa_agent(state: AnalyticsState):
    await asyncio.sleep(1)
    return {
        "reasoning": [{"step_name": "Supervisor", "step_text": "Answering from existing artifacts (`findings`, `synthesis_result`)."}],
        "messages": [AIMessage(content="Based on synthesized data, the highest digital friction occurs during the password reset flow — a **23% drop-off** at the OTP verification step.")],
        "requires_user_input": False,
    }


def build_graph(*args, **kwargs):
    graph = StateGraph(AnalyticsState)

    graph.add_node("supervisor",     supervisor)
    graph.add_node("data_discovery", data_discovery)
    graph.add_node("data_prep",      data_prep)
    graph.add_node("friction",       friction)
    graph.add_node("synthesizer",    synthesizer)
    graph.add_node("critique",       critique)
    graph.add_node("reporting",      reporting)
    graph.add_node("qa_agent",       qa_agent)

    graph.add_conditional_edges("supervisor", route_supervisor, {
        "data_discovery": "data_discovery",
        "data_prep":      "data_prep",
        "friction":       "friction",
        "critique":       "critique",
        "reporting":      "reporting",
        "qa_agent":       "qa_agent",
        END:              END,
    })

    graph.add_edge("data_discovery", END)
    graph.add_edge("data_prep",      END)
    graph.add_edge("friction",       "synthesizer")
    graph.add_edge("synthesizer",    END)
    graph.add_edge("critique",       "reporting")
    graph.add_edge("reporting",      END)
    graph.add_edge("qa_agent",       END)

    graph.add_edge(START, "supervisor")

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)

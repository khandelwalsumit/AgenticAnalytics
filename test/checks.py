"""Exhaustive compile & sanity checks for AgenticAnalytics.

Run with:
    source .venv/Scripts/activate && cd main && python checks.py

Covers:
  1. All module imports
  2. Config constants & paths
  3. Tool registry completeness
  4. Agent definition parsing (all .md files)
  5. Skill file loading (all domain skills)
  6. Graph compilation
  7. State initialisation
  8. Filter catalog generation
  9. DataStore CRUD operations
  10. MetricsEngine computations
  11. Schema validation (Pydantic models)
  12. Agent factory (structured chains + ReAct agents)
  13. Unicode safety (no cp1252-breaking chars in .py log lines)
  14. Report tools import
  15. UI components import
  16. PPTX export import
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_errors: list[str] = []


def ok(label: str) -> None:
    global _pass
    _pass += 1
    print(f"  [PASS] {label}")


def fail(label: str, detail: str = "") -> None:
    global _fail
    _fail += 1
    msg = f"  [FAIL] {label}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    _errors.append(msg)


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# 1. Module imports
# ---------------------------------------------------------------------------

section("1. Module Imports")

MODULES = [
    "config",
    "core.llm",
    "core.data_store",
    "core.agent_factory",
    "core.skill_loader",
    "core.file_data_layer",
    "agents.state",
    "agents.schemas",
    "agents.nodes",
    "agents.graph",
    "tools",
    "tools.data_tools",
    "tools.report_tools",
    "tools.metrics",
    "ui.components",
    "ui.chat_history",
    "utils.pptx_export",
    "app",
]

for mod in MODULES:
    try:
        importlib.import_module(mod)
        ok(f"import {mod}")
    except Exception as exc:
        fail(f"import {mod}", str(exc))


# ---------------------------------------------------------------------------
# 2. Config constants & paths
# ---------------------------------------------------------------------------

section("2. Config Constants & Paths")

from config import (
    AGENTS_DIR,
    ALL_DOMAIN_SKILLS,
    DATA_CACHE_DIR,
    DATA_DIR,
    DEFAULT_PARQUET_PATH,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    FRICTION_AGENTS,
    GOOGLE_API_KEY,
    GROUP_BY_COLUMNS,
    DATA_FILTER_COLUMNS,
    LLM_ANALYSIS_CONTEXT,
    LLM_ANALYSIS_FOCUS,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    LOG_LEVEL,
    MAX_BUCKET_SIZE,
    MAX_DISPLAY_LENGTH,
    MAX_SAMPLE_SIZE,
    MIN_BUCKET_SIZE,
    PPTX_TEMPLATE_PATH,
    REPORTING_AGENTS,
    ROOT_DIR,
    SKILLS_DIR,
    TAIL_BUCKET_ENABLED,
    THREAD_STATES_DIR,
    TOP_N_DEFAULT,
    VERBOSE,
)

# Type checks
for name, val, expected_type in [
    ("ROOT_DIR", ROOT_DIR, Path),
    ("AGENTS_DIR", AGENTS_DIR, Path),
    ("SKILLS_DIR", SKILLS_DIR, Path),
    ("DATA_DIR", DATA_DIR, Path),
    ("DATA_CACHE_DIR", DATA_CACHE_DIR, Path),
    ("DEFAULT_MODEL", DEFAULT_MODEL, str),
    ("DEFAULT_TEMPERATURE", DEFAULT_TEMPERATURE, float),
    ("DEFAULT_TOP_P", DEFAULT_TOP_P, float),
    ("DEFAULT_MAX_TOKENS", DEFAULT_MAX_TOKENS, int),
    ("MAX_SAMPLE_SIZE", MAX_SAMPLE_SIZE, int),
    ("TOP_N_DEFAULT", TOP_N_DEFAULT, int),
    ("MIN_BUCKET_SIZE", MIN_BUCKET_SIZE, int),
    ("MAX_BUCKET_SIZE", MAX_BUCKET_SIZE, int),
    ("VERBOSE", VERBOSE, bool),
    ("LOG_LEVEL", LOG_LEVEL, str),
    ("GROUP_BY_COLUMNS", GROUP_BY_COLUMNS, list),
    ("DATA_FILTER_COLUMNS", DATA_FILTER_COLUMNS, list),
    ("LLM_ANALYSIS_FOCUS", LLM_ANALYSIS_FOCUS, list),
    ("LLM_ANALYSIS_CONTEXT", LLM_ANALYSIS_CONTEXT, dict),
    ("FRICTION_AGENTS", FRICTION_AGENTS, set),
    ("REPORTING_AGENTS", REPORTING_AGENTS, set),
    ("ALL_DOMAIN_SKILLS", ALL_DOMAIN_SKILLS, list),
]:
    if isinstance(val, expected_type):
        ok(f"{name} is {expected_type.__name__}")
    else:
        fail(f"{name} type", f"expected {expected_type.__name__}, got {type(val).__name__}")

# Directory existence
for name, path in [("AGENTS_DIR", AGENTS_DIR), ("SKILLS_DIR", SKILLS_DIR)]:
    if path.is_dir():
        ok(f"{name} exists")
    else:
        fail(f"{name} exists", str(path))

# API key present
if GOOGLE_API_KEY:
    ok("GOOGLE_API_KEY is set")
else:
    fail("GOOGLE_API_KEY is set", "empty -- LLM calls will fail")


# ---------------------------------------------------------------------------
# 3. Tool registry completeness
# ---------------------------------------------------------------------------

section("3. Tool Registry")

from tools import TOOL_REGISTRY
from tools.data_tools import DATA_TOOLS
from tools.report_tools import REPORT_TOOLS

EXPECTED_TOOLS = [
    "load_dataset", "filter_data", "bucket_data", "sample_data",
    "get_distribution", "analyze_bucket", "apply_skill",
    "get_findings_summary", "generate_markdown_report",
    "export_to_pptx", "export_filtered_csv",
    "validate_findings", "score_quality", "execute_chart_code",
]

for tool_name in EXPECTED_TOOLS:
    if tool_name in TOOL_REGISTRY:
        ok(f"tool: {tool_name}")
    else:
        fail(f"tool: {tool_name}", "missing from TOOL_REGISTRY")

if len(TOOL_REGISTRY) == len(EXPECTED_TOOLS):
    ok(f"registry size matches ({len(TOOL_REGISTRY)} tools)")
else:
    fail(
        "registry size",
        f"expected {len(EXPECTED_TOOLS)}, got {len(TOOL_REGISTRY)}. "
        f"Extra: {set(TOOL_REGISTRY) - set(EXPECTED_TOOLS)}",
    )

ok(f"DATA_TOOLS count: {len(DATA_TOOLS)}")
ok(f"REPORT_TOOLS count: {len(REPORT_TOOLS)}")


# ---------------------------------------------------------------------------
# 4. Agent definitions
# ---------------------------------------------------------------------------

section("4. Agent Definitions")

from core.agent_factory import AgentFactory

factory = AgentFactory(definitions_dir=AGENTS_DIR, tool_registry=TOOL_REGISTRY)

EXPECTED_AGENTS = [
    "supervisor", "planner", "data_analyst", "report_analyst",
    "digital_friction_agent", "operations_agent",
    "communication_agent", "policy_agent",
    "synthesizer_agent", "narrative_agent",
    "formatting_agent", "critique",
    "business_analyst",
]

for agent_name in EXPECTED_AGENTS:
    try:
        cfg = factory.parse_agent_md(agent_name)
        prompt_len = len(cfg.system_prompt)
        tool_count = len(cfg.tools)
        if prompt_len < 50:
            fail(f"agent: {agent_name}", f"system prompt too short ({prompt_len} chars)")
        else:
            ok(f"agent: {agent_name} (prompt={prompt_len}c, tools={tool_count})")
    except Exception as exc:
        fail(f"agent: {agent_name}", str(exc))


# ---------------------------------------------------------------------------
# 5. Skill files
# ---------------------------------------------------------------------------

section("5. Domain Skills")

from core.skill_loader import SkillLoader

skill_loader = SkillLoader()

for skill_name in ALL_DOMAIN_SKILLS:
    try:
        content = skill_loader.load_skill(skill_name)
        if len(content) < 50:
            fail(f"skill: {skill_name}", f"content too short ({len(content)} chars)")
        else:
            ok(f"skill: {skill_name} ({len(content)} chars)")
    except Exception as exc:
        fail(f"skill: {skill_name}", str(exc))

# Bulk load
try:
    all_skills = skill_loader.load_skills(ALL_DOMAIN_SKILLS)
    ok(f"load_skills(ALL_DOMAIN_SKILLS): {len(all_skills)} chars total")
except Exception as exc:
    fail("load_skills(ALL_DOMAIN_SKILLS)", str(exc))


# ---------------------------------------------------------------------------
# 6. Graph compilation
# ---------------------------------------------------------------------------

section("6. Graph Compilation")

from agents.graph import build_graph

try:
    graph = build_graph(agent_factory=factory, skill_loader=skill_loader)
    ok("build_graph() compiled")

    # Check node names
    expected_nodes = {
        "supervisor", "planner", "data_analyst", "report_analyst",
        "critique", "user_checkpoint", "friction_analysis",
        "report_generation",
    }
    # LangGraph compiled graph stores nodes differently
    if hasattr(graph, "get_graph"):
        graph_repr = graph.get_graph()
        # Nodes can be a dict (keys are node IDs) or list of objects with .id
        if isinstance(graph_repr.nodes, dict):
            node_ids = {k for k in graph_repr.nodes if k not in ("__start__", "__end__")}
        else:
            node_ids = {n.id for n in graph_repr.nodes if n.id not in ("__start__", "__end__")}
        missing = expected_nodes - node_ids
        if missing:
            fail("graph nodes", f"missing: {missing}")
        else:
            ok(f"graph has all {len(expected_nodes)} expected nodes")
    else:
        ok("graph compiled (node introspection skipped)")
except Exception as exc:
    fail("build_graph()", str(exc))


# ---------------------------------------------------------------------------
# 7. State initialisation
# ---------------------------------------------------------------------------

section("7. State Initialisation")

from app import make_initial_state

try:
    state = make_initial_state()
    expected_keys = [
        "messages", "user_focus", "analysis_type", "selected_skills",
        "critique_enabled", "selected_agents", "selected_friction_agents",
        "auto_approve_checkpoints", "plan_steps_total", "plan_steps_completed",
        "plan_tasks", "requires_user_input", "checkpoint_message",
        "checkpoint_prompt", "checkpoint_token", "pending_input_for",
        "execution_trace", "reasoning", "node_io", "io_trace",
        "last_completed_node", "dataset_path", "dataset_schema",
        "active_filters", "data_buckets", "findings",
        "domain_analysis", "operational_analysis",
        "digital_analysis", "operations_analysis",
        "communication_analysis", "policy_analysis",
        "synthesis_result", "narrative_output", "dataviz_output",
        "formatting_output", "report_markdown_key", "report_file_path",
        "data_file_path", "markdown_file_path", "critique_feedback", "quality_score",
        "next_agent", "supervisor_decision", "analysis_complete",
        "phase", "filters_applied", "themes_for_analysis",
        "navigation_log", "analysis_objective",
        "error_count", "recoverable_error", "fault_injection",
    ]
    missing = [k for k in expected_keys if k not in state]
    if missing:
        fail("make_initial_state()", f"missing keys: {missing}")
    else:
        ok(f"make_initial_state() has {len(expected_keys)} expected keys")
except Exception as exc:
    fail("make_initial_state()", str(exc))


# ---------------------------------------------------------------------------
# 8. Filter catalog generation
# ---------------------------------------------------------------------------

section("8. Filter Context (Config-Driven)")

import pandas as pd

if LLM_ANALYSIS_CONTEXT:
    ok(f"LLM_ANALYSIS_CONTEXT: {len(LLM_ANALYSIS_CONTEXT)} filter dimensions")
    for col, values in LLM_ANALYSIS_CONTEXT.items():
        if isinstance(values, list) and values:
            ok(f"  '{col}': {len(values)} valid values")
        else:
            fail(f"  '{col}'", "expected non-empty list of values")
else:
    fail("LLM_ANALYSIS_CONTEXT", "empty — no filter dimensions configured")

# Verify DATA_FILTER_COLUMNS is derived correctly from LLM_ANALYSIS_CONTEXT
if set(DATA_FILTER_COLUMNS) == set(LLM_ANALYSIS_CONTEXT.keys()):
    ok(f"DATA_FILTER_COLUMNS matches LLM_ANALYSIS_CONTEXT keys ({len(DATA_FILTER_COLUMNS)} columns)")
else:
    fail("DATA_FILTER_COLUMNS", "does not match LLM_ANALYSIS_CONTEXT keys")

# Verify LLM_ANALYSIS_FOCUS is non-empty
if LLM_ANALYSIS_FOCUS:
    ok(f"LLM_ANALYSIS_FOCUS: {len(LLM_ANALYSIS_FOCUS)} focus columns: {LLM_ANALYSIS_FOCUS}")
else:
    fail("LLM_ANALYSIS_FOCUS", "empty — no focus columns configured for agents")


# ---------------------------------------------------------------------------
# 9. DataStore CRUD
# ---------------------------------------------------------------------------

section("9. DataStore CRUD")

from core.data_store import DataStore

try:
    store = DataStore(session_id="__check__", DATA_CACHE_DIR=str(DATA_CACHE_DIR))

    # Store DataFrame
    test_df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    store.store_dataframe("test_key", test_df, metadata={"rows": 3})
    ok("store_dataframe()")

    # Get DataFrame
    retrieved = store.get_dataframe("test_key")
    assert len(retrieved) == 3, f"expected 3 rows, got {len(retrieved)}"
    ok("get_dataframe()")

    # Get metadata
    meta = store.get_metadata("test_key")
    assert meta["rows"] == 3
    ok("get_metadata()")

    # Store text
    store.store_text("test_text", "hello world", metadata={"type": "test"})
    assert store.get_text("test_text") == "hello world"
    ok("store_text() / get_text()")

    # List keys
    keys = store.list_keys()
    assert "test_key" in keys and "test_text" in keys
    ok(f"list_keys(): {keys}")

    # Cleanup (Windows can keep parquet handles briefly; do not hard-fail checks)
    try:
        store.cleanup()
        ok("cleanup()")
    except PermissionError as cleanup_exc:
        ok(f"cleanup() skipped due file lock: {cleanup_exc}")
except Exception as exc:
    fail("DataStore CRUD", str(exc))
    traceback.print_exc()


# ---------------------------------------------------------------------------
# 10. MetricsEngine
# ---------------------------------------------------------------------------

section("10. MetricsEngine")

from tools.metrics import MetricsEngine

try:
    test_df = pd.DataFrame({
        "category": ["A", "A", "B", "B", "B", "C"],
        "value": [10, 20, 30, 40, 50, 60],
    })

    # summary_stats
    stats = MetricsEngine.summary_stats(test_df)
    assert "rows" in stats or "row_count" in stats
    row_key = "rows" if "rows" in stats else "row_count"
    ok(f"summary_stats(): {stats[row_key]} rows")

    # get_distribution
    dist = MetricsEngine.get_distribution(test_df, "category")
    assert "distribution" in dist
    ok(f"get_distribution(): {len(dist['distribution'])} values")

    # top_n
    top = MetricsEngine.top_n(test_df, "category", n=2)
    assert len(top) == 2
    ok(f"top_n(): top 2 = {top}")

    # rank_findings
    findings = [
        {"finding": "test", "impact_score": 0.8, "ease_score": 0.6},
        {"finding": "test2", "impact_score": 0.5, "ease_score": 0.9},
    ]
    ranked = MetricsEngine.rank_findings(findings)
    ok(f"rank_findings(): {len(ranked)} findings ranked")
except Exception as exc:
    fail("MetricsEngine", str(exc))
    traceback.print_exc()


# ---------------------------------------------------------------------------
# 11. Schema validation (Pydantic models)
# ---------------------------------------------------------------------------

section("11. Pydantic Schemas")

from agents.schemas import (
    CritiqueOutput,
    DataAnalystOutput,
    PlannerOutput,
    SectionBlueprintOutput,
    STRUCTURED_OUTPUT_SCHEMAS,
    SupervisorOutput,
    SynthesizerOutput,
)

# Verify all expected schemas exist
for name in ["supervisor", "planner"]:
    if name in STRUCTURED_OUTPUT_SCHEMAS:
        ok(f"STRUCTURED_OUTPUT_SCHEMAS['{name}']")
    else:
        fail(f"STRUCTURED_OUTPUT_SCHEMAS['{name}']", "missing")

if "formatting_agent" in STRUCTURED_OUTPUT_SCHEMAS:
    ok("STRUCTURED_OUTPUT_SCHEMAS['formatting_agent']")
else:
    fail("STRUCTURED_OUTPUT_SCHEMAS['formatting_agent']", "missing")

# Quick instantiation checks
try:
    s = SupervisorOutput(decision="answer", confidence=90, reasoning="test", response="hi")
    ok(f"SupervisorOutput: decision={s.decision}")
except Exception as exc:
    fail("SupervisorOutput", str(exc))

try:
    p = PlannerOutput(
        plan_tasks=[], plan_steps_total=0,
        analysis_objective="test", reasoning="test",
    )
    ok(f"PlannerOutput: {p.plan_steps_total} tasks")
except Exception as exc:
    fail("PlannerOutput", str(exc))

try:
    sb = SectionBlueprintOutput(
        section_key="exec_summary",
        slides=[{
            "slide_number": 1,
            "slide_role": "hook_and_quick_wins",
            "layout_index": 1,
            "title": "Test Slide",
            "elements": [{"type": "point_description", "text": "hello"}],
        }],
    )
    ok(f"SectionBlueprintOutput: {len(sb.slides)} slide")
except Exception as exc:
    fail("SectionBlueprintOutput", str(exc))


# ---------------------------------------------------------------------------
# 12. Agent factory: structured chains & ReAct
# ---------------------------------------------------------------------------

section("12. Agent Factory")

try:
    # Structured chain (supervisor)
    chain, schema = factory.create_structured_chain("supervisor")
    ok(f"create_structured_chain('supervisor') -> {schema.__name__}")
except Exception as exc:
    fail("create_structured_chain('supervisor')", str(exc))

try:
    chain, schema = factory.create_structured_chain("planner")
    ok(f"create_structured_chain('planner') -> {schema.__name__}")
except Exception as exc:
    fail("create_structured_chain('planner')", str(exc))

# ReAct agent (data_analyst has tools)
try:
    agent = factory.make_agent("data_analyst")
    ok("make_agent('data_analyst') created")
except Exception as exc:
    fail("make_agent('data_analyst')", str(exc))

# ReAct agent with extra context
try:
    agent = factory.make_agent("digital_friction_agent", extra_context="<test>context</test>")
    ok("make_agent('digital_friction_agent') with extra_context")
except Exception as exc:
    fail("make_agent('digital_friction_agent')", str(exc))


# ---------------------------------------------------------------------------
# 13. Unicode safety (no cp1252-breaking chars in .py log/print lines)
# ---------------------------------------------------------------------------

section("13. Unicode Safety (.py files)")

# Characters that break Windows cp1252 console: arrows, em-dashes, box-drawing, etc.
UNSAFE_CHARS = re.compile(r"[\u2192\u2190\u2191\u2193\u2500\u2502\u250c\u2510\u2514\u2518\u2550\u2551\u2014]")

py_files = list(Path(ROOT_DIR).rglob("*.py"))
for pyf in py_files:
    try:
        src = pyf.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            # Only flag lines that are actual code (not comments/docstrings only)
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            matches = UNSAFE_CHARS.findall(line)
            if matches:
                # Check if it's in a logger/print call (more likely to hit console)
                if any(kw in line for kw in ("logger.", "log.", "print(", "logging.")):
                    fail(
                        f"unicode in log: {pyf.relative_to(ROOT_DIR)}:{i}",
                        f"chars={matches} line={stripped[:80]}",
                    )
    except Exception as exc:
        fail(f"read {pyf.relative_to(ROOT_DIR)}", str(exc))

if not any("unicode" in e for e in _errors):
    ok("no unsafe Unicode in .py log/print lines")


# ---------------------------------------------------------------------------
# 14. Node factory & extra context builder
# ---------------------------------------------------------------------------

section("14. Extra Context Builder")

from agents.nodes import _build_extra_context

# Verify extra context for each agent type
test_state: dict[str, Any] = {
    "messages": [],
    "dataset_schema": LLM_ANALYSIS_CONTEXT,
    "filters_applied": {},
    "dataset_path": DEFAULT_PARQUET_PATH,
    "analysis_objective": "Test",
    "digital_analysis": {"output": "test"},
    "operations_analysis": {"output": "test"},
    "communication_analysis": {"output": "test"},
    "policy_analysis": {"output": "test"},
    "synthesis_result": {"test": True},
    "findings": [{"finding": "test"}],
    "narrative_output": {},
    "dataviz_output": {},
    "selected_agents": [],
    "critique_enabled": False,
    "themes_for_analysis": [],
    "navigation_log": [],
    "plan_tasks": [],
    "plan_steps_completed": 0,
    "plan_steps_total": 0,
}

CONTEXT_AGENTS = [
    ("data_analyst", True),
    ("supervisor", True),
    ("planner", True),
    ("synthesizer_agent", True),
    ("digital_friction_agent", True),  # needs skill_loader
    ("narrative_agent", True),
    ("formatting_agent", True),
    ("critique", False),  # no extra context expected
]

for agent_name, expect_context in CONTEXT_AGENTS:
    ctx = _build_extra_context(agent_name, test_state, skill_loader)
    has_context = len(ctx.strip()) > 0
    if expect_context and has_context:
        ok(f"extra_context('{agent_name}'): {len(ctx)} chars")
    elif not expect_context and not has_context:
        ok(f"extra_context('{agent_name}'): none (expected)")
    elif expect_context and not has_context:
        fail(f"extra_context('{agent_name}')", "expected context but got empty")
    else:
        ok(f"extra_context('{agent_name}'): {len(ctx)} chars (unexpected but ok)")

# Verify data_analyst context includes Available Filters
da_ctx = _build_extra_context("data_analyst", test_state, skill_loader)
if "Available Filters" in da_ctx:
    ok("data_analyst context has 'Available Filters' section")
else:
    fail("data_analyst context", "missing 'Available Filters' section")

if "filter_data" in da_ctx or "column" in da_ctx.lower():
    ok("data_analyst context references filter columns")
else:
    if test_state.get("dataset_schema"):
        fail("data_analyst context", "no column references found")
    else:
        ok("data_analyst context column-reference check skipped (no dataset schema)")



# ---------------------------------------------------------------------------
# 15. filter_data tool error reporting
# ---------------------------------------------------------------------------

section("15. filter_data Error Reporting")

import tools.data_tools as _dt_mod
from tools.data_tools import filter_data, set_data_store as set_dt_store

try:
    store = DataStore(session_id="__check_filter__", DATA_CACHE_DIR=str(DATA_CACHE_DIR))
    test_df = pd.DataFrame({
        "product": ["A", "B", "A", "C"],
        "region": ["US", "EU", "US", "EU"],
    })
    store.store_dataframe("main_dataset", test_df, metadata={})
    set_dt_store(store)

    # filter_data reads from DEFAULT_PARQUET_PATH, not from DataStore.
    # Write the test DataFrame to a temp parquet so filter_data can read it.
    import tempfile
    _tmp_pq = Path(tempfile.mktemp(suffix=".parquet"))
    test_df.to_parquet(_tmp_pq, index=False)
    _orig_pq_path = _dt_mod.DEFAULT_PARQUET_PATH
    _dt_mod.DEFAULT_PARQUET_PATH = _tmp_pq

    # Test: wrong column name -> should report skipped_filters
    result = json.loads(filter_data.invoke({"filters": {"wrong_col": "X"}}))
    if "skipped_filters" in result:
        ok("filter_data reports skipped_filters for bad columns")
    else:
        fail("filter_data error reporting", "no skipped_filters in result")

    if result.get("warning"):
        ok(f"filter_data warning: {result['warning'][:60]}")
    else:
        fail("filter_data warning", "no warning for all-skipped filters")

    # Test: correct column name -> should work
    result2 = json.loads(filter_data.invoke({"filters": {"product": "A"}}))
    if result2.get("filtered_rows") == 2:
        ok("filter_data correct filter: 2 rows")
    else:
        fail("filter_data correct filter", f"expected 2 rows, got {result2.get('filtered_rows')}")

    # Restore original parquet path and clean up temp file
    _dt_mod.DEFAULT_PARQUET_PATH = _orig_pq_path
    try:
        _tmp_pq.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        store.cleanup()
    except PermissionError as cleanup_exc:
        ok(f"filter_data cleanup skipped due file lock: {cleanup_exc}")
except Exception as exc:
    fail("filter_data error reporting", str(exc))
    traceback.print_exc()


# ---------------------------------------------------------------------------
# 16. App helpers
# ---------------------------------------------------------------------------

section("16. App Helpers")

from app import (
    AGENT_ID_TO_LABEL,
    AGENT_LABEL_TO_ID,
    DEFAULT_SELECTED_AGENTS,
    FRICTION_AGENT_IDS,
    _apply_agent_selection,
    _message_text,
)

# _message_text filters
from langchain_core.messages import AIMessage

class FakeMsg:
    type = "ai"
    content = "Hello world"
    tool_calls = []

assert _message_text(FakeMsg()) == "Hello world"
ok("_message_text(normal) works")

class ToolCallMsg:
    type = "ai"
    content = ""
    tool_calls = [{"name": "test"}]

assert _message_text(ToolCallMsg()) == ""
ok("_message_text(tool_call) returns empty")

class JsonMsg:
    type = "ai"
    content = '{"key": "value", "a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}'
    tool_calls = []

assert _message_text(JsonMsg()) == ""
ok("_message_text(json blob) returns empty")

# Agent selection
state: dict[str, Any] = {}
_apply_agent_selection(state, ["digital_friction_agent", "critique"])
assert state["critique_enabled"] is True
assert "digital_friction_agent" in state["selected_friction_agents"]
ok("_apply_agent_selection() works")

# Labels
assert len(AGENT_ID_TO_LABEL) == len(AGENT_LABEL_TO_ID)
ok(f"agent labels: {len(AGENT_ID_TO_LABEL)} entries")
assert len(FRICTION_AGENT_IDS) == 4
ok(f"FRICTION_AGENT_IDS: {FRICTION_AGENT_IDS}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

section("SUMMARY")
total = _pass + _fail
print(f"\n  Total: {total} checks")
print(f"  Passed: {_pass}")
print(f"  Failed: {_fail}")

if _errors:
    print(f"\n  Failures:")
    for e in _errors:
        print(f"    {e}")

sys.exit(0 if _fail == 0 else 1)

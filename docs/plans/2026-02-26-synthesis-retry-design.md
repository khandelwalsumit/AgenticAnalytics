---
name: synthesis-retry
description: Design for file-based synthesis persistence and report generation retry
---

# Synthesis Retry & File-Based Context Design

## Overview
This document outlines the architecture to support deterministic retries for the report generation phase, while simultaneously offloading the massive `synthesis_result` payload from the LangGraph state into the `DataStore`.

## Context & Motivation
Currently, the `Synthesizer Agent` produces a large nested JSON object (`synthesis_result`), which is stored entirely in the `AnalyticsState`. For large datasets or complex analyses, this pushes the LangGraph state toward token limits and inflates checkpoint sizes. Furthermore, if a user types "retry" or "regenerate the report", the system lacks deterministic routing to immediately rerun the report creation using that saved data. 

## Approach: File-Based Context + Report-Only Retry
We will alter the state to store only a lightweight reference (`synthesis_output_file`) rather than the heavy JSON payload, and update the graph supervisor to detect a retry intent and route directly to the `report_generation` subgraph.

### 1. State Updates (`agents/state.py`)
- Add `synthesis_output_file: str` to `AnalyticsState`.
- Retain `synthesis_result: dict[str, Any]` in the typing (or optional) for backward compatibility, but it will be kept empty or removed once persisted.

### 2. Synthesizer Output Persistence (`agents/graph.py`)
- In `friction_analysis_node`, after `synthesizer_node` completes, serialize the `synthesis_result` dictionary to JSON.
- Store this JSON in the active session's `DataStore`.
- Update the final merge dictionary so that `synthesis_output_file` holds the `DataStore` key, and explicitly clear `synthesis_result` (e.g., `final["synthesis_result"] = {}`) to prevent state bloat.

### 3. Reporting Subagents Rehydration (`agents/nodes.py` & `agents/graph_helpers.py`)
- In `agents/nodes.py` -> `_build_extra_context`, when configuring the system prompts for `REPORTING_AGENTS` (`narrative_agent`, `formatting_agent`, `report_analyst`), dynamically fetch the `synthesis_output_file` from the `DataStore` and parse it into the `synthesis` dictionary instead of reading `state["synthesis_result"]`.
- In `agents/graph_helpers.py` -> `_build_deterministic_dataviz_output`, apply the same rehydration logic so charts generate correctly from the offloaded synthesized data.

### 4. Retry Routing (`agents/definitions/supervisor.md`)
- Enhance the supervisor prompt instructions to explicitly recognize commands like "retry", "regenerate report", or "fix the slides".
- Instruct the supervisor to issue a decision of `{"next_agent": "report_generation"}` if the analysis is fully complete and the user simply wants a new output.

## Implications & Trade-offs
- **Pros:** Massively reduces LangGraph checkpoint size. Preserves synthesis state across `report_generation` retries. Follows the established paradigm from the upstream friction agents.
- **Cons:** Requires explicit file reading in subsequent downstream nodes and prompts. Can break if DataStore goes out of sync (mitigated by `_rehydrate_friction_outputs` app logic equivalent if needed later, though reports are typically session-bound).

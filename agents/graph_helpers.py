"""Helper utilities for graph orchestration and deterministic artifact assembly."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.nodes import AGENT_STATE_FIELDS
from agents.state import AnalyticsState
from config import DATA_DIR, DATA_OUTPUT_DIR, DATA_CACHE_DIR
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
    tmp_candidate = _thread_tmp_dir() / p.name
    if tmp_candidate.exists():
        return True
    if not p.is_absolute():
        alt = Path(DATA_DIR) / p.name
        if alt.exists():
            return True
    return False


def _safe_thread_id(raw: str) -> str:
    text = str(raw or "").strip() or "unknown_thread"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:80]


def _thread_tmp_dir() -> Path:
    thread_id = "unknown_thread"
    try:
        raw_thread_id = cl.user_session.get("thread_id")
        if raw_thread_id:
            thread_id = str(raw_thread_id)
    except Exception:
        thread_id = "unknown_thread"
    return Path(DATA_CACHE_DIR) / _safe_thread_id(thread_id)


def _thread_output_dir() -> Path:
    thread_id = "unknown_thread"
    try:
        raw_thread_id = cl.user_session.get("thread_id")
        if raw_thread_id:
            thread_id = str(raw_thread_id)
    except Exception:
        thread_id = "unknown_thread"
    return Path(DATA_OUTPUT_DIR) / _safe_thread_id(thread_id)


def _validate_narrative(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    payload = result.get("narrative_output", {})
    full = str(payload.get("full_response", "") if isinstance(payload, dict) else "").strip()
    if not full:
        return ["narrative_output.full_response is empty."]

    slide_tag_pattern = r"<!--\s*SLIDE\s*:\s*.+?-->"
    tags = re.findall(slide_tag_pattern, full, flags=re.IGNORECASE | re.DOTALL)
    if len(tags) < 3:
        errors.append("Narrative markdown must include at least 3 `<!-- SLIDE: ... -->` tags.")

    if _extract_json(full):
        errors.append("Narrative output appears JSON-like; expected pure markdown with slide tags.")

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


def _build_deterministic_dataviz_output(state: dict[str, Any]) -> dict[str, Any]:
    """Generate required charts deterministically via Python chart scripts."""
    synthesis = state.get("synthesis_result", {})
    if not synthesis and state.get("synthesis_output_file"):
        import chainlit as cl
        data_store = cl.user_session.get("data_store")
        if data_store:
            try:
                loaded = data_store.get_text(state["synthesis_output_file"])
                if loaded:
                    synthesis = json.loads(loaded)
            except Exception as e:
                logger.error("Failed to rehydrate synthesis_output_file: %s", e)

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
            chart_path = str(_thread_tmp_dir() / spec["output_filename"])

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
    logger.info("DataViz deterministic chart generation completed.")
    return {
        "messages": [AIMessage(content=payload_json)],
        "reasoning": [{
            "step_name": "DataViz Script",
            "step_text": "Executed deterministic Python chart scripts and generated required visual assets.",
            "agent": "dataviz_script",
        }],
        "dataviz_output": {
            "output": payload_json[:200],
            "full_response": payload_json,
            "agent": "dataviz_script",
        },
    }


def _parse_slide_tag(raw_tag: str) -> dict[str, str]:
    """Parse one <!-- SLIDE: ... --> tag into section/layout/title fields."""
    inner = str(raw_tag or "").strip()
    inner = inner.removeprefix("<!--").removesuffix("-->").strip()
    if inner.lower().startswith("slide:"):
        inner = inner[6:].strip()

    parts = [p.strip() for p in inner.split("|") if p.strip()]
    if not parts:
        return {}

    section_type = parts[0].strip()
    layout = ""
    title = ""
    for part in parts[1:]:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key == "layout":
            layout = value
        elif key == "title":
            title = value

    return {
        "section_type": section_type,
        "layout": layout,
        "title": title,
    }


def _parse_narrative_slide_blocks(markdown_text: str) -> list[dict[str, str]]:
    """Split narrative markdown into ordered slide blocks using SLIDE tags."""
    text = str(markdown_text or "")
    tag_pattern = re.compile(r"<!--\s*SLIDE\s*:.*?-->", flags=re.IGNORECASE | re.DOTALL)
    matches = list(tag_pattern.finditer(text))
    blocks: list[dict[str, str]] = []
    if not matches:
        return blocks

    for idx, match in enumerate(matches):
        tag_text = match.group(0)
        parsed = _parse_slide_tag(tag_text)
        if not parsed:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        blocks.append({
            "section_type": parsed.get("section_type", ""),
            "layout": parsed.get("layout", ""),
            "title": parsed.get("title", ""),
            "body": body,
            "tag": tag_text,
        })

    return blocks


def _extract_deck_title_subtitle_from_markdown(markdown_text: str) -> tuple[str, str]:
    """Pick deck title/subtitle from narrative markdown."""
    title = "Friction Analysis Report"
    subtitle = ""
    lines = [ln.strip() for ln in str(markdown_text or "").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("<!--")]

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip() or title
            break

    for line in lines:
        if line.startswith("## "):
            subtitle = line[3:].strip()
            break
        if not line.startswith("#"):
            subtitle = line
            break
    return title, subtitle


def _build_fallback_formatting_from_narrative_markdown(narrative_markdown: str) -> dict[str, Any]:
    """Deterministic fallback blueprint from narrative slide tags."""
    blocks = _parse_narrative_slide_blocks(narrative_markdown)
    deck_title, deck_subtitle = _extract_deck_title_subtitle_from_markdown(narrative_markdown)
    if not blocks:
        blocks = [{
            "section_type": "executive_summary",
            "layout": "title_slide",
            "title": deck_title,
            "body": narrative_markdown.strip(),
            "tag": "",
        }]

    slides: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks, start=1):
        layout_raw = str(block.get("layout", "")).strip().lower()
        layout_map = {
            "title_impact": "title_slide",
            "section_divider": "section_divider",
            "callout_stat": "callout",
            "three_column": "three_column",
            "table_full": "table",
            "action_list": "table",
            "scorecard_drivers": "scorecard_table",
        }
        layout = layout_map.get(layout_raw, layout_raw or "callout")
        if layout not in {"title_slide", "section_divider", "callout", "three_column", "table", "scorecard_table"}:
            layout = "callout"

        body = str(block.get("body", "")).strip()
        elements: list[dict[str, Any]] = []
        if body:
            elements.append({
                "type": "paragraph",
                "text": body[:4000],
            })
        else:
            elements.append({
                "type": "paragraph",
                "text": "Slide content generated from narrative fallback.",
            })

        slides.append({
            "slide_number": idx,
            "section_type": str(block.get("section_type", "")).strip() or "narrative",
            "layout": layout,
            "title": str(block.get("title", "")).strip() or f"Slide {idx}",
            "elements": elements,
        })

    return {
        "deck_title": deck_title,
        "deck_subtitle": deck_subtitle,
        "total_slides": len(slides),
        "qa_enhancements_applied": [
            "fallback: generated deterministic slide blueprint from narrative markdown",
        ],
        "slides": slides,
    }


def _validate_formatting_blueprint(result: dict[str, Any]) -> list[str]:
    """Validate formatting agent structured deck blueprint."""
    payload = result.get("formatting_output", {})
    full = payload.get("full_response", "") if isinstance(payload, dict) else ""
    data = _extract_json(full)

    if not isinstance(data, dict):
        return ["Formatting output is not valid JSON."]

    slides = data.get("slides", [])
    if not isinstance(slides, list) or len(slides) < 3:
        return ["Formatting output must include at least 3 slides."]
    return []


def _styled_text(text: str, style: str) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    style_key = str(style or "normal").strip().lower()
    if style_key == "bold":
        return f"**{content}**"
    if style_key == "italic":
        return f"*{content}*"
    if style_key == "bold_italic":
        return f"***{content}***"
    return content


def _resolve_chart_placeholder(
    value: str,
    chart_paths: dict[str, str],
    unused_ids: list[str],
) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if text in chart_paths:
        if text in unused_ids:
            unused_ids.remove(text)
        return text

    m = re.search(r"\{\{\s*chart\.([a-zA-Z0-9_-]+)\s*\}\}", text)
    if m:
        key = m.group(1).strip()
        if key in chart_paths:
            if key in unused_ids:
                unused_ids.remove(key)
            return key

    stem = Path(text).stem
    if stem in chart_paths:
        if stem in unused_ids:
            unused_ids.remove(stem)
        return stem

    if unused_ids:
        return unused_ids.pop(0)
    return ""


def _build_slide_plan_from_formatting(
    formatting_json: dict[str, Any],
    chart_paths: dict[str, str],
) -> dict[str, Any]:
    slides = formatting_json.get("slides", []) if isinstance(formatting_json, dict) else []
    if not isinstance(slides, list):
        slides = []

    # Keep deterministic order even if model returns unordered slide_number.
    slides = sorted(
        [s for s in slides if isinstance(s, dict)],
        key=lambda s: _safe_int(s.get("slide_number", 0), 0) or 10_000,
    )

    plan_slides: list[dict[str, Any]] = []
    unused_chart_ids = list(chart_paths.keys())

    for idx, slide in enumerate(slides, start=1):
        layout = str(slide.get("layout", "callout")).strip() or "callout"
        section_type = str(slide.get("section_type", "")).strip().lower()
        title = _stringify(slide.get("title", ""), limit=180) or f"Slide {idx}"
        elements = slide.get("elements", [])
        if not isinstance(elements, list):
            elements = []

        subtitle = ""
        points: list[str] = []
        visual = "none"
        notes: list[str] = []
        qa_note = _stringify(slide.get("qa_note", ""), limit=250)
        if qa_note:
            notes.append(f"QA: {qa_note}")

        for elem in elements:
            if not isinstance(elem, dict):
                continue
            etype = str(elem.get("type", "")).strip()

            if etype == "image_prompt":
                placeholder_raw = str(elem.get("placeholder_id", "")).strip() or str(elem.get("text", "")).strip()
                placeholder = _resolve_chart_placeholder(placeholder_raw, chart_paths, unused_chart_ids)
                if placeholder:
                    visual = placeholder
                caption = _stringify(elem.get("caption", ""), limit=220)
                if caption:
                    notes.append(caption)
                continue

            if etype == "table":
                headers = elem.get("headers", [])
                rows = elem.get("rows", [])
                if isinstance(headers, list) and headers:
                    points.append(" | ".join([_stringify(h, limit=80) for h in headers]))
                if isinstance(rows, list):
                    for row in rows[:8]:
                        if isinstance(row, list):
                            points.append(" | ".join([_stringify(cell, limit=120) for cell in row]))
                continue

            text = _stringify(elem.get("text", ""), limit=600)
            if not text:
                continue
            styled = _styled_text(text, str(elem.get("style", "normal")))
            level = max(1, min(4, _safe_int(elem.get("level", 1), 1)))

            if layout == "title_slide":
                if not subtitle and etype in {"heading2", "heading3", "paragraph", "callout_text", "bullet"}:
                    subtitle = styled
                else:
                    notes.append(styled)
                continue

            if etype == "bullet":
                label = _stringify(elem.get("label", ""), limit=80)
                content = f"{label}: {styled}" if label else styled
                indent = "  " * max(0, level - 1)
                points.append(f"{indent}- {content}")
            else:
                points.append(styled)

        if layout == "title_slide":
            plan_slides.append({
                "type": "title",
                "title": title,
                "subtitle": subtitle,
                "points": [],
                "visual": "none",
                "notes": " ".join(notes).strip(),
            })
            continue

        slide_type = "content"
        if visual == "impact_ease_scatter" or "matrix" in section_type:
            slide_type = "impact_ease"
        elif visual != "none" or layout in {"scorecard_table", "three_column"}:
            slide_type = "theme_detail"

        plan_slides.append({
            "type": slide_type,
            "title": title,
            "points": points[:12],
            "visual": visual,
            "notes": " ".join(notes).strip(),
        })

    if not plan_slides:
        deck_title = _stringify(formatting_json.get("deck_title", ""), limit=140) or "Friction Analysis Report"
        deck_subtitle = _stringify(formatting_json.get("deck_subtitle", ""), limit=180)
        plan_slides.append({
            "type": "title",
            "title": deck_title,
            "subtitle": deck_subtitle,
            "points": [],
            "visual": "none",
            "notes": "Auto-generated fallback title slide.",
        })

    return {"slides": plan_slides}


def _run_artifact_writer_node(
    state: AnalyticsState,
    narrative_result: dict[str, Any],
    formatting_result: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically create dataviz + pptx + csv; persist narrative markdown directly."""
    dataviz_result = _build_deterministic_dataviz_output(state)
    dataviz_errors = _validate_dataviz(dataviz_result)
    if dataviz_errors:
        raise RuntimeError(f"Deterministic DataViz generation failed validation: {dataviz_errors}")

    narrative_payload = narrative_result.get("narrative_output", {})
    narrative_markdown = str(
        narrative_payload.get("full_response", "") if isinstance(narrative_payload, dict) else ""
    ).strip()
    if not narrative_markdown:
        narrative_markdown = "# Analysis Report\n\nNo narrative markdown was generated."

    formatting_payload = formatting_result.get("formatting_output", {})
    formatting_json = _extract_json(
        formatting_payload.get("full_response", "") if isinstance(formatting_payload, dict) else ""
    )
    if not isinstance(formatting_json, dict) or not isinstance(formatting_json.get("slides", []), list):
        formatting_json = _build_fallback_formatting_from_narrative_markdown(narrative_markdown)

    dataviz_json = _extract_json(
        dataviz_result.get("dataviz_output", {}).get("full_response", "")
        if isinstance(dataviz_result.get("dataviz_output", {}), dict) else ""
    )

    chart_paths = _build_chart_paths_map(dataviz_json)
    slide_plan = _build_slide_plan_from_formatting(formatting_json, chart_paths)

    # Persist narrative markdown directly to DataStore + output path.
    output_dir = _thread_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = str(output_dir / "complete_analysis.md")
    Path(markdown_path).write_text(narrative_markdown, encoding="utf-8")

    report_key = "report_markdown"
    data_store = cl.user_session.get("data_store")
    if data_store is not None:
        try:
            report_key = data_store.store_text(
                "report_markdown",
                narrative_markdown,
                {"agent": "narrative_agent", "type": "report_markdown"},
            )
        except Exception:
            report_key = "report_markdown"

    ppt_tool = TOOL_REGISTRY["export_to_pptx"]
    ppt_raw = ppt_tool.invoke({
        "slide_plan_json": json.dumps(slide_plan, default=str),
        "chart_paths_json": json.dumps(chart_paths, default=str),
        "report_key": report_key,
    })
    ppt_data = _extract_json(str(ppt_raw))
    report_path = _resolve_existing_path(str(ppt_data.get("pptx_path", "")).strip())

    csv_tool = TOOL_REGISTRY["export_filtered_csv"]
    csv_raw = csv_tool.invoke({})
    csv_data = _extract_json(str(csv_raw))
    data_path = _resolve_existing_path(str(csv_data.get("csv_path", "")).strip())

    payload = {
        "report_markdown_key": report_key,
        "markdown_file_path": markdown_path,
        "report_file_path": report_path,
        "data_file_path": data_path,
    }
    payload_json = json.dumps(payload, indent=2)
    logger.info("Artifact writer completed deterministic exports: %s", payload)
    return {
        "messages": [AIMessage(content=payload_json)],
        "reasoning": [{
            "step_name": "Artifact Writer",
            "step_text": "Ran chart scripts, stored narrative markdown, resolved placeholders, and generated PPTX and CSV artifacts.",
            "agent": "artifact_writer_node",
        }],
        "dataviz_output": dataviz_result.get("dataviz_output", {}),
        "report_markdown_key": report_key,
        "markdown_file_path": markdown_path,
        "report_file_path": report_path,
        "data_file_path": data_path,
    }


def _resolve_existing_path(raw_path: str) -> str:
    path = str(raw_path or "").strip()
    if not path:
        return ""
    p = Path(path)
    if p.exists():
        return str(p)
    tmp_alt = _thread_tmp_dir() / p.name
    if tmp_alt.exists():
        return str(tmp_alt)
    if not p.is_absolute():
        alt = Path(DATA_DIR) / p.name
        if alt.exists():
            return str(alt)
    return path


def _stringify(value: Any, *, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float, bool)):
        text = str(value)
    elif isinstance(value, list):
        parts = [_stringify(v, limit=limit) for v in value]
        text = "; ".join([p for p in parts if p])
    elif isinstance(value, dict):
        parts: list[str] = []
        for k, v in value.items():
            rendered = _stringify(v, limit=limit)
            if rendered:
                label = str(k).replace("_", " ").strip().title()
                parts.append(f"{label}: {rendered}")
        text = " | ".join(parts)
    else:
        text = str(value).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _build_chart_paths_map(dataviz_json: dict[str, Any]) -> dict[str, str]:
    chart_paths: dict[str, str] = {}
    charts = dataviz_json.get("charts", []) if isinstance(dataviz_json, dict) else []
    if not isinstance(charts, list):
        return chart_paths
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        chart_type = _stringify(chart.get("type", ""), limit=80)
        raw_path = _stringify(chart.get("file_path", ""), limit=400)
        resolved_path = _resolve_existing_path(raw_path)
        if chart_type and resolved_path:
            chart_paths[chart_type] = resolved_path
    return chart_paths


def _build_executive_summary_message(narrative_payload: dict[str, Any]) -> str:
    """Build a concise user-facing summary from narrative markdown."""
    full = str(narrative_payload.get("full_response", "") if isinstance(narrative_payload, dict) else "").strip()
    if not full:
        return "Executive summary is ready in the final report artifacts."

    blocks = _parse_narrative_slide_blocks(full)
    target_block = None
    for block in blocks:
        section = str(block.get("section_type", "")).lower()
        if "executive" in section or "pain_point" in section:
            target_block = block
            break
    if target_block is None and blocks:
        target_block = blocks[0]

    if target_block is None:
        return "Executive summary is ready in the final report artifacts."

    lines = [ln.strip() for ln in str(target_block.get("body", "")).splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        if not ln or ln == "---" or ln.startswith("<!--"):
            continue
        text = re.sub(r"^#+\s*", "", ln)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = text.strip()
        if text:
            cleaned.append(text)
        if len(cleaned) >= 2:
            break

    if not cleaned:
        return "Executive summary is ready in the final report artifacts."
    return " ".join(cleaned)


def _build_friction_reasoning_entries(
    lens_ids: list[str],
    state: dict[str, Any],
    synth_result: dict[str, Any],
) -> list[dict[str, str]]:
    """Curated reasoning entries for friction-analysis composite step."""
    bucket_count = len(state.get("data_buckets", {})) if isinstance(state.get("data_buckets", {}), dict) else 0
    bucket_count = bucket_count or 1
    entries: list[dict[str, str]] = []
    for aid in lens_ids:
        title = FRICTION_SUB_AGENTS.get(aid, {}).get("title", aid.replace("_", " ").title())
        lens_name = title.replace(" Agent", "")
        entries.append({
            "step_name": title,
            "step_text": f"Running {bucket_count} theme bucket(s) through the {lens_name} lens.",
            "agent": aid,
        })

    synth_text = ""
    for r in synth_result.get("reasoning", []):
        if isinstance(r, dict):
            synth_text = str(r.get("step_text", "")).strip()
            if synth_text:
                break
    entries.append({
        "step_name": "Synthesizer Agent",
        "step_text": synth_text or "Consolidating cross-lens findings into a single executive synthesis.",
        "agent": "synthesizer_agent",
    })
    return entries


def _build_report_reasoning_entries() -> list[dict[str, str]]:
    """Curated reasoning entries for report-generation composite step."""
    return [
        {
            "step_name": "Narrative Agent",
            "step_text": "Shaping a McKinsey-style executive narrative with quantified findings and a clear decision arc.",
            "agent": "narrative_agent",
        },
        {
            "step_name": "Formatting Agent",
            "step_text": "Designing a polished slide blueprint with chart placeholders and actionable hierarchy.",
            "agent": "formatting_agent",
        },
        {
            "step_name": "DataViz Script",
            "step_text": "Firing deterministic Python scripts to generate chart outputs for the deck.",
            "agent": "dataviz_script",
        },
        {
            "step_name": "Artifact Writer",
            "step_text": "Creating PPT, data and md files by binding chart outputs into the slide placeholders.",
            "agent": "artifact_writer_node",
        },
    ]


def _validate_artifact_paths(result: dict[str, Any]) -> list[str]:
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
    lines = [f"Execution contract for {agent_id} (attempt {attempt}/{max_attempts})."]
    if required_tools:
        lines.append(f"Required tool calls in this attempt: {', '.join(required_tools)}.")
    else:
        lines.append("No tool calls are required for this attempt.")
    lines.append("Do not return an empty response.")

    if agent_id == "narrative_agent":
        lines.extend([
            "Call get_findings_summary before final output.",
            "Return pure markdown with explicit `<!-- SLIDE: ... -->` boundary tags.",
            "Do not return JSON.",
        ])
    elif agent_id == "formatting_agent":
        lines.extend([
            "Return only structured deck JSON with deck metadata and detailed slide elements.",
            "Use image placeholders via image_prompt.placeholder_id (e.g., {{chart.friction_distribution}}).",
            "Do not call export tools from this node.",
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
    "formatting_agent": {
        "title": "Formatting Agent",
        "detail": "Structured slide blueprint with chart placeholders",
    },
    "artifact_writer_node": {
        "title": "Artifact Writer",
        "detail": "Creating PPT, data and md files",
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


def _merge_parallel_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
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


async def _set_task_sub_agents_and_emit(
    tasks: list[dict[str, Any]],
    *,
    agent_name: str,
    sub_agents: list[dict[str, Any]],
    task_status: str | None = None,
) -> list[dict[str, Any]]:
    """Update task sub-agent rows and push TaskList UI update."""
    updated = _set_task_sub_agents(
        tasks,
        agent_name=agent_name,
        sub_agents=sub_agents,
        task_status=task_status,
    )
    await _emit_task_list_update(updated)
    return updated


def _make_sub_agent_entry(
    catalog: dict[str, dict[str, str]],
    agent_id: str,
    *,
    status: str,
    detail_override: str | None = None,
) -> dict[str, Any]:
    """Build one sub-agent entry from catalog metadata."""
    meta = catalog[agent_id]
    return {
        "id": agent_id,
        "title": meta["title"],
        "detail": detail_override if detail_override is not None else meta["detail"],
        "status": status,
    }


def _set_sub_agent_status(
    sub_agents: list[dict[str, Any]],
    agent_id: str,
    *,
    status: str,
    detail: str | None = None,
) -> None:
    """Mutate one sub-agent entry status/detail in place."""
    for item in sub_agents:
        if item.get("id") != agent_id:
            continue
        item["status"] = status
        if detail is not None:
            item["detail"] = detail
        return


def _merge_state_deltas(
    *sources: dict[str, Any],
    list_keys: set[str] | None = None,
    skip_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Merge multiple node deltas into one dict.

    Scalar values are last-writer-wins; list keys are concatenated.
    """
    out: dict[str, Any] = {}
    merge_list_keys = list_keys or set()
    ignore = skip_keys or set()

    for src in sources:
        for key, value in src.items():
            if key in ignore:
                continue
            if key in merge_list_keys and isinstance(value, list):
                out.setdefault(key, [])
                out[key].extend(value)
            else:
                out[key] = value
    return out


def _record_plan_progress(
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    agent_name: str,
    mark_analysis_complete: bool = False,
) -> None:
    """Increment and persist plan progress in result delta."""
    tasks = result.get("plan_tasks", state.get("plan_tasks", []))
    total = max(state.get("plan_steps_total", 0), len(tasks) if isinstance(tasks, list) else 0)
    done_count = len([t for t in tasks if isinstance(t, dict) and t.get("status") == "done"]) if isinstance(tasks, list) else 0
    completed = max(state.get("plan_steps_completed", 0), done_count)
    result["plan_steps_total"] = total
    result["plan_steps_completed"] = completed
    logger.info("Plan progress: %d/%d (agent=%s)", completed, total, agent_name)

    if mark_analysis_complete and total > 0 and completed >= total:
        result["analysis_complete"] = True
        result["phase"] = "qa"
        logger.info("Pipeline complete -- entering Q&A mode.")


def _persist_friction_outputs(
    lens_ids: list[str],
    results: list[dict[str, Any]],
) -> dict[str, str]:
    """Persist each friction lens full_response to DataStore and return key map."""
    data_store = cl.user_session.get("data_store")
    output_keys: dict[str, str] = {}
    if not data_store:
        return output_keys

    for agent_id, result in zip(lens_ids, results):
        field = AGENT_STATE_FIELDS.get(agent_id, "")
        if not field:
            continue
        agent_output = result.get(field, {})
        full_response = agent_output.get("full_response", "") if isinstance(agent_output, dict) else ""
        if not full_response:
            continue
        key = f"{agent_id}_output"
        data_store.store_text(key, full_response, {"agent": agent_id, "type": "friction_output"})
        output_keys[agent_id] = key
        logger.info("  DataStore: wrote %s (%d chars)", key, len(full_response))
    return output_keys


# ═══════════════════════════════════════════════════════════════════════════
# Section-based formatting pipeline
# ═══════════════════════════════════════════════════════════════════════════


def _build_section_formatting_message(
    section_key: str,
    section_data: dict[str, Any],
    synthesis_summary: dict[str, Any],
) -> str:
    """Build the HumanMessage content for a single section formatting call."""
    template_spec = section_data.get("template_spec", {})
    visual_hierarchy = section_data.get("visual_hierarchy", {})
    narrative_chunk = section_data.get("narrative_chunk", "")

    chart_placeholders = [
        "{{chart.friction_distribution}}",
        "{{chart.impact_ease_scatter}}",
        "{{chart.driver_breakdown}}",
    ]

    parts = [
        f"section_key: {section_key}",
        "",
        "--- TEMPLATE SPEC ---",
        json.dumps(template_spec, indent=2, default=str),
        "",
        "--- VISUAL HIERARCHY ---",
        json.dumps(visual_hierarchy, indent=2, default=str),
        "",
        "--- CHART PLACEHOLDERS ---",
        json.dumps(chart_placeholders),
        "",
        "--- SYNTHESIS SUMMARY (verification only) ---",
        json.dumps(synthesis_summary, indent=2, default=str),
        "",
        "--- NARRATIVE CHUNK ---",
        narrative_chunk,
    ]
    return "\n".join(parts)


def _validate_section_blueprint(result: dict[str, Any]) -> list[str]:
    """Validate a single section formatting agent output."""
    payload = result.get("formatting_output", {})
    full = payload.get("full_response", "") if isinstance(payload, dict) else ""
    data = _extract_json(full)

    if not isinstance(data, dict):
        return ["Section formatting output is not valid JSON."]

    slides = data.get("slides", [])
    if not isinstance(slides, list) or len(slides) < 1:
        return ["Section formatting output must include at least 1 slide."]

    section_key = data.get("section_key", "")
    expected_counts = {"exec_summary": 3, "impact": 3}
    expected = expected_counts.get(section_key)
    if expected and len(slides) != expected:
        return [f"Section '{section_key}' expected {expected} slides but got {len(slides)}."]

    return []


def _build_fallback_section_blueprint(
    section_key: str,
    section_data: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic fallback: build section blueprint from narrative slide tags."""
    slide_blocks = section_data.get("slides", [])
    template_spec = section_data.get("template_spec", {})

    # Get default layout index from template spec
    default_layout = 1
    if "slides" in template_spec:
        spec_slides = template_spec["slides"]
        if spec_slides:
            default_layout = spec_slides[0].get("layout_index", 1)
    elif "per_theme_slide" in template_spec:
        default_layout = template_spec["per_theme_slide"].get("layout_index", 19)

    result_slides: list[dict[str, Any]] = []

    if section_key == "exec_summary":
        # Merge into 3 slides: hook, situation+pain points, quick wins
        hook_blocks = [b for b in slide_blocks if "executive" in b.get("section_type", "").lower()]
        pain_blocks = [b for b in slide_blocks if "pain" in b.get("section_type", "").lower()]
        wins_blocks = [b for b in slide_blocks if "quick" in b.get("section_type", "").lower()]

        # Slide 1: Hook
        hook_text = hook_blocks[0]["body"] if hook_blocks else "Analysis report"
        result_slides.append({
            "slide_number": 1,
            "slide_role": "hook",
            "layout_index": template_spec.get("slides", [{}])[0].get("layout_index", 6) if template_spec.get("slides") else 6,
            "title": hook_blocks[0].get("title", "Friction Analysis") if hook_blocks else "Friction Analysis",
            "elements": [{"type": "point_description", "text": hook_text[:500]}],
        })

        # Slide 2: Situation + pain points merged
        pain_text_parts = []
        for b in (hook_blocks[1:] + pain_blocks):
            pain_text_parts.append(b.get("body", "")[:300])
        result_slides.append({
            "slide_number": 2,
            "slide_role": "situation_and_pain_points",
            "layout_index": template_spec.get("slides", [{}, {}])[1].get("layout_index", 1) if len(template_spec.get("slides", [])) > 1 else 1,
            "title": "The Situation & Key Pain Points",
            "elements": [{"type": "point_description", "text": t} for t in pain_text_parts[:5]],
        })

        # Slide 3: Quick wins
        wins_text = wins_blocks[0]["body"] if wins_blocks else "Quick wins to be identified."
        result_slides.append({
            "slide_number": 3,
            "slide_role": "quick_wins",
            "layout_index": template_spec.get("slides", [{}, {}, {}])[2].get("layout_index", 1) if len(template_spec.get("slides", [])) > 2 else 1,
            "title": "Quick Wins: Start Monday",
            "elements": [{"type": "point_description", "text": wins_text[:500]}],
        })

    elif section_key == "impact":
        matrix_blocks = [b for b in slide_blocks if "matrix" in b.get("section_type", "").lower() and "bet" not in b.get("section_type", "").lower()]
        bet_blocks = [b for b in slide_blocks if "bet" in b.get("section_type", "").lower()]
        rec_blocks = [b for b in slide_blocks if "recommend" in b.get("section_type", "").lower()]

        spec_slides = template_spec.get("slides", [])

        result_slides.append({
            "slide_number": 1,
            "slide_role": "impact_matrix",
            "layout_index": spec_slides[0].get("layout_index", 51) if spec_slides else 51,
            "title": matrix_blocks[0].get("title", "Impact vs. Ease Matrix") if matrix_blocks else "Impact vs. Ease Matrix",
            "elements": [{"type": "point_description", "text": matrix_blocks[0].get("body", "")[:500] if matrix_blocks else ""}],
        })

        result_slides.append({
            "slide_number": 2,
            "slide_role": "biggest_bet",
            "layout_index": spec_slides[1].get("layout_index", 37) if len(spec_slides) > 1 else 37,
            "title": bet_blocks[0].get("title", "The Biggest Bet") if bet_blocks else "The Biggest Bet",
            "elements": [{"type": "callout", "text": bet_blocks[0].get("body", "")[:300] if bet_blocks else ""}],
        })

        rec_text = "\n".join([b.get("body", "") for b in rec_blocks])[:800]
        result_slides.append({
            "slide_number": 3,
            "slide_role": "recommendations",
            "layout_index": spec_slides[2].get("layout_index", 1) if len(spec_slides) > 2 else 1,
            "title": "Recommended Actions by Team",
            "elements": [{"type": "point_description", "text": rec_text}],
        })

    else:  # theme_deep_dives
        per_theme = template_spec.get("per_theme_slide", {})
        theme_layout = per_theme.get("layout_index", 19)
        # Group blocks by theme
        themes: dict[str, list[dict[str, Any]]] = {}
        current_theme = ""
        for b in slide_blocks:
            if b.get("section_type", "").lower() == "theme_divider":
                current_theme = b.get("title", "").replace(" — Deep Dive", "").replace(" - Deep Dive", "").strip()
            if current_theme:
                themes.setdefault(current_theme, []).append(b)

        max_themes = template_spec.get("max_themes", 10)
        for idx, (theme_name, blocks) in enumerate(list(themes.items())[:max_themes], start=1):
            body_parts = [b.get("body", "")[:200] for b in blocks]
            result_slides.append({
                "slide_number": idx,
                "slide_role": "theme_card",
                "layout_index": theme_layout,
                "title": theme_name,
                "elements": [
                    {"type": "point_description", "text": t} for t in body_parts if t
                ] + [
                    {"type": "chart_placeholder", "chart_key": "friction_distribution", "position": "right"},
                ],
            })

    return {
        "section_key": section_key,
        "slides": result_slides,
    }


def _run_section_artifact_writer(
    state: AnalyticsState,
    narrative_result: dict[str, Any],
    section_blueprints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic artifact writer using section-based PPTX builder.

    Replaces the legacy _run_artifact_writer_node for the new pipeline.
    """
    from utils.pptx_builder import build_pptx_from_sections

    # 1. Generate charts deterministically
    dataviz_result = _build_deterministic_dataviz_output(state)
    dataviz_errors = _validate_dataviz(dataviz_result)
    if dataviz_errors:
        raise RuntimeError(f"Deterministic DataViz generation failed: {dataviz_errors}")

    # 2. Extract narrative markdown
    narrative_payload = narrative_result.get("narrative_output", {})
    narrative_markdown = str(
        narrative_payload.get("full_response", "") if isinstance(narrative_payload, dict) else ""
    ).strip()
    if not narrative_markdown:
        narrative_markdown = "# Analysis Report\n\nNo narrative markdown was generated."

    # 3. Build chart paths map
    dataviz_json = _extract_json(
        dataviz_result.get("dataviz_output", {}).get("full_response", "")
        if isinstance(dataviz_result.get("dataviz_output", {}), dict) else ""
    )
    chart_paths = _build_chart_paths_map(dataviz_json)

    # 4. Load template catalog for visual hierarchy
    try:
        catalog_path = Path(__file__).resolve().parent.parent / "data" / "input" / "template_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {}
    except Exception:
        catalog = {}

    visual_hierarchy = catalog.get("visual_hierarchy")

    # 5. Persist narrative markdown
    output_dir = _thread_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = str(output_dir / "complete_analysis.md")
    Path(markdown_path).write_text(narrative_markdown, encoding="utf-8")

    report_key = "report_markdown"
    data_store = cl.user_session.get("data_store")
    if data_store is not None:
        try:
            report_key = data_store.store_text(
                "report_markdown",
                narrative_markdown,
                {"agent": "narrative_agent", "type": "report_markdown"},
            )
        except Exception:
            report_key = "report_markdown"

    # 6. Build PPTX from section blueprints using new builder
    from config import PPTX_TEMPLATE_PATH
    pptx_path = str(output_dir / "report.pptx")
    template_path = PPTX_TEMPLATE_PATH if Path(PPTX_TEMPLATE_PATH).exists() else ""

    build_pptx_from_sections(
        section_blueprints=section_blueprints,
        chart_paths=chart_paths,
        output_path=pptx_path,
        template_path=template_path,
        visual_hierarchy=visual_hierarchy,
    )
    report_path = pptx_path if Path(pptx_path).exists() else ""
    logger.info("Section-based PPTX built: %s", report_path)

    # 7. Export filtered CSV
    csv_tool = TOOL_REGISTRY["export_filtered_csv"]
    csv_raw = csv_tool.invoke({})
    csv_data = _extract_json(str(csv_raw))
    data_path = _resolve_existing_path(str(csv_data.get("csv_path", "")).strip())

    payload = {
        "report_markdown_key": report_key,
        "markdown_file_path": markdown_path,
        "report_file_path": report_path,
        "data_file_path": data_path,
    }
    payload_json = json.dumps(payload, indent=2)
    logger.info("Section artifact writer completed: %s", payload)
    return {
        "messages": [AIMessage(content=payload_json)],
        "reasoning": [{
            "step_name": "Artifact Writer",
            "step_text": "Built PPTX from section blueprints, persisted narrative markdown, and exported filtered CSV.",
            "agent": "artifact_writer_node",
        }],
        "dataviz_output": dataviz_result.get("dataviz_output", {}),
        "report_markdown_key": report_key,
        "markdown_file_path": markdown_path,
        "report_file_path": report_path,
        "data_file_path": data_path,
    }


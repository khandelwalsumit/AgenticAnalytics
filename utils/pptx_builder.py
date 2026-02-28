"""Deterministic PPTX builder — section-aware, template-based.

Takes per-section JSON blueprints (from the formatting agent) + template.pptx +
chart images and produces the final report.pptx.

No LLM involved — placement, fonts, and structure are fully deterministic.

Section JSON contract (per section):
    {
        "section_key": "exec_summary" | "impact" | "theme_deep_dives",
        "slides": [
            {
                "slide_number": 1,
                "layout_index": 6,          # from template catalog
                "title": "...",
                "subtitle": "...",          # optional
                "elements": [
                    {"type": "h2", "text": "..."},
                    {"type": "bullet", "text": "...", "level": 1},
                    {"type": "bullet", "text": "...", "bold_label": "Impact:", "level": 1},
                    {"type": "table", "headers": [...], "rows": [...]},
                    {"type": "callout", "text": "..."},
                    {"type": "chart_placeholder", "chart_key": "friction_distribution"},
                ]
            }
        ]
    }
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn

logger = logging.getLogger("agenticanalytics.pptx_builder")


# ---------------------------------------------------------------------------
# Visual hierarchy defaults (overridden by template_catalog if available)
# ---------------------------------------------------------------------------

_DEFAULT_HIERARCHY = {
    "h1":             {"size": Pt(28), "bold": True,  "color": RGBColor(0x00, 0x3B, 0x70), "font": "Calibri"},
    "h2":             {"size": Pt(20), "bold": True,  "color": RGBColor(0x00, 0x3B, 0x70), "font": "Calibri"},
    "h3":             {"size": Pt(16), "bold": True,  "color": RGBColor(0x33, 0x33, 0x33), "font": "Calibri"},
    "point_heading":  {"size": Pt(14), "bold": True,  "color": RGBColor(0x33, 0x33, 0x33), "font": "Calibri"},
    "point_description": {"size": Pt(13), "bold": False, "color": RGBColor(0x33, 0x33, 0x33), "font": "Calibri"},
    "sub_point":      {"size": Pt(12), "bold": False, "color": RGBColor(0x66, 0x66, 0x66), "font": "Calibri"},
    "callout":        {"size": Pt(24), "bold": True,  "color": RGBColor(0x00, 0x6B, 0xA6), "font": "Calibri"},
    "table_header":   {"size": Pt(11), "bold": True,  "color": RGBColor(0xFF, 0xFF, 0xFF), "font": "Calibri"},
    "table_cell":     {"size": Pt(10), "bold": False, "color": RGBColor(0x33, 0x33, 0x33), "font": "Calibri"},
}

_HEADER_BG = RGBColor(0x00, 0x3B, 0x70)  # Dark blue for table header row
_ALT_ROW_BG = RGBColor(0xF2, 0xF2, 0xF2)  # Light grey for alternating rows


def _hex_to_rgb(hex_str: str) -> RGBColor:
    hex_str = hex_str.lstrip("#")
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


def _load_hierarchy(visual_hierarchy: dict[str, Any] | None) -> dict[str, Any]:
    """Merge catalog visual_hierarchy into runtime format."""
    if not visual_hierarchy:
        return _DEFAULT_HIERARCHY

    merged = dict(_DEFAULT_HIERARCHY)
    for key, spec in visual_hierarchy.items():
        if key in merged and isinstance(spec, dict):
            merged[key] = {
                "size": Pt(spec.get("font_size_pt", 13)),
                "bold": spec.get("bold", False),
                "color": _hex_to_rgb(spec.get("color_hex", "333333")),
                "font": spec.get("font_name", "Calibri"),
            }
    return merged


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------


def _strip_md(text: str) -> str:
    """Remove markdown bold/italic markers."""
    text = re.sub(r"\*\*\*(.*?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Element renderers
# ---------------------------------------------------------------------------


def _apply_font(run, style: dict[str, Any]) -> None:
    """Apply visual hierarchy style to a run."""
    run.font.size = style["size"]
    run.font.bold = style["bold"]
    run.font.color.rgb = style["color"]
    run.font.name = style["font"]


def _add_text_elements(tf, elements: list[dict[str, Any]], hierarchy: dict[str, Any]) -> None:
    """Render a list of text elements into a text frame."""
    tf.clear()
    first = True

    for elem in elements:
        etype = elem.get("type", "point_description")
        text = _strip_md(elem.get("text", ""))
        if not text and etype not in ("table", "chart_placeholder"):
            continue

        # Tables and charts handled separately
        if etype in ("table", "chart_placeholder"):
            continue

        # Get paragraph
        if first:
            p = tf.paragraphs[0]
            first = False
        else:
            p = tf.add_paragraph()

        # Determine style
        style_key = etype
        if style_key not in hierarchy:
            style_key = "point_description"
        style = hierarchy[style_key]

        # Handle bold_label + text pattern (e.g., "Impact:" prefix)
        bold_label = elem.get("bold_label", "")
        if bold_label:
            run_label = p.add_run()
            run_label.text = _strip_md(bold_label) + " "
            _apply_font(run_label, hierarchy.get("point_heading", style))
            run_body = p.add_run()
            run_body.text = text
            _apply_font(run_body, hierarchy.get("point_description", style))
        else:
            run = p.add_run()
            run.text = text
            _apply_font(run, style)

        # Indent level for bullets
        level = elem.get("level", 0)
        if level and level > 0:
            p.level = min(level - 1, 3)  # python-pptx levels are 0-indexed

        p.alignment = PP_ALIGN.LEFT


def _add_table_to_slide(
    slide,
    table_elem: dict[str, Any],
    hierarchy: dict[str, Any],
    left: float = 0.6,
    top: float = 2.2,
    width: float = 12.0,
    row_height: float = 0.35,
) -> None:
    """Add a formatted table to a slide."""
    headers = table_elem.get("headers", [])
    rows = table_elem.get("rows", [])
    if not headers:
        return

    num_rows = len(rows) + 1  # +1 for header
    num_cols = len(headers)

    col_width = width / num_cols
    table_height = row_height * num_rows

    tbl_shape = slide.shapes.add_table(
        num_rows, num_cols,
        Inches(left), Inches(top),
        Inches(width), Inches(table_height),
    )
    table = tbl_shape.table

    # Style header row
    header_style = hierarchy.get("table_header", _DEFAULT_HIERARCHY["table_header"])
    for col_idx, header_text in enumerate(headers):
        cell = table.cell(0, col_idx)
        cell.text = _strip_md(str(header_text))
        for p in cell.text_frame.paragraphs:
            p.alignment = PP_ALIGN.CENTER
            for run in p.runs:
                _apply_font(run, header_style)
        # Header background
        cell_fill = cell.fill
        cell_fill.solid()
        cell_fill.fore_color.rgb = _HEADER_BG

    # Style body rows
    cell_style = hierarchy.get("table_cell", _DEFAULT_HIERARCHY["table_cell"])
    for row_idx, row_data in enumerate(rows):
        for col_idx in range(num_cols):
            cell_text = _strip_md(str(row_data[col_idx])) if col_idx < len(row_data) else ""
            cell = table.cell(row_idx + 1, col_idx)
            cell.text = cell_text
            for p in cell.text_frame.paragraphs:
                p.alignment = PP_ALIGN.LEFT
                for run in p.runs:
                    _apply_font(run, cell_style)
            # Alternating row background
            if row_idx % 2 == 1:
                cell_fill = cell.fill
                cell_fill.solid()
                cell_fill.fore_color.rgb = _ALT_ROW_BG

    # Set column widths proportionally (first column wider for labels)
    if num_cols > 1:
        first_col_pct = 0.25
        remaining_pct = (1.0 - first_col_pct) / (num_cols - 1)
        table.columns[0].width = Inches(width * first_col_pct)
        for i in range(1, num_cols):
            table.columns[i].width = Inches(width * remaining_pct)


def _add_chart_image(
    slide,
    chart_key: str,
    chart_paths: dict[str, str],
    position: str = "right",
) -> None:
    """Embed a chart image on the slide if available."""
    # Normalize chart key: strip {{chart.xxx}} wrapper
    clean_key = chart_key
    m = re.search(r"\{\{\s*chart\.([a-zA-Z0-9_-]+)\s*\}\}", chart_key)
    if m:
        clean_key = m.group(1)

    chart_path = chart_paths.get(clean_key, "")
    if not chart_path or not Path(chart_path).exists():
        return

    # Position based on slide layout
    if position == "right":
        left, top, width = Inches(8.0), Inches(1.8), Inches(4.8)
    elif position == "left":
        left, top, width = Inches(0.6), Inches(1.8), Inches(4.8)
    elif position == "bottom":
        left, top, width = Inches(0.6), Inches(4.5), Inches(11.5)
    elif position == "full":
        left, top, width = Inches(0.6), Inches(1.8), Inches(11.5)
    else:
        left, top, width = Inches(8.0), Inches(1.8), Inches(4.8)

    slide.shapes.add_picture(str(chart_path), left, top, width=width)


# ---------------------------------------------------------------------------
# Slide builders — one per slide type
# ---------------------------------------------------------------------------


def _build_title_slide(prs: Presentation, slide_data: dict, hierarchy: dict, layout_idx: int) -> None:
    """Title slide: hook assertion + subtitle."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))
    subtitle_text = _strip_md(slide_data.get("subtitle", ""))

    # Set title
    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    # Set subtitle in first non-title placeholder
    if subtitle_text:
        for ph in slide.placeholders:
            if ph.placeholder_format.type in (4,):  # SUBTITLE
                ph.text = subtitle_text
                for p in ph.text_frame.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(18)
                        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
                break


def _build_content_slide(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
    chart_paths: dict[str, str],
) -> None:
    """Standard content slide: title + elements in body placeholder."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))
    elements = slide_data.get("elements", [])

    # Title
    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    # Body elements — find content placeholder
    body_ph = None
    for ph in slide.placeholders:
        if ph.placeholder_format.type in (2, 7):  # BODY or OBJECT
            body_ph = ph
            break

    if body_ph and elements:
        text_elements = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elements, hierarchy)

    # Tables — rendered as shapes directly on the slide
    for elem in elements:
        if elem.get("type") == "table":
            _add_table_to_slide(slide, elem, hierarchy)

    # Charts — embedded as images
    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            _add_chart_image(slide, elem.get("chart_key", ""), chart_paths,
                             position=elem.get("position", "right"))


def _build_table_slide(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
) -> None:
    """Table-focused slide: title + full-width table."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))

    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    # Find first table element
    for elem in slide_data.get("elements", []):
        if elem.get("type") == "table":
            _add_table_to_slide(slide, elem, hierarchy, left=0.4, top=2.0, width=12.5)
            break


def _build_callout_slide(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
) -> None:
    """Big stat / callout slide: prominent number or assertion."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))

    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    # The callout text goes in the OBJECT placeholder (usually idx=13)
    for ph in slide.placeholders:
        if ph.placeholder_format.type in (2, 7):  # BODY or OBJECT
            elements = slide_data.get("elements", [])
            if elements:
                _add_text_elements(ph.text_frame, elements, hierarchy)
            break


def _build_theme_card_slide(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
    chart_paths: dict[str, str],
) -> None:
    """Theme deep dive card: text left + chart right."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))
    elements = slide_data.get("elements", [])

    # Title
    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    # Body — OBJECT placeholder for text content
    body_ph = None
    pic_ph = None
    for ph in slide.placeholders:
        ph_type = ph.placeholder_format.type
        if ph_type in (2, 7) and body_ph is None:  # BODY or OBJECT
            body_ph = ph
        if ph_type == 18 and pic_ph is None:  # PICTURE
            pic_ph = ph

    if body_ph:
        text_elements = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elements, hierarchy)

    # Chart in picture placeholder or fallback to manual placement
    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            chart_key = elem.get("chart_key", "")
            clean_key = chart_key
            m = re.search(r"\{\{\s*chart\.([a-zA-Z0-9_-]+)\s*\}\}", chart_key)
            if m:
                clean_key = m.group(1)
            chart_path = chart_paths.get(clean_key, "")
            if chart_path and Path(chart_path).exists():
                if pic_ph is not None:
                    pic_ph.insert_picture(str(chart_path))
                else:
                    _add_chart_image(slide, chart_key, chart_paths, position="right")
            break


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_pptx_from_sections(
    section_blueprints: list[dict[str, Any]],
    chart_paths: dict[str, str],
    output_path: str,
    template_path: str = "",
    visual_hierarchy: dict[str, Any] | None = None,
) -> str:
    """Build a PPTX from per-section formatting blueprints.

    Args:
        section_blueprints: List of section dicts, each with ``section_key`` and ``slides``.
            Ordered: exec_summary, impact, theme_deep_dives.
        chart_paths: Map of chart_key -> image file path.
        output_path: Where to save the .pptx.
        template_path: Path to .pptx template file (uses blank if not found).
        visual_hierarchy: Optional visual hierarchy from template catalog.

    Returns:
        The output path.
    """
    if template_path and Path(template_path).exists():
        prs = Presentation(template_path)
    else:
        prs = Presentation()

    # Widescreen 16:9
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    hierarchy = _load_hierarchy(visual_hierarchy)
    num_layouts = len(prs.slide_layouts)

    for section in section_blueprints:
        section_key = section.get("section_key", "")
        slides = section.get("slides", [])

        for slide_data in slides:
            layout_idx = slide_data.get("layout_index", 1)
            if layout_idx >= num_layouts:
                layout_idx = 1  # fallback to "Content"

            slide_role = slide_data.get("slide_role", "content")

            if slide_role == "hook":
                _build_title_slide(prs, slide_data, hierarchy, layout_idx)
            elif slide_role == "impact_matrix":
                _build_table_slide(prs, slide_data, hierarchy, layout_idx)
            elif slide_role in ("biggest_bet", "callout"):
                _build_callout_slide(prs, slide_data, hierarchy, layout_idx)
            elif slide_role == "theme_card":
                _build_theme_card_slide(prs, slide_data, hierarchy, layout_idx, chart_paths)
            else:
                _build_content_slide(prs, slide_data, hierarchy, layout_idx, chart_paths)

    prs.save(output_path)
    logger.info("PPTX built: %d slides -> %s", sum(len(s.get("slides", [])) for s in section_blueprints), output_path)
    return output_path

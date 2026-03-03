"""Deterministic PPTX builder — section-aware, template-based.

Takes per-section JSON blueprints (from the formatting agent) + template.pptx +
chart images and produces the final report.pptx.

No LLM involved — placement, fonts, and structure are fully deterministic.

Supports two JSON contracts:
  1. **Structured (new)**: typed fields per slide_role (stats_bar, left_column,
     right_column, cards, dimensions, etc.)
  2. **Legacy**: flat `elements` arrays for backward compatibility
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
# Visual design constants
# ---------------------------------------------------------------------------

# Color palette
COLOR_PRIMARY = RGBColor(0x00, 0x3B, 0x70)    # Navy — titles, headers, dark bg
COLOR_SECONDARY = RGBColor(0x00, 0x6B, 0xA6)  # Blue — accent, callout stats
COLOR_LIGHT_BG = RGBColor(0xF5, 0xF7, 0xFA)   # Off-white — content backgrounds
COLOR_DARK_BG = RGBColor(0x00, 0x3B, 0x70)     # Navy — hook, biggest bet
COLOR_TEXT = RGBColor(0x33, 0x33, 0x33)         # Body text
COLOR_MUTED = RGBColor(0x88, 0x88, 0x88)       # Stats bar, secondary info
COLOR_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
COLOR_RED = RGBColor(0xC0, 0x39, 0x2B)         # High-priority
COLOR_AMBER = RGBColor(0xE6, 0x7E, 0x22)       # Medium-priority
COLOR_GREEN = RGBColor(0x27, 0xAE, 0x60)       # Low-effort / quick-win

_HEADER_BG = COLOR_PRIMARY
_ALT_ROW_BG = RGBColor(0xF5, 0xF7, 0xFA)


# ---------------------------------------------------------------------------
# Visual hierarchy defaults (overridden by template_catalog if available)
# ---------------------------------------------------------------------------

_DEFAULT_HIERARCHY = {
    "h1":             {"size": Pt(28), "bold": True,  "color": COLOR_PRIMARY, "font": "Calibri"},
    "h2":             {"size": Pt(20), "bold": True,  "color": COLOR_PRIMARY, "font": "Calibri"},
    "h3":             {"size": Pt(16), "bold": True,  "color": COLOR_TEXT, "font": "Calibri"},
    "point_heading":  {"size": Pt(14), "bold": True,  "color": COLOR_TEXT, "font": "Calibri"},
    "point_description": {"size": Pt(13), "bold": False, "color": COLOR_TEXT, "font": "Calibri"},
    "sub_point":      {"size": Pt(12), "bold": False, "color": RGBColor(0x66, 0x66, 0x66), "font": "Calibri"},
    "callout":        {"size": Pt(24), "bold": True,  "color": COLOR_SECONDARY, "font": "Calibri"},
    "big_stat":       {"size": Pt(60), "bold": True,  "color": COLOR_WHITE, "font": "Calibri"},
    "stats_bar":      {"size": Pt(11), "bold": False, "color": COLOR_MUTED, "font": "Calibri"},
    "table_header":   {"size": Pt(11), "bold": True,  "color": COLOR_WHITE, "font": "Calibri"},
    "table_cell":     {"size": Pt(10), "bold": False, "color": COLOR_TEXT, "font": "Calibri"},
}


def _hex_to_rgb(hex_str: str) -> RGBColor:
    hex_str = hex_str.lstrip("#")
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


def _load_hierarchy(visual_hierarchy: dict[str, Any] | None) -> dict[str, Any]:
    """Merge catalog visual_hierarchy into runtime format."""
    if not visual_hierarchy:
        return dict(_DEFAULT_HIERARCHY)

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
# Utility helpers
# ---------------------------------------------------------------------------


def _strip_md(text: str) -> str:
    """Remove markdown bold/italic markers."""
    text = re.sub(r"\*\*\*(.*?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text.strip()


def _apply_font(run, style: dict[str, Any]) -> None:
    """Apply visual hierarchy style to a run."""
    run.font.size = style["size"]
    run.font.bold = style["bold"]
    run.font.color.rgb = style["color"]
    run.font.name = style["font"]


def _set_slide_bg(slide, color: RGBColor) -> None:
    """Set solid background color for a slide."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(slide, left, top, width, height, text, style, alignment=PP_ALIGN.LEFT, word_wrap=True):
    """Add a styled textbox to a slide. Returns the shape."""
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = word_wrap
    p = tf.paragraphs[0]
    p.alignment = alignment
    run = p.add_run()
    run.text = _strip_md(str(text))
    _apply_font(run, style)
    return txBox


def _add_separator_line(slide, left, top, width, color=COLOR_WHITE, opacity=0.5):
    """Add a thin horizontal line to a slide."""
    from pptx.util import Inches as _In, Pt as _Pt
    connector = slide.shapes.add_connector(
        1,  # MSO_CONNECTOR_TYPE.STRAIGHT
        _In(left), _In(top),
        _In(left + width), _In(top),
    )
    connector.line.color.rgb = color
    connector.line.width = _Pt(1)


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------


def _add_table_to_slide(
    slide,
    headers: list,
    rows: list,
    hierarchy: dict[str, Any],
    left: float = 0.6,
    top: float = 2.2,
    width: float = 12.0,
    row_height: float = 0.35,
) -> None:
    """Add a formatted table to a slide."""
    if not headers:
        return

    num_rows = len(rows) + 1
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

    # First column wider for labels
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
    clean_key = chart_key
    m = re.search(r"\{\{\s*chart\.([a-zA-Z0-9_-]+)\s*\}\}", chart_key)
    if m:
        clean_key = m.group(1)

    chart_path = chart_paths.get(clean_key, "")
    if not chart_path or not Path(chart_path).exists():
        return

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
# Legacy element renderer (backward compatibility)
# ---------------------------------------------------------------------------


def _add_text_elements(tf, elements: list[dict[str, Any]], hierarchy: dict[str, Any]) -> None:
    """Render a list of text elements into a text frame."""
    tf.clear()
    first = True

    for elem in elements:
        etype = elem.get("type", "point_description")
        text = _strip_md(elem.get("text", ""))
        if not text and etype not in ("table", "chart_placeholder"):
            continue

        if etype in ("table", "chart_placeholder"):
            continue

        if first:
            p = tf.paragraphs[0]
            first = False
        else:
            p = tf.add_paragraph()

        style_key = etype
        if style_key not in hierarchy:
            style_key = "point_description"
        style = hierarchy[style_key]

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

        level = elem.get("level", 0)
        if level and level > 0:
            p.level = min(level - 1, 3)

        p.alignment = PP_ALIGN.LEFT


# ═══════════════════════════════════════════════════════════════════════════
# Slide type renderers — one per slide_role
# ═══════════════════════════════════════════════════════════════════════════


def _render_hook(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
) -> None:
    """Hook slide: dark bg, centered white title 36pt, separator, gray subtitle 14pt."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)
    _set_slide_bg(slide, COLOR_DARK_BG)

    title_text = _strip_md(slide_data.get("title", ""))
    subtitle_text = _strip_md(slide_data.get("subtitle", ""))

    # Large white centered title
    _add_textbox(
        slide, left=1.0, top=2.0, width=11.33, height=1.5,
        text=title_text,
        style={"size": Pt(36), "bold": True, "color": COLOR_WHITE, "font": "Calibri"},
        alignment=PP_ALIGN.CENTER,
    )

    # Thin horizontal separator
    _add_separator_line(slide, left=3.0, top=3.8, width=7.33, color=COLOR_WHITE)

    # Gray subtitle below
    if subtitle_text:
        _add_textbox(
            slide, left=1.5, top=4.2, width=10.33, height=1.0,
            text=subtitle_text,
            style={"size": Pt(14), "bold": False, "color": COLOR_MUTED, "font": "Calibri"},
            alignment=PP_ALIGN.CENTER,
        )


def _render_pain_point_cards(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
) -> None:
    """Pain points: 3-column card layout with accent bars."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "Key Pain Points"))

    # Title
    _add_textbox(
        slide, left=0.6, top=0.4, width=12.0, height=0.7,
        text=title_text,
        style=hierarchy.get("h1", _DEFAULT_HIERARCHY["h1"]),
    )

    cards = slide_data.get("cards", [])
    if not cards:
        # Fallback to elements-based rendering
        return

    # Priority colors for accent bars
    accent_colors = [COLOR_RED, COLOR_AMBER, COLOR_SECONDARY]
    card_width = 3.8
    card_gap = 0.3
    start_left = 0.6

    for i, card in enumerate(cards[:3]):
        card_left = start_left + i * (card_width + card_gap)
        card_top = 1.4

        # Accent bar (left edge)
        accent_color = accent_colors[i % len(accent_colors)]
        bar = slide.shapes.add_shape(
            1,  # MSO_SHAPE.RECTANGLE
            Inches(card_left), Inches(card_top),
            Inches(0.08), Inches(5.2),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent_color
        bar.line.fill.background()

        # Card background
        card_bg = slide.shapes.add_shape(
            1,
            Inches(card_left + 0.08), Inches(card_top),
            Inches(card_width - 0.08), Inches(5.2),
        )
        card_bg.fill.solid()
        card_bg.fill.fore_color.rgb = COLOR_LIGHT_BG
        card_bg.line.fill.background()

        # Card content
        content_left = card_left + 0.25
        content_width = card_width - 0.4
        y = card_top + 0.2

        # Pain point name
        name = _strip_md(str(card.get("name", f"Pain Point {i+1}")))
        _add_textbox(slide, content_left, y, content_width, 0.4, name,
                     {"size": Pt(16), "bold": True, "color": COLOR_TEXT, "font": "Calibri"})
        y += 0.5

        # Call count + % badge
        calls = card.get("calls", 0)
        pct = card.get("pct", "")
        priority = card.get("priority", 0)
        badge_text = f"{calls} calls | {pct} | Priority: {priority}"
        _add_textbox(slide, content_left, y, content_width, 0.3, badge_text,
                     {"size": Pt(10), "bold": False, "color": COLOR_MUTED, "font": "Calibri"})
        y += 0.5

        # Issue label + description
        _add_textbox(slide, content_left, y, content_width, 0.25, "Issue:",
                     {"size": Pt(12), "bold": True, "color": COLOR_TEXT, "font": "Calibri"})
        y += 0.3
        issue = _strip_md(str(card.get("issue", "")))
        _add_textbox(slide, content_left, y, content_width, 1.0, issue,
                     {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 1.2

        # Fix label + description
        _add_textbox(slide, content_left, y, content_width, 0.25, "Fix:",
                     {"size": Pt(12), "bold": True, "color": COLOR_GREEN, "font": "Calibri"})
        y += 0.3
        fix = _strip_md(str(card.get("fix", "")))
        _add_textbox(slide, content_left, y, content_width, 1.0, fix,
                     {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 1.2

        # Owner tag at bottom
        owner = card.get("owner", "")
        if owner:
            _add_textbox(slide, content_left, y, content_width, 0.3, owner,
                         {"size": Pt(10), "bold": True, "color": accent_color, "font": "Calibri"})


def _render_impact_matrix(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
    chart_paths: dict[str, str],
) -> None:
    """Impact matrix: styled table LEFT, chart RIGHT."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "Impact vs. Ease Analysis"))

    # Title
    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    # Table — from top-level `table` field or legacy `elements`
    table_data = slide_data.get("table", {})
    if not table_data:
        # Legacy: look in elements
        for elem in slide_data.get("elements", []):
            if elem.get("type") == "table":
                table_data = elem
                break

    chart_placeholder = slide_data.get("chart_placeholder", {})
    if not chart_placeholder:
        for elem in slide_data.get("elements", []):
            if elem.get("type") == "chart_placeholder":
                chart_placeholder = elem
                break

    has_chart = bool(chart_placeholder) and bool(chart_paths)

    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])

    if headers:
        table_width = 7.0 if has_chart else 12.5
        _add_table_to_slide(
            slide, headers, rows, hierarchy,
            left=0.4, top=2.0, width=table_width, row_height=0.30,
        )

    if chart_placeholder:
        _add_chart_image(
            slide, chart_placeholder.get("chart_key", "impact_ease_scatter"),
            chart_paths, position=chart_placeholder.get("position", "right"),
        )


def _render_biggest_bet(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
) -> None:
    """Biggest bet: dark bg, large stat, accent theme name, context narrative."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)
    _set_slide_bg(slide, COLOR_DARK_BG)

    theme_name = _strip_md(slide_data.get("theme_name", ""))
    stat_number = _strip_md(slide_data.get("stat_number", ""))
    stat_pct = _strip_md(slide_data.get("stat_pct", ""))
    narrative = _strip_md(slide_data.get("narrative", ""))

    # Fallback for legacy format
    if not stat_number and slide_data.get("title"):
        stat_number = _strip_md(slide_data.get("title", ""))
    if not narrative:
        for elem in slide_data.get("elements", []):
            if elem.get("type") in ("callout", "point_description"):
                narrative = _strip_md(elem.get("text", ""))
                break

    # Big number (60pt, white, centered)
    _add_textbox(
        slide, left=2.0, top=1.5, width=9.33, height=1.5,
        text=stat_number,
        style=hierarchy.get("big_stat", _DEFAULT_HIERARCHY["big_stat"]),
        alignment=PP_ALIGN.CENTER,
    )

    # Theme name in accent color
    if theme_name:
        _add_textbox(
            slide, left=2.0, top=3.2, width=9.33, height=0.7,
            text=theme_name,
            style={"size": Pt(20), "bold": True, "color": COLOR_SECONDARY, "font": "Calibri"},
            alignment=PP_ALIGN.CENTER,
        )

    # Narrative context below
    if narrative:
        _add_textbox(
            slide, left=2.0, top=4.2, width=9.33, height=1.5,
            text=narrative,
            style={"size": Pt(16), "bold": False, "color": COLOR_WHITE, "font": "Calibri"},
            alignment=PP_ALIGN.CENTER,
        )


def _render_recommendations(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
) -> None:
    """Recommendations: 2x2 card grid with per-dimension accent colors."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "Recommended Actions by Owning Team"))

    # Title
    _add_textbox(
        slide, left=0.6, top=0.4, width=12.0, height=0.7,
        text=title_text,
        style=hierarchy.get("h1", _DEFAULT_HIERARCHY["h1"]),
    )

    dimensions = slide_data.get("dimensions", [])
    if not dimensions:
        # Fallback to legacy elements rendering
        _render_legacy_content(prs, slide, slide_data, hierarchy, {})
        return

    # Default accent colors for each dimension
    default_colors = {
        "Digital / UX": "006BA6",
        "Digital/UX": "006BA6",
        "Operations": "2C5F2D",
        "Communications": "E67E22",
        "Policy": "8E44AD",
    }

    # 2x2 grid layout
    positions = [
        (0.6, 1.6),   # top-left
        (6.8, 1.6),   # top-right
        (0.6, 4.4),   # bottom-left
        (6.8, 4.4),   # bottom-right
    ]
    card_width = 5.8
    card_height = 2.5

    for i, dim in enumerate(dimensions[:4]):
        if i >= len(positions):
            break

        card_left, card_top = positions[i]
        dim_name = str(dim.get("name", f"Dimension {i+1}"))
        accent_hex = dim.get("accent_color", default_colors.get(dim_name, "006BA6"))
        accent_color = _hex_to_rgb(accent_hex)

        # Colored square icon + dimension name
        icon = slide.shapes.add_shape(
            1,  # MSO_SHAPE.RECTANGLE
            Inches(card_left), Inches(card_top),
            Inches(0.25), Inches(0.25),
        )
        icon.fill.solid()
        icon.fill.fore_color.rgb = accent_color
        icon.line.fill.background()

        _add_textbox(
            slide, card_left + 0.35, card_top - 0.05, card_width - 0.35, 0.35,
            dim_name,
            {"size": Pt(14), "bold": True, "color": COLOR_TEXT, "font": "Calibri"},
        )

        # Actions as bullet-like items
        y = card_top + 0.45
        actions = dim.get("actions", [])
        for action in actions[:2]:
            action_title = _strip_md(str(action.get("title", "")))
            action_detail = _strip_md(str(action.get("detail", "")))
            calls = action.get("calls", 0)

            # Action title (bold)
            txBox = slide.shapes.add_textbox(
                Inches(card_left + 0.3), Inches(y),
                Inches(card_width - 0.3), Inches(0.7),
            )
            tf = txBox.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]

            # Bullet marker
            bullet_run = p.add_run()
            bullet_run.text = "• "
            _apply_font(bullet_run, {"size": Pt(12), "bold": True, "color": accent_color, "font": "Calibri"})

            # Title
            title_run = p.add_run()
            title_run.text = action_title
            _apply_font(title_run, {"size": Pt(12), "bold": True, "color": COLOR_TEXT, "font": "Calibri"})

            # Detail on next line
            if action_detail:
                detail_p = tf.add_paragraph()
                detail_run = detail_p.add_run()
                detail_text = f"   → {action_detail}"
                if calls:
                    detail_text += f" ({calls} calls)"
                detail_run.text = detail_text
                _apply_font(detail_run, {"size": Pt(10), "bold": False, "color": COLOR_MUTED, "font": "Calibri"})

            y += 0.9


def _render_theme_card(
    prs: Presentation,
    slide_data: dict,
    hierarchy: dict,
    layout_idx: int,
    chart_paths: dict[str, str],
) -> None:
    """Theme card: stats bar, left narrative column (60%), right driver table (40%)."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))
    stats_bar = slide_data.get("stats_bar", {})
    left_column = slide_data.get("left_column", {})
    right_column = slide_data.get("right_column", {})

    # If no structured fields, fall back to legacy
    if not stats_bar and not left_column and not right_column:
        _render_legacy_theme_card(prs, slide, slide_data, hierarchy, chart_paths)
        return

    # Title (24pt, bold)
    _add_textbox(
        slide, left=0.5, top=0.3, width=12.0, height=0.6,
        text=title_text,
        style={"size": Pt(24), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"},
    )

    # Stats bar (11pt, muted gray)
    if stats_bar:
        calls = stats_bar.get("calls", 0)
        pct = stats_bar.get("pct", "")
        impact = stats_bar.get("impact", 0)
        ease = stats_bar.get("ease", 0)
        priority = stats_bar.get("priority", 0)
        stats_text = f"Calls: {calls} | {pct} | Impact: {impact} | Ease: {ease} | Priority: {priority}"
        _add_textbox(
            slide, left=0.5, top=0.95, width=12.0, height=0.3,
            text=stats_text,
            style=hierarchy.get("stats_bar", _DEFAULT_HIERARCHY["stats_bar"]),
        )

    # LEFT COLUMN (60%) — core issue, primary driver, solutions
    left_x = 0.5
    left_width = 7.2
    y = 1.5

    if left_column:
        # Core Issue heading
        _add_textbox(slide, left_x, y, left_width, 0.3, "CORE ISSUE",
                     {"size": Pt(13), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"})
        y += 0.35
        core_issue = _strip_md(str(left_column.get("core_issue", "")))
        if core_issue:
            _add_textbox(slide, left_x, y, left_width, 1.0, core_issue,
                         {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 1.1

        # Primary Driver heading
        _add_textbox(slide, left_x, y, left_width, 0.3, "PRIMARY DRIVER",
                     {"size": Pt(13), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"})
        y += 0.35
        primary_driver = _strip_md(str(left_column.get("primary_driver", "")))
        if primary_driver:
            _add_textbox(slide, left_x, y, left_width, 0.8, primary_driver,
                         {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 0.9

        # Solutions heading
        solutions = left_column.get("solutions", [])
        if solutions:
            _add_textbox(slide, left_x, y, left_width, 0.3, "SOLUTIONS",
                         {"size": Pt(13), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"})
            y += 0.35

            for idx, sol in enumerate(solutions[:3], start=1):
                action = _strip_md(str(sol.get("action", "")))
                dimension = sol.get("dimension", "")
                sol_text = f"{idx}. {action}"
                if dimension:
                    sol_text += f" [{dimension}]"
                _add_textbox(slide, left_x, y, left_width, 0.3, sol_text,
                             {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
                y += 0.35

    # RIGHT COLUMN (40%) — driver table
    right_x = 8.0
    right_width = 5.0
    right_top = 1.5

    if right_column:
        headers = right_column.get("headers", ["Driver", "Calls"])
        rows = right_column.get("rows", [])
        if headers and rows:
            _add_table_to_slide(
                slide, headers, rows, hierarchy,
                left=right_x, top=right_top, width=right_width, row_height=0.28,
            )


def _render_legacy_theme_card(
    prs: Presentation,
    slide,
    slide_data: dict,
    hierarchy: dict,
    chart_paths: dict[str, str],
) -> None:
    """Legacy theme card rendering using elements array."""
    elements = slide_data.get("elements", [])

    title_text = _strip_md(slide_data.get("title", ""))
    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    body_ph = None
    for ph in slide.placeholders:
        if ph.placeholder_format.type in (2, 7):
            body_ph = ph
            break

    if body_ph:
        text_elements = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elements, hierarchy)

    # Tables
    table_elements = [e for e in elements if e.get("type") == "table"]
    for t_elem in table_elements:
        _add_table_to_slide(
            slide, t_elem.get("headers", []), t_elem.get("rows", []), hierarchy,
            left=0.6, top=4.0, width=7.5, row_height=0.30,
        )

    # Charts
    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            _add_chart_image(slide, elem.get("chart_key", ""), chart_paths,
                             position=elem.get("position", "right"))
            break


def _render_legacy_content(
    prs: Presentation,
    slide,
    slide_data: dict,
    hierarchy: dict,
    chart_paths: dict[str, str],
) -> None:
    """Legacy content rendering using elements array."""
    elements = slide_data.get("elements", [])

    body_ph = None
    for ph in slide.placeholders:
        if ph.placeholder_format.type in (2, 7):
            body_ph = ph
            break

    if body_ph and elements:
        text_elements = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elements, hierarchy)

    for elem in elements:
        if elem.get("type") == "table":
            _add_table_to_slide(
                slide, elem.get("headers", []), elem.get("rows", []), hierarchy,
            )

    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            _add_chart_image(slide, elem.get("chart_key", ""), chart_paths,
                             position=elem.get("position", "right"))


# ---------------------------------------------------------------------------
# Generic slide builders (for legacy/fallback)
# ---------------------------------------------------------------------------


def _build_title_slide(prs: Presentation, slide_data: dict, hierarchy: dict, layout_idx: int) -> None:
    """Title slide: hook assertion + subtitle."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))
    subtitle_text = _strip_md(slide_data.get("subtitle", ""))

    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    if subtitle_text:
        for ph in slide.placeholders:
            if ph.placeholder_format.type in (4,):
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

    if slide.shapes.title:
        slide.shapes.title.text = title_text
        for p in slide.shapes.title.text_frame.paragraphs:
            for run in p.runs:
                _apply_font(run, hierarchy["h1"])

    body_ph = None
    for ph in slide.placeholders:
        if ph.placeholder_format.type in (2, 7):
            body_ph = ph
            break

    if body_ph and elements:
        text_elements = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elements, hierarchy)

    for elem in elements:
        if elem.get("type") == "table":
            _add_table_to_slide(
                slide, elem.get("headers", []), elem.get("rows", []), hierarchy,
            )

    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            _add_chart_image(slide, elem.get("chart_key", ""), chart_paths,
                             position=elem.get("position", "right"))


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

    for ph in slide.placeholders:
        if ph.placeholder_format.type in (2, 7):
            elements = slide_data.get("elements", [])
            if elements:
                _add_text_elements(ph.text_frame, elements, hierarchy)
            break


# ---------------------------------------------------------------------------
# Slide role dispatcher
# ---------------------------------------------------------------------------

# Map slide_role -> whether it uses structured fields (new) or legacy elements
_STRUCTURED_ROLES = {"hook", "pain_points", "impact_matrix", "biggest_bet", "recommendations", "theme_card"}


def _has_structured_fields(slide_data: dict) -> bool:
    """Check if slide_data uses the new structured JSON contract."""
    role = slide_data.get("slide_role", "")
    if role not in _STRUCTURED_ROLES:
        return False
    # Check for presence of typed fields
    if role == "hook":
        return True  # always structured (title + subtitle)
    if role == "pain_points":
        return bool(slide_data.get("cards"))
    if role == "impact_matrix":
        return bool(slide_data.get("table")) or bool(slide_data.get("chart_placeholder"))
    if role == "biggest_bet":
        return bool(slide_data.get("stat_number") or slide_data.get("theme_name"))
    if role == "recommendations":
        return bool(slide_data.get("dimensions"))
    if role == "theme_card":
        return bool(slide_data.get("stats_bar") or slide_data.get("left_column") or slide_data.get("right_column"))
    return False


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
                layout_idx = 1

            slide_role = slide_data.get("slide_role", "content")

            # Dispatch to structured renderers first, then legacy
            if slide_role == "hook":
                _render_hook(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "pain_points" and _has_structured_fields(slide_data):
                _render_pain_point_cards(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "impact_matrix":
                _render_impact_matrix(prs, slide_data, hierarchy, layout_idx, chart_paths)

            elif slide_role == "biggest_bet":
                if _has_structured_fields(slide_data):
                    _render_biggest_bet(prs, slide_data, hierarchy, layout_idx)
                else:
                    _build_callout_slide(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "recommendations" and _has_structured_fields(slide_data):
                _render_recommendations(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "theme_card":
                _render_theme_card(prs, slide_data, hierarchy, layout_idx, chart_paths)

            elif slide_role in ("hook_and_quick_wins", "pain_points", "recommendations",
                                "quick_wins", "situation_and_pain_points"):
                _build_content_slide(prs, slide_data, hierarchy, layout_idx, chart_paths)

            elif slide_role == "callout":
                _build_callout_slide(prs, slide_data, hierarchy, layout_idx)

            else:
                _build_content_slide(prs, slide_data, hierarchy, layout_idx, chart_paths)

    prs.save(output_path)
    logger.info("PPTX built: %d slides -> %s", sum(len(s.get("slides", [])) for s in section_blueprints), output_path)
    return output_path

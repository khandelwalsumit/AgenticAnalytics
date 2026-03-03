"""Deterministic PPTX builder — section-aware, template-based.

Takes per-section JSON blueprints (from the formatting agent) + template.pptx +
chart images and produces the final report.pptx.

No LLM involved — placement, fonts, and structure are fully deterministic.

Slide types supported:
  1. executive_summary — title + subtitle + quick wins
  2. pain_points — 3-column card layout
  3. impact_matrix — theme card list LEFT + scatter chart RIGHT
  4. low_hanging_fruit — 3 easiest solutions
  5. recommendations — 2x2 dimension grid
  6. theme_card — stats bar + two-column narrative/table
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

logger = logging.getLogger("agenticanalytics.pptx_builder")


# ---------------------------------------------------------------------------
# Visual design constants
# ---------------------------------------------------------------------------

COLOR_PRIMARY = RGBColor(0x00, 0x3B, 0x70)    # Navy
COLOR_SECONDARY = RGBColor(0x00, 0x6B, 0xA6)  # Blue accent
COLOR_LIGHT_BG = RGBColor(0xF5, 0xF7, 0xFA)   # Off-white
COLOR_TEXT = RGBColor(0x33, 0x33, 0x33)         # Body text
COLOR_MUTED = RGBColor(0x88, 0x88, 0x88)       # Stats, secondary
COLOR_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
COLOR_RED = RGBColor(0xC0, 0x39, 0x2B)
COLOR_AMBER = RGBColor(0xE6, 0x7E, 0x22)
COLOR_GREEN = RGBColor(0x27, 0xAE, 0x60)

_HEADER_BG = COLOR_PRIMARY
_ALT_ROW_BG = RGBColor(0xF5, 0xF7, 0xFA)


# ---------------------------------------------------------------------------
# Visual hierarchy defaults
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
    text = re.sub(r"\*\*\*(.*?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text.strip()


def _apply_font(run, style: dict[str, Any]) -> None:
    run.font.size = style["size"]
    run.font.bold = style["bold"]
    run.font.color.rgb = style["color"]
    run.font.name = style["font"]


def _set_slide_bg(slide, color: RGBColor) -> None:
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(slide, left, top, width, height, text, style,
                 alignment=PP_ALIGN.LEFT, word_wrap=True):
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top),
                                     Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = word_wrap
    p = tf.paragraphs[0]
    p.alignment = alignment
    run = p.add_run()
    run.text = _strip_md(str(text))
    _apply_font(run, style)
    return txBox


def _add_separator_line(slide, left, top, width, color=COLOR_MUTED):
    connector = slide.shapes.add_connector(
        1, Inches(left), Inches(top), Inches(left + width), Inches(top),
    )
    connector.line.color.rgb = color
    connector.line.width = Pt(0.75)


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------


def _add_table_to_slide(slide, headers, rows, hierarchy,
                        left=0.6, top=2.2, width=12.0, row_height=0.35):
    if not headers:
        return

    num_rows = len(rows) + 1
    num_cols = len(headers)
    table_height = row_height * num_rows

    tbl_shape = slide.shapes.add_table(
        num_rows, num_cols,
        Inches(left), Inches(top), Inches(width), Inches(table_height),
    )
    table = tbl_shape.table

    header_style = hierarchy.get("table_header", _DEFAULT_HIERARCHY["table_header"])
    for col_idx, header_text in enumerate(headers):
        cell = table.cell(0, col_idx)
        cell.text = _strip_md(str(header_text))
        for p in cell.text_frame.paragraphs:
            p.alignment = PP_ALIGN.CENTER
            for run in p.runs:
                _apply_font(run, header_style)
        cell.fill.solid()
        cell.fill.fore_color.rgb = _HEADER_BG

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
            if row_idx % 2 == 1:
                cell.fill.solid()
                cell.fill.fore_color.rgb = _ALT_ROW_BG

    if num_cols > 1:
        first_col_pct = 0.30
        remaining_pct = (1.0 - first_col_pct) / (num_cols - 1)
        table.columns[0].width = Inches(width * first_col_pct)
        for i in range(1, num_cols):
            table.columns[i].width = Inches(width * remaining_pct)


def _add_chart_image(slide, chart_key, chart_paths, position="right"):
    clean_key = chart_key
    m = re.search(r"\{\{\s*chart\.([a-zA-Z0-9_-]+)\s*\}\}", chart_key)
    if m:
        clean_key = m.group(1)

    chart_path = chart_paths.get(clean_key, "")
    if not chart_path or not Path(chart_path).exists():
        return

    positions = {
        "right":  (Inches(8.0),  Inches(1.8), Inches(4.8)),
        "left":   (Inches(0.6),  Inches(1.8), Inches(4.8)),
        "bottom": (Inches(0.6),  Inches(4.5), Inches(11.5)),
        "full":   (Inches(0.6),  Inches(1.8), Inches(11.5)),
    }
    left, top, width = positions.get(position, positions["right"])
    slide.shapes.add_picture(str(chart_path), left, top, width=width)


# ---------------------------------------------------------------------------
# Legacy element renderer (backward compat)
# ---------------------------------------------------------------------------


def _add_text_elements(tf, elements, hierarchy):
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
        style_key = etype if etype in hierarchy else "point_description"
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
# Slide type renderers
# ═══════════════════════════════════════════════════════════════════════════


def _render_executive_summary(prs, slide_data, hierarchy, layout_idx):
    """Slide 1: Title + context subtitle + horizontal rule + Quick Wins."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "EXECUTIVE SUMMARY"))
    subtitle_text = _strip_md(slide_data.get("subtitle", ""))
    quick_wins = slide_data.get("quick_wins", [])

    # Title (28pt, bold, navy)
    _add_textbox(slide, 0.6, 0.4, 12.0, 0.7, title_text,
                 {"size": Pt(28), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"})

    # Subtitle context (13pt, black)
    y = 1.2
    if subtitle_text:
        _add_textbox(slide, 0.6, y, 12.0, 0.6, subtitle_text,
                     {"size": Pt(13), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 0.7

    # Thin horizontal rule (grey, 80% width)
    _add_separator_line(slide, 0.6, y, 10.5, color=COLOR_MUTED)
    y += 0.4

    # "Quick Wins:" label (16pt, blue)
    if quick_wins:
        _add_textbox(slide, 0.6, y, 12.0, 0.4, "Quick Wins:",
                     {"size": Pt(16), "bold": True, "color": COLOR_SECONDARY, "font": "Calibri"})
        y += 0.5

        # Quick win bullet items (12pt, black)
        for qw in quick_wins[:5]:
            qw_text = _strip_md(str(qw))
            txBox = slide.shapes.add_textbox(Inches(0.8), Inches(y), Inches(11.5), Inches(0.4))
            tf = txBox.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            bullet_run = p.add_run()
            bullet_run.text = "\u2022  "
            _apply_font(bullet_run, {"size": Pt(12), "bold": False, "color": COLOR_SECONDARY, "font": "Calibri"})
            text_run = p.add_run()
            text_run.text = qw_text
            _apply_font(text_run, {"size": Pt(12), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
            y += 0.45


def _render_pain_point_cards(prs, slide_data, hierarchy, layout_idx):
    """Slide 2: 3-column card layout with accent bars."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "Key Pain Points"))
    _add_textbox(slide, 0.6, 0.4, 12.0, 0.7, title_text, hierarchy.get("h1", _DEFAULT_HIERARCHY["h1"]))

    cards = slide_data.get("cards", [])
    if not cards:
        return

    accent_colors = [COLOR_RED, COLOR_AMBER, COLOR_SECONDARY]
    card_width = 3.8
    card_gap = 0.3
    start_left = 0.6

    for i, card in enumerate(cards[:3]):
        card_left = start_left + i * (card_width + card_gap)
        card_top = 1.4
        accent_color = accent_colors[i % len(accent_colors)]

        # Accent bar (left edge)
        bar = slide.shapes.add_shape(1, Inches(card_left), Inches(card_top),
                                     Inches(0.08), Inches(5.2))
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent_color
        bar.line.fill.background()

        # Card background
        card_bg = slide.shapes.add_shape(1, Inches(card_left + 0.08), Inches(card_top),
                                         Inches(card_width - 0.08), Inches(5.2))
        card_bg.fill.solid()
        card_bg.fill.fore_color.rgb = COLOR_LIGHT_BG
        card_bg.line.fill.background()

        content_left = card_left + 0.25
        content_width = card_width - 0.4
        y = card_top + 0.2

        # Card title + call count
        name = _strip_md(str(card.get("name", f"Pain Point {i+1}")))
        calls = card.get("calls", 0)
        title_with_calls = f"{name} ({calls} calls)" if calls else name
        _add_textbox(slide, content_left, y, content_width, 0.4, title_with_calls,
                     {"size": Pt(14), "bold": True, "color": COLOR_TEXT, "font": "Calibri"})
        y += 0.5

        # Impact + Priority scores (grey, 10pt)
        impact_score = card.get("impact_score", card.get("impact", 0))
        priority = card.get("priority", 0)
        stats_text = f"Impact: {impact_score} | Priority: {priority}"
        _add_textbox(slide, content_left, y, content_width, 0.25, stats_text,
                     {"size": Pt(10), "bold": False, "color": COLOR_MUTED, "font": "Calibri"})
        y += 0.45

        # Issue label + text (bold label, 12pt body)
        _add_textbox(slide, content_left, y, content_width, 0.25, "Issue:",
                     {"size": Pt(12), "bold": True, "color": COLOR_TEXT, "font": "Calibri"})
        y += 0.3
        issue = _strip_md(str(card.get("issue", "")))
        _add_textbox(slide, content_left, y, content_width, 1.2, issue,
                     {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 1.4

        # Fix label + text (bold label, green, includes owner in parens)
        _add_textbox(slide, content_left, y, content_width, 0.25, "Fix:",
                     {"size": Pt(12), "bold": True, "color": COLOR_GREEN, "font": "Calibri"})
        y += 0.3
        fix = _strip_md(str(card.get("fix", "")))
        # If there's a separate owner field, append it
        owner = card.get("owner", "")
        if owner and f"({owner})" not in fix and owner not in fix:
            fix = f"{fix} ({owner})"
        _add_textbox(slide, content_left, y, content_width, 1.0, fix,
                     {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})


def _render_impact_matrix(prs, slide_data, hierarchy, layout_idx, chart_paths):
    """Slide 3: Theme card list LEFT (~60%), scatter chart RIGHT (~40%)."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "Impact vs. Ease \u2014 Full Theme Prioritization"))
    _add_textbox(slide, 0.4, 0.3, 12.5, 0.6, title_text, hierarchy.get("h1", _DEFAULT_HIERARCHY["h1"]))

    # Themes list on LEFT
    themes = slide_data.get("themes", [])

    # Fallback: if no themes but there's a legacy table, use the table approach
    if not themes:
        table_data = slide_data.get("table", {})
        if table_data and table_data.get("headers"):
            _add_table_to_slide(slide, table_data["headers"], table_data.get("rows", []),
                                hierarchy, left=0.4, top=1.2, width=7.0, row_height=0.30)
        chart_ph = slide_data.get("chart_placeholder", {})
        if chart_ph:
            _add_chart_image(slide, chart_ph.get("chart_key", "impact_ease_scatter"),
                             chart_paths, position=chart_ph.get("position", "right"))
        return

    y = 1.1
    left_width = 7.2

    for t_idx, theme in enumerate(themes[:10]):
        t_name = _strip_md(str(theme.get("name", "")))
        quadrant = _strip_md(str(theme.get("quadrant", "")))
        t_calls = theme.get("calls", 0)
        t_impact = theme.get("impact", 0)
        t_ease = theme.get("ease", 0)
        t_priority = theme.get("priority", 0)
        t_issue = _strip_md(str(theme.get("issue", "")))

        # Theme name (bold, blue) + quadrant
        header_text = f"{t_name}" + (f" \u2014 {quadrant}" if quadrant else "")
        _add_textbox(slide, 0.4, y, left_width, 0.3, header_text,
                     {"size": Pt(12), "bold": True, "color": COLOR_SECONDARY, "font": "Calibri"})
        y += 0.28

        # Stats line (grey, 10pt)
        stats = f"Calls: {t_calls} | Impact: {t_impact} | Ease: {t_ease} | Priority: {t_priority}"
        _add_textbox(slide, 0.6, y, left_width - 0.2, 0.2, stats,
                     {"size": Pt(9), "bold": False, "color": COLOR_MUTED, "font": "Calibri"})
        y += 0.22

        # Issue (black, 10pt)
        if t_issue:
            _add_textbox(slide, 0.6, y, left_width - 0.2, 0.3, t_issue,
                         {"size": Pt(9), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
            y += 0.28

        # Subtle separator between themes
        if t_idx < min(len(themes), 10) - 1:
            _add_separator_line(slide, 0.6, y, 6.5, color=RGBColor(0xDD, 0xDD, 0xDD))
            y += 0.12

    # Chart on RIGHT
    chart_ph = slide_data.get("chart_placeholder", {})
    if chart_ph:
        _add_chart_image(slide, chart_ph.get("chart_key", "impact_ease_scatter"),
                         chart_paths, position=chart_ph.get("position", "right"))


def _render_low_hanging_fruit(prs, slide_data, hierarchy, layout_idx):
    """Slide 4: 3 easiest solutions with blue title + black elaboration."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "Low Hanging Fruit"))
    _add_textbox(slide, 0.6, 0.4, 12.0, 0.7, title_text, hierarchy.get("h1", _DEFAULT_HIERARCHY["h1"]))

    solutions = slide_data.get("solutions", [])
    y = 1.5

    for sol in solutions[:3]:
        sol_title = _strip_md(str(sol.get("title", "")))
        sol_detail = _strip_md(str(sol.get("detail", "")))
        sol_impact = _strip_md(str(sol.get("call_impact", "")))

        # Solution title (16pt, blue, bold)
        _add_textbox(slide, 0.8, y, 11.5, 0.4, f"\u2022  {sol_title}",
                     {"size": Pt(16), "bold": True, "color": COLOR_SECONDARY, "font": "Calibri"})
        y += 0.5

        # Elaboration (12pt, black, indented)
        if sol_detail:
            _add_textbox(slide, 1.3, y, 11.0, 0.7, sol_detail,
                         {"size": Pt(12), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
            y += 0.6

        # Call impact (12pt, muted, indented)
        if sol_impact:
            _add_textbox(slide, 1.3, y, 11.0, 0.3, sol_impact,
                         {"size": Pt(12), "bold": False, "color": COLOR_MUTED, "font": "Calibri"})
            y += 0.4

        y += 0.3  # gap between solutions


def _render_recommendations(prs, slide_data, hierarchy, layout_idx):
    """Slide 5: 2x2 card grid with per-dimension accent colors."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", "Recommended Actions by Owning Team"))
    _add_textbox(slide, 0.6, 0.4, 12.0, 0.7, title_text, hierarchy.get("h1", _DEFAULT_HIERARCHY["h1"]))

    dimensions = slide_data.get("dimensions", [])
    if not dimensions:
        # Fallback to legacy elements
        _render_legacy_content(prs, slide, slide_data, hierarchy, {})
        return

    default_colors = {
        "Digital / UX": "006BA6", "Digital/UX": "006BA6",
        "Operations": "2C5F2D",
        "Communications": "E67E22",
        "Policy": "8E44AD",
    }

    positions = [
        (0.6, 1.6),   # top-left
        (6.8, 1.6),   # top-right
        (0.6, 4.4),   # bottom-left
        (6.8, 4.4),   # bottom-right
    ]
    card_width = 5.8

    for i, dim in enumerate(dimensions[:4]):
        if i >= len(positions):
            break

        card_left, card_top = positions[i]
        dim_name = str(dim.get("name", f"Dimension {i+1}"))
        accent_hex = dim.get("accent_color", default_colors.get(dim_name, "006BA6"))
        accent_color = _hex_to_rgb(accent_hex)

        # Colored square icon
        icon = slide.shapes.add_shape(1, Inches(card_left), Inches(card_top),
                                      Inches(0.25), Inches(0.25))
        icon.fill.solid()
        icon.fill.fore_color.rgb = accent_color
        icon.line.fill.background()

        # Dimension name
        _add_textbox(slide, card_left + 0.35, card_top - 0.05, card_width - 0.35, 0.35,
                     dim_name,
                     {"size": Pt(14), "bold": True, "color": COLOR_TEXT, "font": "Calibri"})

        # Actions
        y = card_top + 0.45
        for action in dim.get("actions", [])[:2]:
            action_title = _strip_md(str(action.get("title", "")))
            action_detail = _strip_md(str(action.get("detail", "")))
            calls = action.get("calls", 0)

            txBox = slide.shapes.add_textbox(Inches(card_left + 0.3), Inches(y),
                                             Inches(card_width - 0.3), Inches(0.7))
            tf = txBox.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]

            bullet_run = p.add_run()
            bullet_run.text = "\u2022 "
            _apply_font(bullet_run, {"size": Pt(12), "bold": True, "color": accent_color, "font": "Calibri"})

            title_run = p.add_run()
            title_run.text = action_title
            _apply_font(title_run, {"size": Pt(12), "bold": True, "color": COLOR_TEXT, "font": "Calibri"})

            if action_detail:
                detail_p = tf.add_paragraph()
                detail_run = detail_p.add_run()
                detail_text = f"   \u2192 {action_detail}"
                if calls:
                    detail_text += f" ({calls} calls)"
                detail_run.text = detail_text
                _apply_font(detail_run, {"size": Pt(10), "bold": False, "color": COLOR_MUTED, "font": "Calibri"})

            y += 0.9


def _render_theme_card(prs, slide_data, hierarchy, layout_idx, chart_paths):
    """Slide 6+: Stats bar + LEFT narrative (60%) + RIGHT driver table (40%)."""
    layout = prs.slide_layouts[min(layout_idx, len(prs.slide_layouts) - 1)]
    slide = prs.slides.add_slide(layout)

    title_text = _strip_md(slide_data.get("title", ""))
    stats_bar = slide_data.get("stats_bar", {})
    left_column = slide_data.get("left_column", {})
    right_column = slide_data.get("right_column", {})

    # Fallback to legacy rendering
    if not stats_bar and not left_column and not right_column:
        _render_legacy_theme_card(prs, slide, slide_data, hierarchy, chart_paths)
        return

    # Title (24pt, bold)
    _add_textbox(slide, 0.5, 0.3, 12.0, 0.6, title_text,
                 {"size": Pt(24), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"})

    # Stats bar (11pt, muted gray)
    if stats_bar:
        calls = stats_bar.get("calls", 0)
        pct = stats_bar.get("pct", "")
        impact = stats_bar.get("impact", 0)
        ease = stats_bar.get("ease", 0)
        priority = stats_bar.get("priority", 0)
        stats_text = f"Calls: {calls} | {pct} | Impact: {impact} | Ease: {ease} | Priority: {priority}"
        _add_textbox(slide, 0.5, 0.95, 12.0, 0.3, stats_text,
                     hierarchy.get("stats_bar", _DEFAULT_HIERARCHY["stats_bar"]))

    # LEFT COLUMN (60%)
    left_x = 0.5
    left_width = 7.2
    y = 1.5

    if left_column:
        # CORE ISSUE
        _add_textbox(slide, left_x, y, left_width, 0.3, "CORE ISSUE",
                     {"size": Pt(13), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"})
        y += 0.35
        core_issue = _strip_md(str(left_column.get("core_issue", "")))
        if core_issue:
            _add_textbox(slide, left_x, y, left_width, 1.0, core_issue,
                         {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 1.1

        # PRIMARY DRIVER
        _add_textbox(slide, left_x, y, left_width, 0.3, "PRIMARY DRIVER",
                     {"size": Pt(13), "bold": True, "color": COLOR_PRIMARY, "font": "Calibri"})
        y += 0.35
        primary_driver = _strip_md(str(left_column.get("primary_driver", "")))
        if primary_driver:
            _add_textbox(slide, left_x, y, left_width, 0.8, primary_driver,
                         {"size": Pt(11), "bold": False, "color": COLOR_TEXT, "font": "Calibri"})
        y += 0.9

        # SOLUTIONS
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

    # RIGHT COLUMN (40%)
    right_x = 8.0
    right_width = 5.0
    right_top = 1.5

    if right_column:
        headers = right_column.get("headers", ["Driver", "Calls"])
        rows = right_column.get("rows", [])
        if headers and rows:
            _add_table_to_slide(slide, headers, rows, hierarchy,
                                left=right_x, top=right_top, width=right_width, row_height=0.28)


def _render_legacy_theme_card(prs, slide, slide_data, hierarchy, chart_paths):
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
        text_elems = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elems, hierarchy)
    for t_elem in elements:
        if t_elem.get("type") == "table":
            _add_table_to_slide(slide, t_elem.get("headers", []), t_elem.get("rows", []),
                                hierarchy, left=0.6, top=4.0, width=7.5, row_height=0.30)
    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            _add_chart_image(slide, elem.get("chart_key", ""), chart_paths,
                             position=elem.get("position", "right"))
            break


def _render_legacy_content(prs, slide, slide_data, hierarchy, chart_paths):
    """Legacy content rendering using elements array."""
    elements = slide_data.get("elements", [])
    body_ph = None
    for ph in slide.placeholders:
        if ph.placeholder_format.type in (2, 7):
            body_ph = ph
            break
    if body_ph and elements:
        text_elems = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elems, hierarchy)
    for elem in elements:
        if elem.get("type") == "table":
            _add_table_to_slide(slide, elem.get("headers", []), elem.get("rows", []), hierarchy)
    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            _add_chart_image(slide, elem.get("chart_key", ""), chart_paths,
                             position=elem.get("position", "right"))


# ---------------------------------------------------------------------------
# Generic slide builders (legacy fallback)
# ---------------------------------------------------------------------------


def _build_content_slide(prs, slide_data, hierarchy, layout_idx, chart_paths):
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
        text_elems = [e for e in elements if e.get("type") not in ("table", "chart_placeholder")]
        _add_text_elements(body_ph.text_frame, text_elems, hierarchy)
    for elem in elements:
        if elem.get("type") == "table":
            _add_table_to_slide(slide, elem.get("headers", []), elem.get("rows", []), hierarchy)
    for elem in elements:
        if elem.get("type") == "chart_placeholder":
            _add_chart_image(slide, elem.get("chart_key", ""), chart_paths,
                             position=elem.get("position", "right"))


# ---------------------------------------------------------------------------
# Slide role dispatcher
# ---------------------------------------------------------------------------

_STRUCTURED_ROLES = {"executive_summary", "pain_points", "impact_matrix",
                     "low_hanging_fruit", "recommendations", "theme_card"}


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
        chart_paths: Map of chart_key -> image file path.
        output_path: Where to save the .pptx.
        template_path: Path to .pptx template file.
        visual_hierarchy: Optional visual hierarchy from template catalog.

    Returns:
        The output path.
    """
    if template_path and Path(template_path).exists():
        prs = Presentation(template_path)
    else:
        prs = Presentation()

    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    hierarchy = _load_hierarchy(visual_hierarchy)
    num_layouts = len(prs.slide_layouts)

    for section in section_blueprints:
        for slide_data in section.get("slides", []):
            layout_idx = slide_data.get("layout_index", 1)
            if layout_idx >= num_layouts:
                layout_idx = 1

            slide_role = slide_data.get("slide_role", "content")

            if slide_role == "executive_summary":
                _render_executive_summary(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "hook":
                # Legacy hook — render as executive_summary
                _render_executive_summary(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "hook_and_quick_wins":
                # Legacy hook+quick_wins — render as executive_summary
                _render_executive_summary(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "pain_points" and slide_data.get("cards"):
                _render_pain_point_cards(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "impact_matrix":
                _render_impact_matrix(prs, slide_data, hierarchy, layout_idx, chart_paths)

            elif slide_role == "low_hanging_fruit":
                _render_low_hanging_fruit(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "biggest_bet":
                # Legacy biggest_bet — render as low_hanging_fruit fallback
                _render_low_hanging_fruit(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "recommendations" and slide_data.get("dimensions"):
                _render_recommendations(prs, slide_data, hierarchy, layout_idx)

            elif slide_role == "theme_card":
                _render_theme_card(prs, slide_data, hierarchy, layout_idx, chart_paths)

            else:
                _build_content_slide(prs, slide_data, hierarchy, layout_idx, chart_paths)

    prs.save(output_path)
    logger.info("PPTX built: %d slides -> %s",
                sum(len(s.get("slides", [])) for s in section_blueprints), output_path)
    return output_path

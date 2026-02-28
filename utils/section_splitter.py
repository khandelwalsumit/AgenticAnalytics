"""Split narrative markdown into sections for per-section formatting.

The Narrative Agent produces a single markdown document with ``<!-- SLIDE -->``
boundary tags.  This module parses those tags and groups slides into 3 sections:

  1. **exec_summary** — hook, situation/pain points, quick wins (3 slides)
  2. **impact** — matrix table, biggest bet callout, recommendations (3 slides)
  3. **theme_deep_dives** — one slide per theme, max 10 themes

Each section is paired with the relevant slice of the template catalog so the
formatting agent (or deterministic builder) knows exactly which layouts to use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# SLIDE tag parser
# ---------------------------------------------------------------------------

# Pattern: <!-- SLIDE: {section_type} | layout: {layout_id} | title: "{title}" -->
_SLIDE_TAG_RE = re.compile(
    r'<!--\s*SLIDE\s*:\s*(?P<section_type>[^|]+?)\s*'
    r'\|\s*layout\s*:\s*(?P<layout>[^|]+?)\s*'
    r'\|\s*title\s*:\s*"(?P<title>[^"]*?)"\s*-->',
    re.IGNORECASE,
)


def _parse_slide_blocks(narrative_md: str) -> list[dict[str, Any]]:
    """Parse narrative markdown into ordered slide blocks."""
    blocks: list[dict[str, Any]] = []
    positions: list[tuple[int, re.Match]] = []

    for m in _SLIDE_TAG_RE.finditer(narrative_md):
        positions.append((m.start(), m))

    for i, (pos, m) in enumerate(positions):
        # Body = everything between this tag and the next (or end of doc)
        body_start = m.end()
        body_end = positions[i + 1][0] if i + 1 < len(positions) else len(narrative_md)
        body = narrative_md[body_start:body_end].strip()

        # Clean out markdown horizontal rules at boundaries
        body = re.sub(r'^---\s*$', '', body, flags=re.MULTILINE).strip()

        blocks.append({
            "slide_index": i,
            "section_type": m.group("section_type").strip(),
            "layout": m.group("layout").strip(),
            "title": m.group("title").strip(),
            "body": body,
            "tag_raw": m.group(0),
        })

    return blocks


# ---------------------------------------------------------------------------
# Section classification
# ---------------------------------------------------------------------------

# Section type prefixes → section key
_SECTION_TYPE_MAP = {
    "executive_summary": "exec_summary",
    "pain_point": "exec_summary",
    "quick_wins": "exec_summary",
    "matrix": "impact",
    "matrix_bet": "impact",
    "recommendations": "impact",
    "recommendations_digital": "impact",
    "recommendations_ops": "impact",
    "recommendations_comms": "impact",
    "recommendations_policy": "impact",
    "theme_divider": "theme_deep_dives",
    "theme_narrative": "theme_deep_dives",
    "theme_drivers": "theme_deep_dives",
    "theme_consequence": "theme_deep_dives",
}


def _classify_block(block: dict[str, Any]) -> str:
    """Classify a slide block into one of the 3 sections."""
    st = block["section_type"].lower().strip()
    if st in _SECTION_TYPE_MAP:
        return _SECTION_TYPE_MAP[st]

    # Fuzzy matching for edge cases
    if any(k in st for k in ("exec", "summary", "hook", "situation", "pain", "quick")):
        return "exec_summary"
    if any(k in st for k in ("matrix", "impact", "ease", "bet", "recommend", "action")):
        return "impact"
    if any(k in st for k in ("theme", "deep", "dive", "driver", "consequence")):
        return "theme_deep_dives"

    return "theme_deep_dives"  # default: deep dives catch-all


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def split_narrative_into_sections(
    narrative_md: str,
    template_catalog: dict[str, Any] | None = None,
    max_themes: int = 10,
) -> dict[str, Any]:
    """Split narrative markdown into 3 sections with template catalog slices.

    Args:
        narrative_md: Full narrative markdown with <!-- SLIDE --> tags.
        template_catalog: Parsed template_catalog.json. If None, loads from default path.
        max_themes: Maximum number of themes to include in deep dives.

    Returns:
        Dict with keys: ``exec_summary``, ``impact``, ``theme_deep_dives``.
        Each contains:
          - ``slides``: list of slide blocks (section_type, layout, title, body)
          - ``narrative_chunk``: concatenated markdown for this section
          - ``template_spec``: relevant template catalog slice for this section
    """
    if template_catalog is None:
        template_catalog = _load_default_catalog()

    blocks = _parse_slide_blocks(narrative_md)

    # Group blocks by section
    sections: dict[str, list[dict[str, Any]]] = {
        "exec_summary": [],
        "impact": [],
        "theme_deep_dives": [],
    }

    for block in blocks:
        section_key = _classify_block(block)
        sections[section_key].append(block)

    # Cap theme deep dives at max_themes (each theme = 4 slides typically,
    # but user wants 1 slide per theme in the PPTX — we still pass all
    # narrative content so the formatting agent can condense)
    theme_blocks = sections["theme_deep_dives"]
    if len(theme_blocks) > max_themes * 4:
        # Identify unique themes by scanning for theme_divider blocks
        theme_names: list[str] = []
        for b in theme_blocks:
            if b["section_type"].lower() in ("theme_divider",):
                theme_names.append(b["title"])
        # Keep only first max_themes theme groups
        kept_themes = set(theme_names[:max_themes])
        if kept_themes:
            filtered: list[dict[str, Any]] = []
            current_theme_name = ""
            for b in theme_blocks:
                if b["section_type"].lower() == "theme_divider":
                    current_theme_name = b["title"]
                if current_theme_name in kept_themes or not kept_themes:
                    filtered.append(b)
            sections["theme_deep_dives"] = filtered

    # Build output
    section_map = template_catalog.get("section_map", {})
    visual_hierarchy = template_catalog.get("visual_hierarchy", {})

    result: dict[str, Any] = {}
    for section_key, slide_blocks in sections.items():
        # Build the narrative chunk by concatenating tag + body
        narrative_chunk_parts: list[str] = []
        for b in slide_blocks:
            narrative_chunk_parts.append(b["tag_raw"])
            narrative_chunk_parts.append("")
            narrative_chunk_parts.append(b["body"])
            narrative_chunk_parts.append("")
            narrative_chunk_parts.append("---")
            narrative_chunk_parts.append("")

        result[section_key] = {
            "slides": slide_blocks,
            "slide_count": len(slide_blocks),
            "narrative_chunk": "\n".join(narrative_chunk_parts).strip(),
            "template_spec": section_map.get(section_key, {}),
            "visual_hierarchy": visual_hierarchy,
        }

    return result


def _load_default_catalog() -> dict[str, Any]:
    """Load template_catalog.json from the default path."""
    catalog_path = Path(__file__).resolve().parent.parent / "data" / "input" / "template_catalog.json"
    if not catalog_path.exists():
        return {"section_map": {}, "visual_hierarchy": {}}
    return json.loads(catalog_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Utility: extract themes list from narrative for the formatting agent
# ---------------------------------------------------------------------------


def extract_theme_names(narrative_md: str, max_themes: int = 10) -> list[str]:
    """Extract unique theme names from SLIDE tags in the narrative."""
    blocks = _parse_slide_blocks(narrative_md)
    themes: list[str] = []
    for b in blocks:
        if b["section_type"].lower() == "theme_divider":
            name = b["title"].replace(" — Deep Dive", "").replace(" - Deep Dive", "").strip()
            if name and name not in themes:
                themes.append(name)
    return themes[:max_themes]

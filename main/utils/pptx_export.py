"""Markdown → PowerPoint converter."""

from __future__ import annotations

import re

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


def markdown_to_pptx(markdown: str, output_path: str) -> str:
    """Convert a markdown report to a PowerPoint presentation.

    Parses markdown headers (# / ##) as slide titles, bullet points as
    content, and tables as simple text layouts.

    Args:
        markdown: The markdown content string.
        output_path: File path to save the .pptx.

    Returns:
        The output path.
    """
    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    sections = _split_sections(markdown)

    for section in sections:
        _add_slide(prs, section["title"], section["body"])

    prs.save(output_path)
    return output_path


def _split_sections(markdown: str) -> list[dict]:
    """Split markdown into sections by ## headers."""
    sections = []
    current_title = ""
    current_body: list[str] = []

    for line in markdown.split("\n"):
        # Top-level heading → title slide
        if line.startswith("# ") and not line.startswith("## "):
            if current_title or current_body:
                sections.append({"title": current_title, "body": "\n".join(current_body)})
            current_title = line.lstrip("# ").strip()
            current_body = []
        # Section heading → new content slide
        elif line.startswith("## "):
            if current_title or current_body:
                sections.append({"title": current_title, "body": "\n".join(current_body)})
            current_title = line.lstrip("# ").strip()
            current_body = []
        else:
            current_body.append(line)

    if current_title or current_body:
        sections.append({"title": current_title, "body": "\n".join(current_body)})

    return sections


def _add_slide(prs: Presentation, title: str, body: str) -> None:
    """Add a slide with title and body content."""
    slide_layout = prs.slide_layouts[1]  # Title + Content
    slide = prs.slides.add_slide(slide_layout)

    # Title
    if slide.shapes.title:
        slide.shapes.title.text = title
        for paragraph in slide.shapes.title.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(28)
                run.font.bold = True

    # Body content
    if len(slide.placeholders) > 1:
        body_placeholder = slide.placeholders[1]
        tf = body_placeholder.text_frame
        tf.clear()

        lines = body.strip().split("\n")
        first = True
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped == "---":
                continue

            if first:
                p = tf.paragraphs[0]
                first = False
            else:
                p = tf.add_paragraph()

            # Handle bullet points
            indent_level = 0
            text = stripped
            if stripped.startswith("- ") or stripped.startswith("* "):
                text = stripped[2:]
                indent_level = 0
            elif stripped.startswith("  - ") or stripped.startswith("  * "):
                text = stripped[4:]
                indent_level = 1

            # Handle bold markers
            text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)

            p.text = text
            p.level = indent_level
            p.alignment = PP_ALIGN.LEFT
            for run in p.runs:
                run.font.size = Pt(16)

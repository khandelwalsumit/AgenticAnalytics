"""Standalone artifact generation script for rapid iteration.

Reads a saved graph state JSON (from data/.cache/states/<thread_id>.json),
then re-runs the 3 artifact pipelines (dataviz, deck blueprint, DOCX/PPTX)
WITHOUT the full app or Chainlit.

Usage:
    # Use the most recent state file (default):
    python test/test_artifacts.py

    # Use a specific state file:
    python test/test_artifacts.py --state data/.cache/states/007a6944.json

    # Load directly from a synthesis JSON (no full state needed):
    python test/test_artifacts.py --synthesis data/tmp/.cache/<thread_id>/synthesis_v1.json

    # Load by cache thread directory (auto-finds synthesis_v1.json inside):
    python test/test_artifacts.py --cache data/tmp/.cache/2f40f909-c2b9-498f-b513-3469e80fa441

    # Override output directory:
    python test/test_artifacts.py --output data/output/test_run

    # Skip chart generation (reuse existing PNGs):
    python test/test_artifacts.py --skip-charts

All outputs land in the chosen output dir:
    complete_analysis.md, report.pptx, report.docx, charts/*.png
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# ── project root on sys.path ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import (
    DATA_CACHE_DIR,
    DATA_OUTPUT_DIR,
    PPTX_TEMPLATE_PATH,
    THREAD_STATES_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_artifacts")


# ══════════════════════════════════════════════════════════════════════
# 1. State / synthesis loader
# ══════════════════════════════════════════════════════════════════════

def _latest_state_file() -> Path:
    """Return the most recently modified state JSON."""
    states_dir = Path(THREAD_STATES_DIR)
    if not states_dir.exists():
        raise FileNotFoundError(f"No states directory at {states_dir}")
    files = sorted(states_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No state JSON files in {states_dir}")
    return files[0]


def load_state(path: Path) -> dict:
    """Load and return the graph state dict from a JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    # State files may be wrapped: {"state": {...}} or flat
    if "state" in raw and isinstance(raw["state"], dict):
        return raw["state"]
    return raw


def load_synthesis(synthesis_path: str | None, state: dict) -> dict:
    """Resolve synthesis JSON from an explicit path, state["synthesis_path"], or empty dict.

    The synthesis data lives in a versioned file (synthesis_v1.json) written by the
    synthesizer node — it is NOT stored inline in the state dict. This function
    resolves the right file and returns the parsed dict.
    """
    # 1. Explicit --synthesis argument wins
    if synthesis_path:
        p = Path(synthesis_path)
        if not p.is_absolute():
            p = ROOT / p
        if p.exists():
            logger.info("Synthesis loaded from explicit path: %s", p)
            return json.loads(p.read_text(encoding="utf-8"))
        logger.warning("--synthesis path not found: %s", p)

    # 2. state["synthesis_path"] (written by synthesizer node)
    sp = state.get("synthesis_path", "")
    if sp:
        p = Path(sp)
        if p.exists():
            logger.info("Synthesis loaded from state['synthesis_path']: %s", p)
            return json.loads(p.read_text(encoding="utf-8"))
        logger.warning("state['synthesis_path'] not found: %s", sp)

    logger.warning("No synthesis data found — charts and blueprint will be empty.")
    return {}


def find_synthesis_in_cache(cache_dir: Path) -> Path | None:
    """Find the most recent synthesis_vN.json in a cache thread directory."""
    candidates = sorted(cache_dir.glob("synthesis_v*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


# ══════════════════════════════════════════════════════════════════════
# 2. Chart generation (dataviz)
# ══════════════════════════════════════════════════════════════════════

def generate_charts(synthesis: dict, output_dir: Path) -> dict[str, str]:
    """Run deterministic chart scripts and return {chart_type: path} map."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np  # noqa: F401 — used in exec'd code

    themes_raw = synthesis.get("themes", []) if isinstance(synthesis, dict) else []

    themes: list[str] = []
    call_counts: list[int] = []
    ease_scores: list[float] = []
    impact_scores: list[float] = []
    primary_counts: list[int] = []
    secondary_counts: list[int] = []

    for item in (themes_raw[:8] if isinstance(themes_raw, list) else []):
        if not isinstance(item, dict):
            continue
        theme_name = str(item.get("theme", "")).strip() or "Unknown"
        total_calls = max(0, int(float(item.get("call_count", 0) or 0)))
        ease = max(0.0, min(10.0, float(item.get("ease_score", 0) or 0)))
        impact = max(0.0, min(10.0, float(item.get("impact_score", 0) or 0)))

        primary = secondary = 0
        for d in (item.get("all_drivers", []) or []):
            if not isinstance(d, dict):
                continue
            dc = max(0, int(float(d.get("call_count", 0) or 0)))
            if str(d.get("type", "")).strip().lower() == "primary":
                primary += dc
            else:
                secondary += dc
        # Safety fallback: if synthesizer still produced 0s, use theme total
        if primary == 0 and secondary == 0:
            primary = total_calls

        themes.append(theme_name)
        call_counts.append(total_calls)
        ease_scores.append(ease)
        impact_scores.append(impact)
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
            "filename": "friction_distribution.png",
            "code": (
                "import numpy as np\n"
                f"labels = {json.dumps(themes)}\n"
                f"values = {json.dumps(call_counts)}\n"
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
            "filename": "impact_ease_scatter.png",
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
            "filename": "driver_breakdown.png",
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

    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_paths: dict[str, str] = {}

    for spec in chart_specs:
        out_path = chart_dir / spec["filename"]
        exec_globals = {"plt": plt, "np": __import__("numpy"), "output_path": str(out_path)}
        try:
            exec(spec["code"], exec_globals)  # noqa: S102
            plt.close("all")
            chart_paths[spec["type"]] = str(out_path)
            logger.info("Chart OK: %s -> %s", spec["type"], out_path)
        except Exception as e:
            logger.error("Chart FAILED: %s - %s", spec["type"], e)

    return chart_paths


# ══════════════════════════════════════════════════════════════════════
# 3. Deck blueprint (deterministic, no LLM)
# ══════════════════════════════════════════════════════════════════════

def build_deck_blueprint(synthesis: dict) -> list[dict]:
    """Build section blueprints from synthesis JSON (themes + findings).

    Calls the real _build_fixed_deck_blueprint from graph_helpers.
    """
    from agents.graph_helpers import _build_fixed_deck_blueprint

    findings = synthesis.get("findings", []) or []
    return _build_fixed_deck_blueprint(synthesis, findings)


# ══════════════════════════════════════════════════════════════════════
# 4. Narrative markdown
# ══════════════════════════════════════════════════════════════════════

def get_narrative_markdown(state: dict, thread_id: str) -> str:
    """Extract narrative markdown from state or cached files."""
    # 1. Try state.narrative_output.full_response
    narr = state.get("narrative_output", {})
    if isinstance(narr, dict):
        md = str(narr.get("full_response", "")).strip()
        if md:
            return md

    # 2. Try reading from output dir
    output_md = Path(DATA_OUTPUT_DIR) / thread_id / "complete_analysis.md"
    if output_md.exists():
        return output_md.read_text(encoding="utf-8")

    # 3. Try reading from cache dir (narrative_v1.md)
    cache_md = Path(DATA_CACHE_DIR) / thread_id / "narrative_v1.md"
    if cache_md.exists():
        return cache_md.read_text(encoding="utf-8")

    return "# Analysis Report\n\nNo narrative markdown found in state or cached files."


# ══════════════════════════════════════════════════════════════════════
# 5. PPTX generation
# ══════════════════════════════════════════════════════════════════════

def generate_pptx(
    section_blueprints: list[dict],
    chart_paths: dict[str, str],
    output_dir: Path,
) -> str:
    from utils.pptx_builder import build_pptx_from_sections

    # Load visual hierarchy from template catalog if available
    catalog_path = ROOT / "data" / "input" / "template_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {}
    visual_hierarchy = catalog.get("visual_hierarchy")

    template = PPTX_TEMPLATE_PATH if Path(PPTX_TEMPLATE_PATH).exists() else ""
    pptx_path = str(output_dir / "report.pptx")

    build_pptx_from_sections(
        section_blueprints=section_blueprints,
        chart_paths=chart_paths,
        output_path=pptx_path,
        template_path=template,
        visual_hierarchy=visual_hierarchy,
    )
    logger.info("PPTX -> %s", pptx_path)
    return pptx_path


# ══════════════════════════════════════════════════════════════════════
# 6. DOCX generation
# ══════════════════════════════════════════════════════════════════════

def generate_docx(narrative_markdown: str, output_dir: Path) -> str:
    from utils.docx_export import markdown_to_docx

    docx_path = str(output_dir / "report.docx")
    markdown_to_docx(narrative_markdown, docx_path)
    logger.info("DOCX -> %s", docx_path)
    return docx_path


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Re-generate PPTX/DOCX artifacts from a saved graph state or synthesis JSON.",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="Path to state JSON. Default: most recent in data/.cache/states/",
    )
    parser.add_argument(
        "--synthesis", type=str, default="",
        help="Path to synthesis_v1.json (skips state lookup; useful for testing synthesizer output directly).",
    )
    parser.add_argument(
        "--cache", type=str, default="",
        help="Path to a cache thread directory (e.g. data/tmp/.cache/<thread_id>). "
             "Auto-finds synthesis_vN.json inside.",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Output directory. Default: data/output/test_artifacts/",
    )
    parser.add_argument(
        "--skip-charts", action="store_true",
        help="Skip chart generation; reuse existing chart PNGs from output dir.",
    )
    parser.add_argument(
        "--blueprint-only", action="store_true",
        help="Only dump the deck blueprint JSON (no PPTX/DOCX generation).",
    )
    args = parser.parse_args()

    # ── Resolve synthesis source ──
    synthesis_arg = args.synthesis

    # --cache: point to a thread cache dir and auto-find synthesis file
    if args.cache and not synthesis_arg:
        cache_dir = Path(args.cache)
        if not cache_dir.is_absolute():
            cache_dir = ROOT / cache_dir
        found = find_synthesis_in_cache(cache_dir)
        if found:
            synthesis_arg = str(found)
            logger.info("Auto-found synthesis in cache dir: %s", found)
        else:
            logger.warning("No synthesis_v*.json found in --cache dir: %s", cache_dir)

    # ── Resolve state file (only needed when not using --synthesis/--cache directly) ──
    state: dict = {}
    thread_id = "test_artifacts"

    if not synthesis_arg:
        if args.state:
            state_path = Path(args.state)
            if not state_path.is_absolute():
                state_path = ROOT / state_path
        else:
            state_path = _latest_state_file()
        logger.info("Loading state: %s", state_path)
        state = load_state(state_path)
        thread_id = state_path.stem
    else:
        # Derive thread_id from synthesis path (parent dir name)
        thread_id = Path(synthesis_arg).parent.name or "test_artifacts"

    # ── Load synthesis data (from file, not state dict) ──
    synthesis = load_synthesis(synthesis_arg, state)

    # ── Resolve output dir ──
    if args.output:
        output_dir = Path(args.output)
        if not output_dir.is_absolute():
            output_dir = ROOT / output_dir
    else:
        output_dir = Path(DATA_OUTPUT_DIR) / "test_artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output dir: %s", output_dir)

    # Log synthesis summary
    themes = synthesis.get("themes", [])
    findings = synthesis.get("findings", [])
    logger.info(
        "Synthesis: %d themes, %d findings, decision=%s, confidence=%s",
        len(themes), len(findings),
        synthesis.get("decision", "n/a"),
        synthesis.get("confidence", "n/a"),
    )

    # ── 1. Deck blueprint ──
    logger.info("Building deck blueprint from synthesis...")
    blueprints = build_deck_blueprint(synthesis)
    bp_path = output_dir / "deck_blueprint.json"
    bp_path.write_text(json.dumps(blueprints, indent=2, default=str), encoding="utf-8")
    logger.info("Blueprint JSON -> %s  (%d sections, %d total slides)",
                bp_path,
                len(blueprints),
                sum(len(s.get("slides", [])) for s in blueprints))

    if args.blueprint_only:
        print(f"\nBlueprint saved to: {bp_path}")
        return

    # ── 2. Charts ──
    chart_paths: dict[str, str] = {}
    if args.skip_charts:
        # Try to find existing charts in output or cache dir
        for chart_dir in [output_dir / "charts", Path(DATA_CACHE_DIR) / thread_id]:
            if chart_dir.exists():
                for png in chart_dir.glob("*.png"):
                    chart_paths[png.stem] = str(png)
        logger.info("Reusing %d existing chart(s): %s", len(chart_paths), list(chart_paths.keys()))
    else:
        logger.info("Generating charts...")
        chart_paths = generate_charts(synthesis, output_dir)

    # ── 3. Narrative markdown ──
    narrative = get_narrative_markdown(state, thread_id)
    md_path = output_dir / "complete_analysis.md"
    md_path.write_text(narrative, encoding="utf-8")
    logger.info("Narrative MD -> %s  (%d chars)", md_path, len(narrative))

    # ── 4. PPTX ──
    logger.info("Generating PPTX...")
    pptx_path = generate_pptx(blueprints, chart_paths, output_dir)

    # ── 5. DOCX ──
    logger.info("Generating DOCX...")
    docx_path = generate_docx(narrative, output_dir)

    # ── Summary ──
    print("\n" + "=" * 60)
    print("ARTIFACT GENERATION COMPLETE")
    print("=" * 60)
    print(f"  Synthesis    : {synthesis_arg or state.get('synthesis_path', 'from state')}")
    print(f"  Blueprint    : {bp_path}")
    print(f"  Charts       : {len(chart_paths)} files in {output_dir / 'charts'}")
    print(f"  Narrative MD : {md_path}")
    print(f"  PPTX         : {pptx_path}")
    print(f"  DOCX         : {docx_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()

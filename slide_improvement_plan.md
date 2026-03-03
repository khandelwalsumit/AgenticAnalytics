# Slide Formatting Improvement Plan

## Problem Summary

Your current pipeline (Narrative Agent → Formatting Agent → PPTX Builder) produces slides that are **data-complete but visually flat**. The formatting agent outputs a JSON blueprint, but the PPTX builder renders it as generic bullet lists with no visual hierarchy, no spatial design, and no distinction between slide types. Every slide looks the same regardless of whether it's a hook, a matrix, or a theme card.

---

## The Root Cause: Missing "Rendering Layer"

Your pipeline has a gap between the **Formatting Agent's JSON** and the **PPTX Builder's rendering logic**. The Formatting Agent defines *what* goes on each slide (content + element types), but nobody defines *how* it should look spatially. The `template_extractor.py` maps placeholder indices, but it doesn't control visual design — it just says "put text in placeholder 1."

**The fix is a two-part intervention:**

1. **Redesign the PPTX builder** to use `pptxgenjs` with hand-crafted slide master layouts (not template placeholders) — giving you pixel-level control over fonts, colors, spacing, tables, and two-column layouts.
2. **Tighten the Formatting Agent's output contract** so each slide type emits a predictable, render-ready JSON structure that the builder can map 1:1 to a visual layout.

---

## Slide-by-Slide Redesign Spec

### 1. Executive Summary — "Hook" Slide

**Current problem:** Generic title + subtitle. No urgency. Looks like a chapter heading.

**Target layout:**
```
┌─────────────────────────────────────────────────┐
│  [Dark navy background: 003B70]                 │
│                                                 │
│  [Large white text, 36pt, bold]                 │
│  "96 Calls. 3 Root Causes. 1 Quarter to Fix."   │
│                                                 │
│  [Thin horizontal rule — white, 50% opacity]    │
│                                                 │
│  [Light gray text, 14pt]                        │
│  "Analysis of 96 customer calls across Rewards, │
│   Payments, and Account Management segments"     │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Changes needed:**

| Component | Change |
|-----------|--------|
| `narrative_agent.md` | No change — hook content is already good |
| `formatting_agent.md` | Emit `slide_role: "hook"` with `title` + `subtitle` only — no bullets |
| PPTX Builder | New `renderHook()` function: dark bg, centered white title 36pt, separator line, gray subtitle 14pt |

---

### 2. Critical Pain Points Slide

**Current problem:** 3 pain points crammed into one slide as a wall of bullets. No visual separation between pain points.

**Target layout:**
```
┌────────────────────────────────────────────────────┐
│  Title: "3 Pain Points Drive 78% of Call Volume"   │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ [accent  │  │ [accent  │  │ [accent  │         │
│  │  bar     │  │  bar     │  │  bar     │         │
│  │  left]   │  │  left]   │  │  left]   │         │
│  │          │  │          │  │          │         │
│  │ PP#1     │  │ PP#2     │  │ PP#3     │         │
│  │ Title    │  │ Title    │  │ Title    │         │
│  │ 14 calls │  │ 12 calls │  │ 8 calls  │         │
│  │          │  │          │  │          │         │
│  │ Issue:   │  │ Issue:   │  │ Issue:   │         │
│  │ ...      │  │ ...      │  │ ...      │         │
│  │ Fix:     │  │ Fix:     │  │ Fix:     │         │
│  │ ...      │  │ ...      │  │ ...      │         │
│  └──────────┘  └──────────┘  └──────────┘         │
└────────────────────────────────────────────────────┘
```

**Three equal-width cards** with a left accent bar (colored by priority: red/amber/blue). Each card:
- Pain point name (bold, 16pt)
- Call count + % badge (small, muted)
- "Issue:" label + 1-2 sentence description
- "Fix:" label + verb-first action
- "Owner:" Digital/Ops/Comms tag at bottom

**Changes needed:**

| Component | Change |
|-----------|--------|
| `formatting_agent.md` | Emit `pain_points` as an array of 3 objects, each with `{name, calls, pct, issue, fix, owner}` — NOT as flat bullets |
| PPTX Builder | New `renderPainPointCards()`: 3-column card layout with accent bars, structured text per card |

---

### 3. Impact vs Ease Matrix Slide

**Current problem:** Markdown table converted to a basic PPTX table. No visual prioritization. No chart.

**Target layout:**
```
┌─────────────────────────────────────────────────────┐
│  Title: "Impact vs. Ease — Full Theme Prioritization"│
│                                                     │
│  ┌─────────────────────────┐  ┌──────────────────┐  │
│  │  TABLE (left ~60%)      │  │  SCATTER CHART   │  │
│  │                         │  │  (right ~40%)    │  │
│  │  Theme | Vol | Top      │  │                  │  │
│  │        |     | Issue    │  │  x=Ease y=Impact │  │
│  │  ------+-----+-----    │  │  bubble=volume   │  │
│  │  row 1 (dark header,   │  │                  │  │
│  │   alternating rows)    │  │  color-coded per │  │
│  │  row 2                 │  │  theme            │  │
│  │  row 3                 │  │                  │  │
│  │                         │  │                  │  │
│  └─────────────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**Table styling:**
- Header row: navy bg `003B70`, white text, 11pt bold
- Body rows: alternating white / light gray `F5F7FA`
- Priority score column: color-coded (green >7, amber 5-7, red <5)
- Columns: Theme | Volume | Top Issue | Solution | Ease | Impact | Priority

**Changes needed:**

| Component | Change |
|-----------|--------|
| `formatting_agent.md` | Already outputs table + chart_placeholder — ensure table `rows` include ALL 7 columns consistently |
| PPTX Builder | `renderImpactMatrix()`: two-column layout, styled table left (addTable with header fill, alternating rows), chart image right |
| Chart generation | Ensure scatter/bubble chart is generated upstream and path passed through |

---

### 4. The Biggest Bet Slide

**Current problem:** Just a blockquote in markdown, rendered as a regular bullet slide. No visual impact.

**Target layout:**
```
┌────────────────────────────────────────────────┐
│  [Dark bg: 003B70]                             │
│                                                │
│         ┌─────────────────────────┐            │
│         │  [Big number, 60pt]     │            │
│         │  "37 calls"             │            │
│         │  [white, bold]          │            │
│         └─────────────────────────┘            │
│                                                │
│  [Accent color text, 20pt]                     │
│  "Rewards & Loyalty"                           │
│                                                │
│  [White text, 16pt]                            │
│  "Fixing the top 3 drivers alone deflects 37   │
│   calls (38.5% of volume) — achievable within  │
│   one quarter."                                │
│                                                │
└────────────────────────────────────────────────┘
```

**Changes needed:**

| Component | Change |
|-----------|--------|
| `formatting_agent.md` | New structured output for `biggest_bet`: `{theme_name, call_count, pct, deflection_statement}` |
| `narrative_agent.md` | Already produces this — no change needed |
| PPTX Builder | `renderBiggestBet()`: dark slide, large centered stat, theme name in accent color, context sentence below |

---

### 5. Recommendations by Owning Team

**Current problem:** Four dimension groups rendered as flat bullets — no visual grouping.

**Target layout:**
```
┌──────────────────────────────────────────────────┐
│  Title: "Recommended Actions by Owning Team"      │
│                                                  │
│  ┌──────────────────┐  ┌──────────────────┐      │
│  │ ■ Digital / UX   │  │ ■ Operations     │      │
│  │   [blue accent]  │  │   [green accent] │      │
│  │                  │  │                  │      │
│  │ • Build unified  │  │ • Automate       │      │
│  │   rewards dash   │  │   crediting SLA  │      │
│  │   → 12 calls     │  │   → 8 calls      │      │
│  │                  │  │                  │      │
│  │ • Add transfer   │  │                  │      │
│  │   tracker        │  │                  │      │
│  │   → 4 calls      │  │                  │      │
│  └──────────────────┘  └──────────────────┘      │
│  ┌──────────────────┐  ┌──────────────────┐      │
│  │ ■ Communications │  │ ■ Policy         │      │
│  │   [orange accent]│  │   [purple accent]│      │
│  │                  │  │                  │      │
│  │ • Publish SLA    │  │ • Enforce 48-hr  │      │
│  │   expectations   │  │   crediting rule │      │
│  │   → 6 calls      │  │   → 5 calls      │      │
│  └──────────────────┘  └──────────────────┘      │
└──────────────────────────────────────────────────┘
```

**2×2 grid** of dimension cards. Each card has:
- Dimension name with colored square icon
- 1-2 consolidated actions (bold action title + impact line)

**Changes needed:**

| Component | Change |
|-----------|--------|
| `formatting_agent.md` | Emit `recommendations` as `{dimensions: [{name, color, actions: [{title, detail, calls}]}]}` — structured, not flat bullets |
| PPTX Builder | `renderRecommendations()`: 2×2 card grid with per-dimension accent colors |

---

### 6. Theme Deep-Dive Cards (YOUR EXAMPLE)

**Current problem:** Theme cards rendered as a scorecard line + bullets + table, all left-aligned. No two-column split. No visual hierarchy between scorecard, narrative, and driver data.

**Target layout (matching your example):**
```
┌──────────────────────────────────────────────────────┐
│  [Theme Name]                            [bold, 24pt]│
│  Calls: 14 | Impact: 8 | Ease: 7 | Priority: 7.6   │
│  [muted gray text, 11pt — stats bar]                 │
│                                                      │
│  ┌─────────── LEFT (60%) ──────┐ ┌── RIGHT (40%) ──┐│
│  │                             │ │                  ││
│  │  CORE ISSUE          [h3]  │ │ ┌──────────────┐ ││
│  │  2-3 sentence summary of   │ │ │ Driver Table │ ││
│  │  the theme and actionable  │ │ │              │ ││
│  │  core issue                │ │ │ Driver | Vol │ ││
│  │                             │ │ │ ------+-----│ ││
│  │  PRIMARY DRIVER      [h3]  │ │ │ Drv 1 |  8  │ ││
│  │  description of what's     │ │ │ Drv 2 |  4  │ ││
│  │  driving the calls         │ │ │ Drv 3 |  2  │ ││
│  │                             │ │ │              │ ││
│  │  SOLUTIONS           [h3]  │ │ └──────────────┘ ││
│  │  1. Solution one [Digital] │ │                  ││
│  │  2. Solution two [Ops]     │ │                  ││
│  │  3. Solution three [Comms] │ │                  ││
│  │                             │ │                  ││
│  └─────────────────────────────┘ └──────────────────┘│
└──────────────────────────────────────────────────────┘
```

**This is the biggest change.** Your Formatting Agent currently outputs theme cards as a flat list of elements. It needs to emit a structured object that the PPTX builder can map to a two-column layout.

**Changes needed:**

| Component | Change |
|-----------|--------|
| `formatting_agent.md` | **Major restructure** — see detailed spec below |
| `narrative_agent.md` | Add explicit `<!-- SLIDE -->` content for "Core Issue" and "Primary Driver" as distinct subsections within each theme |
| `template_extractor.py` | Update `section_map.theme_deep_dives` to reflect new two-column layout spec |
| PPTX Builder | `renderThemeCard()`: two-column layout with stats bar, left narrative, right driver table |

---

## Detailed Change Specs

### A. Formatting Agent — New Theme Card JSON Contract

Replace the current theme card output with this structure:

```json
{
  "slide_role": "theme_card",
  "layout_index": 19,
  "title": "Rewards & Loyalty",
  "stats_bar": {
    "calls": 14,
    "pct": "14.6%",
    "impact": 8,
    "ease": 7,
    "priority": 7.6
  },
  "left_column": {
    "core_issue": "Customers cannot see pending points, earn rates, or transfer status — forcing them to call for information that should be self-service.",
    "primary_driver": "Points crediting exceeds the 48-hour SLA with no visibility into processing status, generating 8 of 14 calls in this theme.",
    "solutions": [
      {"action": "Build pending points tracker with real-time status", "dimension": "Digital"},
      {"action": "Enforce 48-hour crediting SLA via automated pipeline", "dimension": "Ops"},
      {"action": "Send proactive push notification on points credit", "dimension": "Comms"}
    ]
  },
  "right_column": {
    "type": "driver_table",
    "headers": ["Driver", "Calls"],
    "rows": [
      ["Points crediting delay", 8],
      ["Earn rate confusion", 4],
      ["Transfer status unknown", 2]
    ]
  }
}
```

### B. Formatting Agent — New Biggest Bet JSON

```json
{
  "slide_role": "biggest_bet",
  "layout_index": 37,
  "theme_name": "Rewards & Loyalty",
  "stat_number": "37 calls",
  "stat_pct": "38.5%",
  "narrative": "Fixing the top 3 drivers alone deflects 37 calls (38.5% of total volume) and is achievable within one quarter."
}
```

### C. Formatting Agent — New Pain Points JSON

```json
{
  "slide_role": "pain_points",
  "layout_index": 1,
  "title": "3 Pain Points Drive 78% of Call Volume",
  "cards": [
    {
      "name": "Rewards Crediting",
      "calls": 14,
      "pct": "14.6%",
      "priority": 7.6,
      "issue": "Points crediting is failing its 48-hour SLA. Customers have no visibility into processing status.",
      "fix": "Add pending-points tracker in mobile app with push notifications at each processing stage.",
      "owner": "Digital/UX"
    },
    { "..." : "..." },
    { "..." : "..." }
  ]
}
```

### D. Formatting Agent — New Recommendations JSON

```json
{
  "slide_role": "recommendations",
  "layout_index": 1,
  "title": "Recommended Actions by Owning Team",
  "dimensions": [
    {
      "name": "Digital / UX",
      "accent_color": "006BA6",
      "actions": [
        {"title": "Build unified rewards transparency dashboard", "detail": "Resolves 12 calls across Rewards & Loyalty", "calls": 12},
        {"title": "Add real-time transfer status tracker", "detail": "Eliminates 4 status-check calls", "calls": 4}
      ]
    },
    {
      "name": "Operations",
      "accent_color": "2C5F2D",
      "actions": [
        {"title": "Automate crediting pipeline with 2-hour SLA", "detail": "Resolves 8 calls from SLA breaches", "calls": 8}
      ]
    }
  ]
}
```

---

## Changes per File — Summary

### `narrative_agent.md`

| # | Change | Why |
|---|--------|-----|
| 1 | In Section 4 (Theme Deep Dives), add explicit `## Core Issue` and `## Primary Driver` sub-headings within each theme narrative block | Gives the Formatting Agent clean boundaries to extract structured content from |
| 2 | In the theme template, add a `## Solutions` sub-section that lists solutions with `[Digital]`, `[Ops]`, `[Comms]`, `[Policy]` dimension tags inline | So the formatter can parse dimension ownership per solution |
| 3 | Limit solutions per theme to **max 3** — add rule: "List at most 3 solutions per theme, prioritized by impact. Do not pad with weak solutions." | Prevents slide overcrowding |

### `formatting_agent.md`

| # | Change | Why |
|---|--------|-----|
| 1 | **Replace flat element arrays** with structured JSON per slide type (see specs above) | Gives the PPTX builder deterministic field access — no guessing what `elements[3]` contains |
| 2 | Add a `stats_bar` object to every theme card | Enables the builder to render the gray stats line below the title without parsing callout text |
| 3 | Add `left_column` / `right_column` to theme cards | Enables true two-column rendering |
| 4 | Add `cards` array to pain points slide | Enables three-column card layout |
| 5 | Add `dimensions` array to recommendations slide | Enables 2×2 grid layout |
| 6 | Add `biggest_bet` as its own slide type with `stat_number`, `stat_pct`, `narrative` | Enables the big-number callout slide |
| 7 | Remove the generic `elements` approach for these 5 slide types — keep `elements` only for generic/fallback slides | Reduces ambiguity in the builder |

### `template_extractor.py`

| # | Change | Why |
|---|--------|-----|
| 1 | In `_build_section_map`, update `theme_deep_dives.per_theme_slide` to document the two-column contract: left = narrative, right = driver table | Source of truth alignment |
| 2 | Add a `biggest_bet` section to the section_map | Currently missing — it's nested inside `impact` but deserves its own layout spec |
| 3 | Add `pain_points` as a distinct section in the map with `card_count: 3` and card-level placeholder spec | Currently the pain points layout is not formally specified |

### `report_tools.py` — `export_to_pptx`

| # | Change | Why |
|---|--------|-----|
| 1 | **Replace `markdown_to_pptx` fallback** with a `pptxgenjs`-based renderer that reads the structured JSON | The markdown fallback produces flat bullet slides — it's the primary quality bottleneck |
| 2 | Build 6 render functions: `renderHook`, `renderPainPointCards`, `renderImpactMatrix`, `renderBiggestBet`, `renderRecommendations`, `renderThemeCard` | Each slide type gets its own visual logic |
| 3 | Use a shared color palette and font config derived from `visual_hierarchy` in the template catalog | Consistency across all slides |

### `report_analyst.md`

| # | Change | Why |
|---|--------|-----|
| 1 | No major changes needed | This agent just orchestrates artifact generation — the quality improvement is upstream |
| 2 | Minor: add a check that the Formatting Agent's JSON was used (not the markdown fallback) before marking PPTX as complete | Prevents fallback to the low-quality path |

---

## Visual Design Spec (Color Palette + Typography)

Use this across all slides — defined once in the PPTX builder config:

```
Primary:     003B70  (navy — titles, headers, dark bg slides)
Secondary:   006BA6  (blue — accent, callout stats)
Light bg:    F5F7FA  (off-white — content slide backgrounds)
Dark bg:     003B70  (navy — hook, biggest bet, dividers)
Text:        333333  (body text)
Muted:       888888  (stats bar, secondary info)
Accent-Red:  C0392B  (high-priority markers)
Accent-Amber:E67E22  (medium-priority markers)
Accent-Green:27AE60  (low-effort/quick-win markers)

Font:        Calibri (already in your visual_hierarchy — keep it)
Title:       28pt bold
Body:        13-14pt
Stats bar:   11pt, color 888888
Table header:11pt bold, white on navy
Table body:  10pt, alternating white/F5F7FA
```

---

## Implementation Priority

| Phase | What | Effort | Impact |
|-------|------|--------|--------|
| **Phase 1** | Restructure Formatting Agent JSON output for theme cards + biggest bet | Medium | **Highest** — unblocks all visual improvements |
| **Phase 2** | Build `pptxgenjs` renderer with 6 slide-type functions | High | **Highest** — this is where the visual quality lives |
| **Phase 3** | Update Narrative Agent with Core Issue / Primary Driver / Solutions sub-sections | Low | Medium — cleaner input to formatter |
| **Phase 4** | Update template_extractor to reflect new layout contracts | Low | Low — mostly documentation alignment |
| **Phase 5** | Visual QA loop — generate → screenshot → fix | Medium | High — catches rendering bugs |

---

## Key Principle

**The formatting agent should output render-ready structured data, not prose elements that the builder has to interpret.** Every slide type should have a fixed JSON schema that maps 1:1 to a visual layout function. The builder should never have to "figure out" what an element is — it reads `slide_role` and calls the right renderer with typed fields.

This is the single biggest architectural change: moving from `elements: [{type: "bullet", text: "..."}]` to `stats_bar: {calls: 14, impact: 8}` + `left_column: {core_issue: "...", solutions: [...]}`.

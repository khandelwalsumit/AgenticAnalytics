# PPTX Slide Renderer — Full Implementation Spec

## Global Constants

```
SLIDE_WIDTH:  10 inches
SLIDE_HEIGHT: 5.625 inches (16:9)

MARGIN_LEFT:   0.5
MARGIN_RIGHT:  0.5
MARGIN_TOP:    0.4
MARGIN_BOTTOM: 0.3

CONTENT_WIDTH: 9.0  (10 - 0.5 - 0.5)
```

### Color Palette

```
NAVY:         "003B70"    — slide titles, dark backgrounds
BLUE_ACCENT:  "006BA6"    — h3 labels, accent text, links
LIGHT_BLUE:   "E8F0FE"    — subtle highlight backgrounds
BLACK:        "222222"    — body text
DARK_GRAY:    "444444"    — secondary body text
MID_GRAY:     "888888"    — stats bar, muted metadata
LIGHT_GRAY:   "D0D0D0"    — horizontal rules, table borders
BG_LIGHT:     "F5F7FA"    — alternating table rows, card fills
WHITE:        "FFFFFF"    — white text on dark, card backgrounds

ACCENT_RED:    "C0392B"   — high priority accent bars
ACCENT_AMBER:  "E67E22"   — medium priority accent bars
ACCENT_GREEN:  "27AE60"   — low priority / quick win accent bars
ACCENT_PURPLE: "8E44AD"   — policy dimension accent

DIMENSION_COLORS:
  "Digital / UX":    "006BA6"  (blue)
  "Operations":      "27AE60"  (green)
  "Communications":  "E67E22"  (orange)
  "Policy":          "8E44AD"  (purple)
```

### Typography

```
FONT: "Calibri"  — used everywhere, no exceptions

SLIDE_TITLE:    { fontSize: 22, bold: true,  color: NAVY,       fontFace: "Calibri" }
SUBTITLE_TEXT:  { fontSize: 13, bold: false, color: DARK_GRAY,  fontFace: "Calibri" }
H3_LABEL:       { fontSize: 14, bold: true,  color: BLUE_ACCENT,fontFace: "Calibri" }
BODY_TEXT:      { fontSize: 11, bold: false, color: BLACK,       fontFace: "Calibri" }
BOLD_BODY:      { fontSize: 11, bold: true,  color: BLACK,       fontFace: "Calibri" }
STATS_TEXT:     { fontSize: 10, bold: false, color: MID_GRAY,    fontFace: "Calibri" }
SMALL_MUTED:    { fontSize: 9,  bold: false, color: MID_GRAY,    fontFace: "Calibri" }
BIG_NUMBER:     { fontSize: 48, bold: true,  color: NAVY,        fontFace: "Calibri" }

TABLE_HEADER:   { fontSize: 10, bold: true,  color: WHITE,      fontFace: "Calibri" }
TABLE_CELL:     { fontSize: 9,  bold: false, color: BLACK,      fontFace: "Calibri" }

BULLET_TITLE:   { fontSize: 12, bold: true,  color: BLUE_ACCENT,fontFace: "Calibri" }
BULLET_BODY:    { fontSize: 11, bold: false, color: BLACK,       fontFace: "Calibri" }
```

### Shared Element Helpers

**Horizontal rule:** A thin rectangle shape used as a visual separator.
```
Shape: RECTANGLE
Height: 0.01 inches
Color: LIGHT_GRAY
Transparency: 20%
Full content width (MARGIN_LEFT to MARGIN_LEFT + CONTENT_WIDTH)
```

**Slide title block:** Every content slide (not the hook) starts with:
```
Title text:  x=0.5, y=0.3, w=9.0, h=0.4
             SLIDE_TITLE style
Rule below:  x=0.5, y=0.72, w=9.0, h=0.01
             LIGHT_GRAY fill
```
This leaves content area starting at y=0.85.

---

## Slide Type 1: Executive Summary

**`slide_role: "executive_summary"`**

**Background:** WHITE

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ y=0.3   TITLE: "EXECUTIVE SUMMARY"                      │
│ y=0.72  ──────────────────────────── (gray rule)         │
│ y=0.90  subtitle text (1-2 sentences, what was analyzed) │
│ y=1.35  ──────────────────────────── (gray rule)         │
│                                                         │
│ y=1.55  "Quick Wins:" (blue, h3)                        │
│ y=1.85  • Quick win 1 (bold title + detail)             │
│ y=2.35  • Quick win 2                                   │
│ y=2.85  • Quick win 3                                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Elements to render:**

1. **Title** — `"EXECUTIVE SUMMARY"` in SLIDE_TITLE style
   - `x: 0.5, y: 0.3, w: 9.0, h: 0.4`
   - All caps

2. **Rule 1** — gray line below title
   - `x: 0.5, y: 0.72, w: 9.0, h: 0.01`

3. **Subtitle block** — 3-4 lines covering: what was analyzed, key issues summary, and prevention potential
   - Render as a single text box with rich text array:
     - For each line in `subtitle_lines`, create text runs separated by `breakLine: true`
     - If `bold_part` is not null, split the line text around the `bold_part` string and render that substring as `{ bold: true, color: BLUE_ACCENT }` inline within the sentence
     - All other text renders as SUBTITLE_TEXT (12pt, DARK_GRAY)
   - `x: 0.5, y: 0.85, w: 9.0, h: 0.85`
   - `valign: "top"`, `paraSpaceAfter: 2`

4. **Rule 2** — gray line below subtitle
   - `x: 0.5, y: 1.72, w: 9.0, h: 0.01`

5. **"Quick Wins:" label**
   - `x: 0.5, y: 1.88, w: 9.0, h: 0.3`
   - H3_LABEL style (blue, bold, 14pt)

6. **Quick win items** — render as rich text array, each item is:
   - Bold title (BULLET_TITLE style) + line break + detail text (BODY_TEXT style)
   - Use `bullet: true` for each item
   - `x: 0.5, y: 2.20, w: 9.0, h: 2.8`
   - `paraSpaceAfter: 10` between items
   - Each item format: **"Verb-first action title"** \n "Theme — resolves ~X calls | reason it's fast"

**Input JSON shape:**
```json
{
  "slide_role": "executive_summary",
  "title": "EXECUTIVE SUMMARY",
  "subtitle_lines": [
    { "text": "Analysis of 96 friction-related customer calls across 6 themes — Citi Rewards & Banking, Q4 2024.", "bold_part": null },
    { "text": "Three root causes — rewards visibility gaps, silent transfer failures, and authentication dead-ends — drive 72% of all contacts. These are system-created calls: the product generates the friction it then has to service.", "bold_part": null },
    { "text": "27% of total volume is deflectable with easy implementations (ease score ≥8) that require no backend changes and can ship within 2-3 weeks.", "bold_part": "27%" }
  ],
  "quick_wins": [
    {
      "action": "Automate balance-check IVR fallback",
      "detail": "Account Access — resolves ~18 calls | Config-only change, no code deploy needed"
    }
  ]
}
```

---

## Slide Type 2: Critical Pain Points

**`slide_role: "pain_points"`**

**Background:** WHITE

**Layout — 3 equal-width cards side by side:**
```
CARD_WIDTH:   2.75 inches
CARD_HEIGHT:  4.0 inches
CARD_GAP:     0.25 inches between cards
CARD_START_X: 0.625  (centered: (10 - 3*2.75 - 2*0.25) / 2)
CARD_START_Y: 0.95
ACCENT_BAR_W: 0.06 inches (thin left border on each card)
```

**Per card positions (card index 0, 1, 2):**
```
card_x = 0.625 + (index * (2.75 + 0.25))

Accent bar:   x=card_x, y=0.95, w=0.06, h=4.0
Card bg:      x=card_x+0.06, y=0.95, w=2.69, h=4.0  (BG_LIGHT fill)

Inside card (relative to card_x + 0.06, padded 0.15 from edges):
  inner_x = card_x + 0.22
  inner_w = 2.38

  Title:       y=1.05, h=0.35   — theme name + "(X calls)" — BOLD_BODY 12pt bold, NAVY color
  Stats line:  y=1.40, h=0.25   — "Impact: X | Priority: X.X" — STATS_TEXT 9pt, MID_GRAY
  Separator:   y=1.65, w=inner_w, h=0.005 — LIGHT_GRAY
  Issue label: y=1.75, h=0.2    — "Issue:" — BOLD_BODY, BLACK
  Issue text:  y=1.95, h=0.85   — 2-3 line description — BODY_TEXT 10pt
  Fix label:   y=2.85, h=0.2    — "Fix:" — BOLD_BODY, BLACK
  Fix text:    y=3.05, h=0.75   — 1-2 line fix + "(Owner)" — BODY_TEXT 10pt
```

**Accent bar colors by card position:**
- Card 1 (highest volume): `ACCENT_RED` ("C0392B")
- Card 2: `ACCENT_AMBER` ("E67E22")
- Card 3: `ACCENT_GREEN` ("27AE60")

**Elements to render per card:**

1. **Accent bar** — tall thin RECTANGLE on the left edge
   - Fill: accent color based on position
   - `x: card_x, y: 0.95, w: 0.06, h: 4.0`

2. **Card background** — RECTANGLE
   - Fill: BG_LIGHT
   - `x: card_x + 0.06, y: 0.95, w: 2.69, h: 4.0`

3. **Card title** — theme name with call count
   - Rich text: `[{text: "Theme Name", bold: true}, {text: " (14 calls)", bold: false}]`
   - fontSize: 12, color: NAVY
   - `x: inner_x, y: 1.05, w: inner_w, h: 0.35`

4. **Stats line** — impact + priority scores
   - `"Impact: 8 | Priority: 7.6"`
   - STATS_TEXT style (9pt, MID_GRAY)
   - `x: inner_x, y: 1.40, w: inner_w, h: 0.25`

5. **Separator** — thin line
   - `x: inner_x, y: 1.65, w: inner_w, h: 0.005, fill: LIGHT_GRAY`

6. **"Issue:" label + text** — as rich text array
   - `[{text: "Issue: ", bold: true, fontSize: 11}, {text: "description...", bold: false, fontSize: 10}]`
   - color: BLACK
   - `x: inner_x, y: 1.75, w: inner_w, h: 1.05`

7. **"Fix:" label + text** — as rich text array
   - `[{text: "Fix: ", bold: true, fontSize: 11}, {text: "action... ", bold: false, fontSize: 10}, {text: "(Digital/UX)", bold: true, fontSize: 9, color: BLUE_ACCENT}]`
   - `x: inner_x, y: 2.85, w: inner_w, h: 0.95`

**Input JSON shape:**
```json
{
  "slide_role": "pain_points",
  "title": "3 Pain Points Drive 78% of Call Volume",
  "cards": [
    {
      "name": "Rewards Crediting",
      "calls": 14,
      "pct": "14.6%",
      "impact": 8,
      "priority": 7.6,
      "issue": "Points crediting is failing its 48-hour SLA with no visibility into processing status. Customers call to ask where their points are because there is no self-serve tracker.",
      "fix": "Add pending-points tracker in mobile app with push notifications at each processing stage.",
      "owner": "Digital/UX"
    }
  ]
}
```

---

## Slide Type 3: Impact vs. Ease

**`slide_role: "impact_ease"`**

**Background:** WHITE

**Layout — left text list (58%) + right scatter chart (38%):**
```
LEFT_X:      0.5
LEFT_W:      5.5
RIGHT_X:     6.2
RIGHT_W:     3.5
RIGHT_H:     4.2
CONTENT_Y:   0.95
```

**Left side — theme summary list (repeat for up to 10 themes, sorted by priority desc):**

For each theme (stacked vertically, ~0.40 inches per theme):
```
theme_y = 0.95 + (index * 0.42)

Line 1: Bold theme name + " — " + quadrant label
         fontSize: 11, bold: true, color: NAVY
         Followed by non-bold quadrant text in MID_GRAY
         
Line 2: "Calls: X | Impact: X | Ease: X | Priority: X.X"
         fontSize: 9, color: MID_GRAY
```

Render as a single text box with rich text array:
- Each theme = 2 text runs with `breakLine: true`
- `x: 0.5, y: 0.95, w: 5.5, h: 4.2`
- `paraSpaceAfter: 6`
- `valign: "top"`

**Quadrant labels** (derive from scores):
- Impact ≥ 7 AND Ease ≥ 7 → "Quick Win"
- Impact ≥ 7 AND Ease < 7 → "Strategic Bet"
- Impact < 7 AND Ease ≥ 7 → "Easy Fix"
- Impact < 7 AND Ease < 7 → "Deprioritize"

**Right side — Scatter/Bubble chart:**

Use `pptxgenjs` built-in chart:
```javascript
slide.addChart(pres.charts.SCATTER, chartData, {
  x: 6.2, y: 0.85, w: 3.5, h: 4.2,
  showTitle: false,
  catAxisTitle: "Ease →",
  valAxisTitle: "Impact →",
  catAxisMinVal: 0, catAxisMaxVal: 10,
  valAxisMinVal: 0, valAxisMaxVal: 10,
  catAxisLabelColor: "888888",
  valAxisLabelColor: "888888",
  catAxisLabelFontSize: 8,
  valAxisLabelFontSize: 8,
  catGridLine: { color: "E8E8E8", size: 0.5 },
  valGridLine: { color: "E8E8E8", size: 0.5 },
  chartColors: ["006BA6", "27AE60", "E67E22", "C0392B", "8E44AD", "2C5F2D", "D4A017", "4A90D9", "C06090", "607D8B"],
  dataLabelPosition: "t",
  showSerName: true,
  dataLabelFontSize: 7,
  dataLabelColor: "444444",
  lineSize: 0,
  showMarker: true,
  markerSize: 12
});
```

Chart data: each theme is a separate series (so each dot gets its own color + label):
```javascript
const chartData = themes.map((t, i) => ({
  name: t.name,
  values: [{ x: t.ease, y: t.impact }]
}));
```

**Input JSON shape:**
```json
{
  "slide_role": "impact_ease",
  "title": "Impact vs. Ease — Full Theme Prioritization",
  "themes": [
    {
      "name": "Rewards & Loyalty",
      "calls": 14,
      "impact": 8,
      "ease": 7,
      "priority": 7.6,
      "quadrant": "Quick Win"
    }
  ]
}
```

---

## Slide Type 4: Low Hanging Fruit

**`slide_role: "low_hanging_fruit"`**

**Background:** WHITE

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│ y=0.3   TITLE: "Low Hanging Fruit"                   │
│ y=0.72  ──────────────────────────── (gray rule)     │
│                                                     │
│ y=0.95  Item 1: bold blue title (14pt)              │
│ y=1.20  - Elaborated solution (11pt, black)         │
│ y=1.45  - Resolves ~X calls (Y%) (11pt, MID_GRAY)  │
│                                                     │
│ y=1.85  Item 2: bold blue title                     │
│ y=2.10  - Elaborated solution                       │
│ y=2.35  - Resolves ~X calls                         │
│                                                     │
│ y=2.75  Item 3: bold blue title                     │
│ y=3.00  - Elaborated solution                       │
│ y=3.25  - Resolves ~X calls                         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

Render as a single text box with rich text runs:

For each item (max 3), the text runs are:
```
{ text: "1. Action title here", bold: true, fontSize: 13, color: BLUE_ACCENT, breakLine: true }
{ text: "    Elaborated description of the solution and what it changes", fontSize: 11, color: BLACK, breakLine: true, bullet: false }
{ text: "    Resolves ~X calls (Y% of volume)", fontSize: 10, color: MID_GRAY, breakLine: true, bullet: false }
{ text: "", breakLine: true }  // spacer between items
```

Position: `x: 0.5, y: 0.95, w: 9.0, h: 4.0, valign: "top"`

**Selection logic:** Pick the 3 solutions with the **highest ease score** from across all themes. These are the "ship on Monday" fixes.

**Input JSON shape:**
```json
{
  "slide_role": "low_hanging_fruit",
  "title": "Low Hanging Fruit",
  "items": [
    {
      "action": "Publish transfer-limit FAQ in help center",
      "detail": "Create a dedicated FAQ page showing daily and per-transaction limits for all transfer types. Link it from the transfer initiation screen and error messages.",
      "impact": "Resolves ~8 calls (8.3% of volume)",
      "ease": 9,
      "theme": "Payments"
    }
  ]
}
```

---

## Slide Type 5: Recommendations by Owning Team

**`slide_role: "recommendations"`**

**Background:** WHITE

**Layout — 2×2 card grid:**
```
CARD_W:     4.15 inches
CARD_H:     2.05 inches
GAP_X:      0.2 inches
GAP_Y:      0.15 inches
GRID_START_X: 0.5 + ((9.0 - 2*4.15 - 0.2) / 2)  = 0.75
GRID_START_Y: 0.95

Card positions:
  [0,0] Digital/UX:     x=0.75,  y=0.95
  [0,1] Operations:     x=5.10,  y=0.95
  [1,0] Communications: x=0.75,  y=3.15
  [1,1] Policy:         x=5.10,  y=3.15
```

**Per card:**

1. **Card background** — RECTANGLE
   - Fill: BG_LIGHT ("F5F7FA")
   - `x: card_x, y: card_y, w: 4.15, h: 2.05`

2. **Left accent bar** — thin RECTANGLE
   - Fill: dimension color from DIMENSION_COLORS
   - `x: card_x, y: card_y, w: 0.05, h: 2.05`

3. **Dimension title** — bold text
   - `"■ Digital / UX"` — the square is a unicode block char (■) colored with dimension color
   - Rich text: `[{text: "■ ", color: dimension_color, bold: true}, {text: "Digital / UX", color: NAVY, bold: true}]`
   - fontSize: 13
   - `x: card_x + 0.2, y: card_y + 0.1, w: 3.75, h: 0.3`

4. **Action bullets** — max 2 per card
   - Each action:
     ```
     { text: "• Action title", bold: true, fontSize: 10.5, color: BLACK, breakLine: true }
     { text: "   → X calls resolved across Theme", bold: false, fontSize: 9.5, color: MID_GRAY, breakLine: true }
     ```
   - `x: card_x + 0.2, y: card_y + 0.5, w: 3.75, h: 1.45`
   - `valign: "top"`, `paraSpaceAfter: 6`

**If a dimension has no actions:** Skip that card entirely. Remaining cards reposition to fill space. Or: render the card with muted text: `"No high-priority actions in this cycle"` in SMALL_MUTED style.

**Input JSON shape:**
```json
{
  "slide_role": "recommendations",
  "title": "Recommended Actions by Owning Team",
  "dimensions": [
    {
      "name": "Digital / UX",
      "actions": [
        {
          "title": "Build unified rewards transparency dashboard",
          "detail": "Resolves 12 calls across Rewards & Loyalty — single view for points balance, earn rates, transfer status"
        },
        {
          "title": "Add real-time transfer status tracker",
          "detail": "Resolves 4 calls — push notifications at each transfer stage"
        }
      ]
    },
    {
      "name": "Operations",
      "actions": [
        {
          "title": "Automate crediting pipeline with 2-hour SLA",
          "detail": "Resolves 8 calls from crediting SLA breaches"
        }
      ]
    },
    {
      "name": "Communications",
      "actions": [
        {
          "title": "Publish planned-maintenance push notifications 48hrs ahead",
          "detail": "Resolves 6 'is the app down?' calls per cycle"
        }
      ]
    },
    {
      "name": "Policy",
      "actions": [
        {
          "title": "Enforce 48-hour crediting SLA with escalation path",
          "detail": "Resolves 5 calls — policy backstop for ops automation"
        }
      ]
    }
  ]
}
```

---

## Slide Type 6: Theme Deep-Dive Card

**`slide_role: "theme_card"`**

**One slide per theme. Sort by call volume descending.**

**Background:** WHITE

**Layout — two columns:**
```
TITLE_Y:      0.3
STATS_Y:      0.62
RULE_Y:       0.82
LEFT_X:       0.5
LEFT_W:       5.3
RIGHT_X:      6.1
RIGHT_W:      3.6
CONTENT_Y:    0.95
CONTENT_H:    4.2
```

**Elements to render:**

### Top section (full width):

1. **Theme title**
   - fontSize: 22, bold: true, color: NAVY
   - `x: 0.5, y: 0.3, w: 9.0, h: 0.35`

2. **Stats bar** — single line of muted metrics
   - `"Calls: 14  |  Impact: 8  |  Ease: 7  |  Priority: 7.6"`
   - fontSize: 10, color: MID_GRAY
   - `x: 0.5, y: 0.62, w: 9.0, h: 0.2`

3. **Rule** — gray separator
   - `x: 0.5, y: 0.82, w: 9.0, h: 0.008`

### Left column (60%):

4. **"Core Issue" label**
   - `"CORE ISSUE"`
   - H3_LABEL style (14pt, bold, BLUE_ACCENT)
   - `x: 0.5, y: 0.95, w: 5.3, h: 0.25`

5. **Core issue text**
   - 2-3 sentences describing the theme's main problem
   - BODY_TEXT style (11pt, BLACK)
   - `x: 0.5, y: 1.22, w: 5.3, h: 0.65`
   - `valign: "top"`

6. **"Primary Driver" label**
   - `"PRIMARY DRIVER"`
   - H3_LABEL style
   - `x: 0.5, y: 1.95, w: 5.3, h: 0.25`

7. **Primary driver text**
   - Description of what's driving calls
   - BODY_TEXT style
   - `x: 0.5, y: 2.22, w: 5.3, h: 0.55`
   - `valign: "top"`

8. **"Solutions" label**
   - `"SOLUTIONS"`
   - H3_LABEL style
   - `x: 0.5, y: 2.85, w: 5.3, h: 0.25`

9. **Solutions list** — numbered, max 3 items
   - Rich text array, each solution:
     ```
     { text: "1. ", bold: true, fontSize: 11, color: BLACK }
     { text: "Solution description here ", bold: false, fontSize: 11, color: BLACK }
     { text: "[Digital]", bold: true, fontSize: 9, color: BLUE_ACCENT, breakLine: true }
     ```
   - `x: 0.5, y: 3.12, w: 5.3, h: 1.8`
   - `valign: "top"`, `paraSpaceAfter: 4`
   - Do NOT force 3 solutions. If only 1-2 exist, render only those.

### Right column (40%):

10. **Driver table**
    - Position: `x: 6.1, y: 0.95, w: 3.6`
    - Auto-height based on row count

    **Table structure:**
    ```
    Header row:  bg=NAVY, text=WHITE, fontSize=9, bold=true
    Body rows:   alternating WHITE / BG_LIGHT, fontSize=9, color=BLACK
    Border:      color=LIGHT_GRAY, pt=0.5
    ```

    **Columns:**
    | Column | Width | Align |
    |--------|-------|-------|
    | Driver | 2.5"  | left  |
    | Calls  | 1.1"  | center|

    **Column widths array:** `colW: [2.5, 1.1]`

    **Row height:** `rowH: 0.3` for header, `0.28` for body rows

    Build as pptxgenjs table:
    ```javascript
    const tableRows = [
      // Header
      [
        { text: "Driver", options: { bold: true, fontSize: 9, color: "FFFFFF", fill: { color: "003B70" }, align: "left" } },
        { text: "Calls",  options: { bold: true, fontSize: 9, color: "FFFFFF", fill: { color: "003B70" }, align: "center" } }
      ],
      // Body rows
      ...drivers.map((d, i) => [
        { text: d.name,  options: { fontSize: 9, color: "222222", fill: { color: i % 2 === 0 ? "FFFFFF" : "F5F7FA" }, align: "left" } },
        { text: String(d.calls), options: { fontSize: 9, color: "222222", fill: { color: i % 2 === 0 ? "FFFFFF" : "F5F7FA" }, align: "center" } }
      ])
    ];

    slide.addTable(tableRows, {
      x: 6.1, y: 0.95, w: 3.6,
      colW: [2.5, 1.1],
      border: { pt: 0.5, color: "D0D0D0" },
      margin: [3, 5, 3, 5]  // top, right, bottom, left in points
    });
    ```

**Input JSON shape:**
```json
{
  "slide_role": "theme_card",
  "title": "Rewards & Loyalty",
  "stats_bar": {
    "calls": 14,
    "impact": 8,
    "ease": 7,
    "priority": 7.6
  },
  "left_column": {
    "core_issue": "Customers cannot see pending points, earn rates, or transfer status — forcing them to call for information that should be self-service. The lack of a real-time tracker means every points crediting event generates a potential call.",
    "primary_driver": "Points crediting exceeds the 48-hour SLA with no visibility into processing status, generating 8 of 14 calls in this theme.",
    "solutions": [
      { "action": "Build pending points tracker with real-time status", "dimension": "Digital" },
      { "action": "Enforce 48-hour crediting SLA via automated pipeline", "dimension": "Ops" },
      { "action": "Send proactive push notification on points credit", "dimension": "Comms" }
    ]
  },
  "right_column": {
    "headers": ["Driver", "Calls"],
    "rows": [
      ["Points crediting delay", 8],
      ["Earn rate confusion", 4],
      ["Transfer status unknown", 2]
    ]
  }
}
```

---

## Complete Input JSON Schema

The renderer expects a single JSON object:

```json
{
  "metadata": {
    "report_title": "Customer Call Analysis — Q4 2024",
    "total_calls": 96,
    "generated_at": "2025-01-15"
  },
  "slides": [
    { "slide_role": "executive_summary", ... },
    { "slide_role": "pain_points", ... },
    { "slide_role": "impact_ease", ... },
    { "slide_role": "low_hanging_fruit", ... },
    { "slide_role": "recommendations", ... },
    { "slide_role": "theme_card", ... },
    { "slide_role": "theme_card", ... },
    { "slide_role": "theme_card", ... }
  ]
}
```

## Renderer Architecture

```javascript
const pptxgen = require("pptxgenjs");
const fs = require("fs");

const inputPath = process.argv[2];
const outputPath = process.argv[3] || "report.pptx";
const data = JSON.parse(fs.readFileSync(inputPath, "utf-8"));

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "AgenticAnalytics";
pres.title = data.metadata.report_title;

// Dispatch each slide to its renderer
for (const slideData of data.slides) {
  switch (slideData.slide_role) {
    case "executive_summary":  renderExecutiveSummary(pres, slideData); break;
    case "pain_points":        renderPainPoints(pres, slideData); break;
    case "impact_ease":        renderImpactEase(pres, slideData); break;
    case "low_hanging_fruit":  renderLowHangingFruit(pres, slideData); break;
    case "recommendations":    renderRecommendations(pres, slideData); break;
    case "theme_card":         renderThemeCard(pres, slideData); break;
  }
}

pres.writeFile({ fileName: outputPath });
```

Each `render*` function creates one slide, adds all shapes/text/tables per the specs above. No shared mutable state between functions — each creates fresh option objects to avoid the pptxgenjs mutation pitfall.

## Important pptxgenjs Rules

1. **Never use `#` in hex colors** — `"003B70"` not `"#003B70"`
2. **Never reuse option objects** — create fresh objects for each `addShape`/`addText` call
3. **Use `breakLine: true`** between text runs in rich text arrays
4. **Use `bullet: true`** not unicode `•` characters
5. **Use `paraSpaceAfter`** not `lineSpacing` for bullet gaps
6. **Shadow objects need `opacity`** not encoded in hex — `{ color: "000000", opacity: 0.15 }` not `"00000020"`
7. **Do NOT use accent lines under titles** — use whitespace or the gray RECTANGLE rule instead

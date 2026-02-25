import json
import time

def create_text(id, x, y, text, fontSize=14, fontFamily=1, strokeColor="#1e1e1e", textAlign="center", verticalAlign="middle", width=None, height=None):
    # approximate width/height
    lines = text.split('\n')
    w = width or max(len(l) for l in lines) * fontSize * 0.6
    h = height or len(lines) * fontSize * 1.2
    return {
        "id": id,
        "type": "text",
        "x": x, "y": y,
        "width": w, "height": h,
        "angle": 0, "strokeColor": strokeColor, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
        "roughness": 0, "opacity": 100, "groupIds": [], "roundness": null_val(),
        "seed": 1, "version": 1, "versionNonce": 1, "isDeleted": False,
        "boundElements": None, "updated": int(time.time() * 1000), "link": None,
        "locked": False, "text": text, "fontSize": fontSize, "fontFamily": fontFamily,
        "textAlign": textAlign, "verticalAlign": verticalAlign, "originalText": text
    }

def create_rect(id, x, y, width, height, bgColor="#ffffff", strokeColor="#1e1e1e", strokeStyle="solid"):
    return {
        "id": id,
        "type": "rectangle",
        "x": x, "y": y,
        "width": width, "height": height,
        "angle": 0, "strokeColor": strokeColor, "backgroundColor": bgColor,
        "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": strokeStyle,
        "roughness": 0, "opacity": 100, "groupIds": [], "roundness": {"type": 3},
        "seed": 1, "version": 1, "versionNonce": 1, "isDeleted": False,
        "boundElements": None, "updated": int(time.time() * 1000), "link": None,
        "locked": False
    }

def create_arrow(id, x, y, end_x, end_y, text="", strokeColor="#1e1e1e"):
    w = end_x - x
    h = end_y - y
    elements = [{
        "id": id,
        "type": "arrow",
        "x": x, "y": y,
        "width": abs(w), "height": abs(h),
        "angle": 0, "strokeColor": strokeColor, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
        "roughness": 0, "opacity": 100, "groupIds": [], "roundness": None,
        "seed": 1, "version": 1, "versionNonce": 1, "isDeleted": False,
        "boundElements": None, "updated": int(time.time() * 1000), "link": None,
        "locked": False,
        "points": [[0, 0], [w, h]],
        "lastCommittedPoint": None, "startBinding": None, "endBinding": None,
        "startArrowhead": None, "endArrowhead": "arrow", "elbowed": False
    }]
    if text:
        text_id = id + "_text"
        txt_x = x + w/2 - (len(text) * 4)
        txt_y = y + h/2 - 10
        elements.append(create_text(text_id, txt_x, txt_y, text, fontSize=10, strokeColor=strokeColor))
    return elements

def null_val(): return None

# Colors for different types
COLOR_REACT = "#ffc9c9"          # Light red
COLOR_ROUTER = "#ffe8cc"         # Light orange
COLOR_STRUCTURED = "#d0ebff"     # Light blue
COLOR_PLAN = "#d3f9d8"           # Light green
COLOR_SCRIPT = "#eebefa"         # Light purple
COLOR_COMPOSITE = "#f1f3f5"      # Light grey
COLOR_STORAGE = "#fff3bf"        # Light yellow
COLOR_SKILL = "#c3fae8"          # Teal/Cyan

elements = []

# Title
elements.append(create_text("title", 800, 20, "AgenticAnalytics Detailed Architecture\n(Nodes, Agents, Connections, Skills)", fontSize=28, textAlign="center"))

# Legend
leg_x = 40
leg_y = 20
elements.append(create_rect("leg_bg", leg_x, leg_y, 250, 200, "#ffffff"))
elements.append(create_text("leg_t", leg_x+10, leg_y+10, "Legend:", fontSize=16, textAlign="left"))
elements.append(create_rect("leg_1", leg_x+10, leg_y+40, 20, 20, COLOR_REACT))
elements.append(create_text("leg_t1", leg_x+40, leg_y+42, "ReAct Agent", fontSize=12, textAlign="left"))
elements.append(create_rect("leg_2", leg_x+10, leg_y+70, 20, 20, COLOR_ROUTER))
elements.append(create_text("leg_t2", leg_x+40, leg_y+72, "Router / orchestrator", fontSize=12, textAlign="left"))
elements.append(create_rect("leg_3", leg_x+10, leg_y+100, 20, 20, COLOR_STRUCTURED))
elements.append(create_text("leg_t3", leg_x+40, leg_y+102, "Structured LLM", fontSize=12, textAlign="left"))
elements.append(create_rect("leg_4", leg_x+10, leg_y+130, 20, 20, COLOR_PLAN))
elements.append(create_text("leg_t4", leg_x+40, leg_y+132, "Plan LLM", fontSize=12, textAlign="left"))
elements.append(create_rect("leg_5", leg_x+10, leg_y+160, 20, 20, COLOR_SCRIPT))
elements.append(create_text("leg_t5", leg_x+40, leg_y+162, "Script-only / Deterministic", fontSize=12, textAlign="left"))


# --- Client & App layer ---
elements.append(create_rect("ui_node", 400, 150, 200, 80, "#ffffff"))
elements.append(create_text("ui_text", 410, 160, "Chainlit UI / Client\n(App/API Layer)", fontSize=14))

# --- LangGraph Orchestrator (Supervisor) ---
elements.append(create_rect("supervisor", 400, 300, 200, 100, COLOR_ROUTER))
elements.append(create_text("sup_text", 410, 310, "Supervisor Node\n[Structured LLM]\n(Routing & Execution)", fontSize=14))

elements.extend(create_arrow("a_ui_sup", 500, 230, 500, 300, "User Query /\nGraph Stream"))

# --- Global Nodes ---
elements.append(create_rect("planner", 150, 300, 180, 80, COLOR_PLAN))
elements.append(create_text("plan_t", 160, 320, "Planner Node\n[Plan LLM]", fontSize=14))
elements.extend(create_arrow("a_sup_plan", 400, 340, 330, 340, "plan_tasks"))
elements.extend(create_arrow("a_plan_sup", 330, 360, 400, 360, "return"))

elements.append(create_rect("data_analyst", 150, 450, 180, 80, COLOR_REACT))
elements.append(create_text("da_t", 160, 470, "Data Analyst\n[ReAct Agent]", fontSize=14))
elements.extend(create_arrow("a_sup_da", 450, 400, 330, 490, "extract"))

elements.append(create_rect("report_analyst", 150, 600, 180, 80, COLOR_REACT))
elements.append(create_text("ra_t", 160, 620, "Report Analyst\n[ReAct Agent]", fontSize=14))
elements.extend(create_arrow("a_sup_ra", 450, 400, 330, 640, "QA fix"))

elements.append(create_rect("critique", 150, 750, 180, 80, COLOR_REACT))
elements.append(create_text("cr_t", 160, 770, "Critique Node\n[ReAct Agent]", fontSize=14))

elements.append(create_rect("user_checkpoint", 650, 150, 180, 60, COLOR_SCRIPT))
elements.append(create_text("uc_t", 660, 165, "User Checkpoint\n[Script]", fontSize=14))
elements.extend(create_arrow("a_sup_chk", 550, 300, 650, 210, "Interrupt"))


# --- Friction Analysis Composite ---
fx = 750
fy = 280
elements.append(create_rect("friction_comp", fx, fy, 450, 320, COLOR_COMPOSITE, strokeStyle="dashed"))
elements.append(create_text("friction_title", fx+10, fy+10, "Friction Analysis Composite Node", fontSize=14, strokeColor="#868e96"))

elements.append(create_rect("dig_lens", fx+20, fy+50, 150, 60, COLOR_REACT))
elements.append(create_text("dig_t", fx+30, fy+60, "Digital Agent\n[ReAct]", fontSize=12))

elements.append(create_rect("ops_lens", fx+20, fy+120, 150, 60, COLOR_REACT))
elements.append(create_text("ops_t", fx+30, fy+130, "Operations Agent\n[ReAct]", fontSize=12))

elements.append(create_rect("com_lens", fx+190, fy+50, 150, 60, COLOR_REACT))
elements.append(create_text("com_t", fx+200, fy+60, "Communication Agent\n[ReAct]", fontSize=12))

elements.append(create_rect("pol_lens", fx+190, fy+120, 150, 60, COLOR_REACT))
elements.append(create_text("pol_t", fx+200, fy+130, "Policy Agent\n[ReAct]", fontSize=12))

elements.append(create_rect("synth_lens", fx+105, fy+230, 150, 60, COLOR_STRUCTURED))
elements.append(create_text("synth_t", fx+115, fy+240, "Synthesizer Agent\n[Structured LLM]", fontSize=12))

elements.extend(create_arrow("a_sup_fric", 600, 350, fx, 350, "friction_analysis"))

# Connect lenses to synth
elements.extend(create_arrow("al1", fx+95, fy+110, fx+150, fy+230, ""))
elements.extend(create_arrow("al2", fx+95, fy+180, fx+150, fy+230, ""))
elements.extend(create_arrow("al3", fx+265, fy+110, fx+200, fy+230, ""))
elements.extend(create_arrow("al4", fx+265, fy+180, fx+200, fy+230, ""))

# Skills inside Friction Analysis
elements.append(create_rect("skills_box", fx+360, fy+50, 70, 200, COLOR_SKILL))
elements.append(create_text("sk_t", fx+365, fy+60, "Domain\nSkills:\n-auth\n-fraud\n-transfer\n-profile\n-rewards\n-stmt", fontSize=10))


# --- Report Generation Composite ---
rx = 750
ry = 650
elements.append(create_rect("report_comp", rx, ry, 450, 250, COLOR_COMPOSITE, strokeStyle="dashed"))
elements.append(create_text("report_title", rx+10, ry+10, "Report Generation Composite Node", fontSize=14, strokeColor="#868e96"))

elements.append(create_rect("narrative", rx+40, ry+50, 160, 60, COLOR_REACT))
elements.append(create_text("narr_t", rx+50, ry+65, "Narrative Agent\n[ReAct]", fontSize=12))

elements.append(create_rect("dataviz", rx+250, ry+50, 160, 60, COLOR_SCRIPT))
elements.append(create_text("dv_t", rx+260, ry+60, "DataViz Agent\n[Deterministic/Script]", fontSize=12))

elements.append(create_rect("formatting", rx+145, ry+150, 160, 60, COLOR_REACT))
elements.append(create_text("fmt_t", rx+155, ry+160, "Formatting Agent\n[ReAct]", fontSize=12))

elements.extend(create_arrow("a_sup_rep", 600, 380, rx, 700, "report_generation"))
elements.extend(create_arrow("ar1", rx+120, ry+110, rx+200, ry+150, ""))
elements.extend(create_arrow("ar2", rx+330, ry+110, rx+250, ry+150, ""))

# --- Tools & Storage Layer ---
sx = 1250
sy = 200
elements.append(create_rect("storage_box", sx, sy, 250, 300, COLOR_STORAGE))
elements.append(create_text("st_t", sx+10, sy+10, "Storage & Artifacts\n(Disk / DataStore)", fontSize=14))
elements.append(create_text("st_l", sx+20, sy+50, "1. .cache/thread_states\n2. data/tmp/<thread_id>\n3. data/input/\n4. data/output/<thread_id>\n  - complete_analysis.md\n  - report.pptx\n  - filtered_data.csv\n5. DataStore Session", fontSize=12, textAlign="left"))

elements.extend(create_arrow("a_fric_st", fx+450, fy+150, sx, min(fy+150, sy+400), "store parallel\nagent outputs"))
elements.extend(create_arrow("a_rep_st", rx+450, ry+100, sx+120, sy+300, "write artifacts"))


final_json = {
    "type": "excalidraw",
    "version": 2,
    "source": "https://excalidraw.com",
    "elements": elements,
    "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
    "files": {}
}

with open("d:/Workspace/AgenticAnalytics/architecture.excalidraw", "w") as f:
    json.dump(final_json, f, indent=2)

print("Excalidraw diagram generated successfully.")

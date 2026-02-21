"""Application configuration loaded from environment variables.

All project-wide constants and tunables live here.
Toggle ``VERBOSE`` to surface every node call, tool invocation,
AI message and supervisor reasoning inside the Chainlit UI.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# -- Paths ------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT_DIR / "agents" / "definitions"
SKILLS_DIR = ROOT_DIR / "skills"
DATA_DIR = ROOT_DIR / os.getenv("DATA_DIR", "data")
CACHE_DIR = ROOT_DIR / os.getenv("CACHE_DIR", ".cache")
THREAD_STATES_DIR = CACHE_DIR / "thread_states"

# -- Google AI Studio / Gemini -------------------------------------------------------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# -- Model defaults -----------------------------------------------------------
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.5-flash")
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.1"))
DEFAULT_TOP_P = float(os.getenv("DEFAULT_TOP_P", "0.95"))
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "8192"))

# -- Thresholds ---------------------------------------------------------------
MAX_SAMPLE_SIZE = 50  # Max rows returned by sample_data
TOP_N_DEFAULT = 10  # Default for top-N distributions
MIN_BUCKET_SIZE = 10  # Minimum rows for a meaningful bucket
IMPACT_WEIGHT = 0.6  # Weight for impact in composite score
EASE_WEIGHT = 0.4  # Weight for ease in composite score

# -- Display & Debug ---------------------------------------------------------
# Master switch: when True, every node entry/exit, tool call, AI response,
# and supervisor reasoning is rendered as collapsible Chainlit Steps.
VERBOSE = os.getenv("VERBOSE", "true").lower() in ("1", "true", "yes")

# Individual toggles (only matter when VERBOSE is True)
SHOW_TOOL_CALLS = os.getenv("SHOW_TOOL_CALLS", "true").lower() in ("1", "true", "yes")
SHOW_NODE_IO = os.getenv("SHOW_NODE_IO", "true").lower() in ("1", "true", "yes")
SHOW_SUPERVISOR_REASONING = os.getenv("SHOW_SUPERVISOR_REASONING", "true").lower() in ("1", "true", "yes")

# Truncation: max characters for long outputs shown in UI steps
MAX_DISPLAY_LENGTH = int(os.getenv("MAX_DISPLAY_LENGTH", "2000"))

# Log level for console logging ("debug" | "info" | "warning" | "error")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()

# -- Agent groups (multi-agent subgraphs) ------------------------------------
FRICTION_AGENTS = {
    "digital_friction_agent",
    "operations_agent",
    "communication_agent",
    "policy_agent",
}
REPORTING_AGENTS = {
    "narrative_agent",
    "dataviz_agent",
    "formatting_agent",
}
ALL_DOMAIN_SKILLS = [
    "payment_transfer",
    "transaction_statement",
    "authentication",
    "profile_settings",
    "fraud_dispute",
    "rewards",
]

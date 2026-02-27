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
ROOT_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ROOT_DIR / "agents" / "definitions"
SKILLS_DIR = ROOT_DIR / "skills"

DATA_DIR = ROOT_DIR / "data"
DATA_INPUT_DIR = DATA_DIR / "input"
DATA_OUTPUT_DIR = DATA_DIR / "output"
DATA_CACHE_DIR = DATA_DIR / ".cache"
THREAD_STATES_DIR = DATA_CACHE_DIR / "states"

# Hardcoded default CSV path — user sets this to their dataset location.
# Override via DEFAULT_CSV_PATH env var or change this line directly.
DEFAULT_CSV_PATH = os.getenv("DEFAULT_CSV_PATH", str(DATA_INPUT_DIR / "input.csv"))

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
IMPACT_WEIGHT = 0.6  # Weight for impact in composite score
EASE_WEIGHT = 0.4  # Weight for ease in composite score

# -- Intelligent Bucketing ---------------------------------------------------
# Columns used for hierarchical group-by (in order of priority).
# Data is grouped by these columns sequentially to create analysis buckets.
GROUP_BY_COLUMNS: list[str] = [
    "call_reason",        # L1 — broadest grouping
    "broad_theme_l3",     # L3 — mid-level theme
    "granular_theme_l5",  # L5 — most granular
]

# Bucket size controls
MIN_BUCKET_SIZE = 10     # Buckets smaller than this get merged into "Other"
MAX_BUCKET_SIZE = 2000   # Buckets larger than this get sub-bucketed by next column

# Tail-end collection: merge all small buckets into a single "Other" bucket
TAIL_BUCKET_ENABLED = True

# -- LLM Analysis Fields ----------------------------------------------------
# ONLY these columns are passed to friction lens agents for LLM analysis.
# All other columns are used for grouping/filtering but NOT sent to the LLM.
# This keeps context small even with 10-12K records.
LLM_ANALYSIS_COLUMNS: list[str] = [
    "digital_friction",   # LLM-processed friction analysis per call
    "key_solution",       # LLM-processed solution summary per call
]

# -- PPTX Template -----------------------------------------------------------
# Path to an external .pptx template file with pre-designed slide layouts.
# If the file exists, slides use its layouts. If not, falls back to code-based defaults.
# Set to "" or leave as default to use code-based template.
PPTX_TEMPLATE_PATH = os.getenv("PPTX_TEMPLATE_PATH", str(DATA_INPUT_DIR / "template.pptx"))

# -- Display & Debug ---------------------------------------------------------
# Master switch: when True, every node entry/exit, tool call, AI response,
# and supervisor reasoning is rendered as collapsible Chainlit Steps.
VERBOSE = False

# Individual toggles (only matter when VERBOSE is True)
SHOW_TOOL_CALLS = os.getenv("SHOW_TOOL_CALLS", "true").lower() in ("1", "true", "yes")
SHOW_NODE_IO = os.getenv("SHOW_NODE_IO", "true").lower() in ("1", "true", "yes")
SHOW_SUPERVISOR_REASONING = os.getenv("SHOW_SUPERVISOR_REASONING", "true").lower() in ("1", "true", "yes")

# Truncation: max characters for long outputs shown in UI steps
MAX_DISPLAY_LENGTH = int(os.getenv("MAX_DISPLAY_LENGTH", "2000"))

# Log level for console logging ("debug" | "info" | "warning" | "error")
LOG_LEVEL = os.getenv("LOG_LEVEL", "debug").lower()
LOG_FORMAT = os.getenv("LOG_FORMAT", " [%(levelname)s]---------[ %(name)s ]----------- %(message)s")
LOG_DATE_FORMAT = os.getenv("LOG_DATE_FORMAT", "%H:%M:%S")

# -- Agent groups (multi-agent subgraphs) ------------------------------------
FRICTION_AGENTS = {
    "digital_friction_agent",
    "operations_agent",
    "communication_agent",
    "policy_agent",
}
REPORTING_AGENTS = {
    "narrative_agent",
    "formatting_agent",
    "report_analyst",
}
ALL_DOMAIN_SKILLS = [
    "payment_transfer",
    "transaction_statement",
    "authentication",
    "profile_settings",
    "fraud_dispute",
    "rewards",
    "promotion_offers",
    "general_inquiry",
]
CALL_REASONS_TO_SKILLS = {'Payments & Transfers': ['payment_transfer','fraud_dispute'], 
 'Fraud & Disputes': ['fraud_dispute'], 
 'Authentication & Access': ['authentication'], 
 'Rewards & Loyalty': ['rewards'], 
 'Profile & Settings': ['profile_settings','authentication'], 
 'Transactions & Statements': ['transaction_statement'],
 'Promotion & Offers': ['promotion_offers'],
 'Other': ['general_inquiry']}

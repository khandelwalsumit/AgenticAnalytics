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


##########################################################################
# ----[ Paths ]-----------------------------------------------------------
##########################################################################

ROOT_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ROOT_DIR / "agents" / "definitions"
SKILLS_DIR = ROOT_DIR / "skills"

DATA_DIR = ROOT_DIR / "data"
DATA_INPUT_DIR = DATA_DIR / "input"
DATA_OUTPUT_DIR = DATA_DIR / "output"
DATA_CACHE_DIR = DATA_DIR / ".cache"
THREAD_STATES_DIR = DATA_CACHE_DIR / "states"




##########################################################################
#----[ MAIN SETTINGS ]----------------------------------------------------
##########################################################################

VERBOSE = False

DEFAULT_PARQUET_PATH = DATA_INPUT_DIR / "adf.parquet"
PPTX_TEMPLATE_PATH = os.getenv("PPTX_TEMPLATE_PATH", str(DATA_INPUT_DIR / "template.pptx"))

LLM_ANALYSIS_FOCUS: list[str] = ["exact_actionable_problem"]

MIN_BUCKET_SIZE = 5     # Buckets smaller than this get merged into "Other"
MAX_BUCKET_SIZE = 200   # Buckets larger than this get sub-bucketed by next column
TAIL_BUCKET_ENABLED = True

GROUP_BY_COLUMNS: list[str] = [
    "call_reason",        # L1 — broadest grouping
    "broad_theme_l3",     # L3 — mid-level theme
    "granular_theme_l5",  # L5 — most granular
]

LLM_ANALYSIS_CONTEXT: dict[str, list[str]] = {
    "product": ["Costco", "Rewards", "AAdvantage", "Cash", "others","Non Rewards","ATT"],
    "call_reason": [
        "Payments & Transfers",
        "Dispute & Fraud",
        "Products & Offers",
        "Sign On",
        "Profile & Settings",
        "Replace Card",
        "Transactions & Statements",
        "Other",
        "Rewards"
    ],
}





#############################################################################
#---[ Agent groups (multi-agent subgraphs) ]---------------------------------
#############################################################################

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
    "promotions_offers",
    "general_inquiry",
    "card_replacement",
]
CALL_REASONS_TO_SKILLS = {
        "Payments & Transfers":["payment_transfer","fraud_dispute"],
        "Dispute & Fraud":["fraud_dispute","payment_transfer"],
        "Products & Offers":["promotions_offers"],
        "Sign On":["authentication"],
        "Profile & Settings":["profile_settings","authentication"],
        "Replace Card":["card_replacement","profile_settings"],
        "Transactions & Statements":["transaction_statement"],
        "Other":["general_inquiry"],
        "Rewards":["rewards","promotions_offers"]
}

##########################################################################
# ----[ Google AI Studio / Gemini ]---------------------------------------
##########################################################################

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
USE_VERTEXAI_SDK = os.getenv("USE_VERTEXAI_SDK", "false").lower() in ("1", "true", "yes")
BACKOFF_MAX_DELAY = int(os.getenv("BACKOFF_MAX_DELAY", "0"))
USERNAME = os.getenv("USERNAME", "")
R2D2_ENDPOINT = os.getenv("R2D2_ENDPOINT", "")
R2D2_PROJECT = os.getenv("R2D2_PROJECT", "")
# BACKOFF_MAX_DELAY = 0  # False or 0 disables backoff and retries, which may be desirable in some cases to fail fast on errors. Adjust as needed.




##########################################################################
# ----[ Model defaults ]--------------------------------------------------
##########################################################################

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.5-flash")
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.1"))
DEFAULT_TOP_P = float(os.getenv("DEFAULT_TOP_P", "0.95"))
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "8192"))



##########################################################################
# ----[ Parallelism ]-----------------------------------------------------
##########################################################################

MAX_MULTITHREADING_WORKERS = int(os.getenv("MAX_MULTITHREADING_WORKERS", "8"))
MAX_SUPERVISOR_MSGS = int(os.getenv("MAX_SUPERVISOR_MSGS", "6"))
SUMMARIZE_THRESHOLD_CHARS = int(os.getenv("SUMMARIZE_THRESHOLD_CHARS", "40000"))



##########################################################################
# ----[ Bucketing Thresholds ]--------------------------------------------
##########################################################################

MAX_SAMPLE_SIZE = 50  # Max rows returned by sample_data
TOP_N_DEFAULT = 10  # Default for top-N distributions
IMPACT_WEIGHT = 0.6  # Weight for impact in composite score
EASE_WEIGHT = 0.4  # Weight for ease in composite score



DATA_FILTER_COLUMNS: list[str] = list(LLM_ANALYSIS_CONTEXT.keys())



##########################################################################
# ----[ Log Settings ]--------------------------------------------
##########################################################################
SHOW_TOOL_CALLS = os.getenv("SHOW_TOOL_CALLS", "true").lower() in ("1", "true", "yes")
SHOW_NODE_IO = os.getenv("SHOW_NODE_IO", "true").lower() in ("1", "true", "yes")
SHOW_SUPERVISOR_REASONING = os.getenv("SHOW_SUPERVISOR_REASONING", "true").lower() in ("1", "true", "yes")

MAX_DISPLAY_LENGTH = int(os.getenv("MAX_DISPLAY_LENGTH", "2000"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "debug").lower()
LOG_FORMAT = os.getenv("LOG_FORMAT", " [%(levelname)s]---------[ %(name)s ]----------- %(message)s")
LOG_DATE_FORMAT = os.getenv("LOG_DATE_FORMAT", "%H:%M:%S")

"""Application configuration loaded from environment variables."""

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

# -- VertexAI / Gemini -------------------------------------------------------
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
VERTEX_AI_ENDPOINT = os.getenv("VERTEX_AI_ENDPOINT", "")

# -- Model defaults -----------------------------------------------------------
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-pro")
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.1"))
DEFAULT_TOP_P = float(os.getenv("DEFAULT_TOP_P", "0.95"))
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "8192"))

# -- Thresholds ---------------------------------------------------------------
MAX_SAMPLE_SIZE = 50  # Max rows returned by sample_data
TOP_N_DEFAULT = 10  # Default for top-N distributions
MIN_BUCKET_SIZE = 10  # Minimum rows for a meaningful bucket
IMPACT_WEIGHT = 0.6  # Weight for impact in composite score
EASE_WEIGHT = 0.4  # Weight for ease in composite score

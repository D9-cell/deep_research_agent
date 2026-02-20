"""
AlgoMentor — Configuration
Loads environment variables and exports constants used across all phases.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# .env lives one level above algomentor/ (i.e. at the workspace root)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# ── API Keys ─────────────────────────────────────────────────────────────────
MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

if not MISTRAL_API_KEY:
    raise RuntimeError("MISTRAL_API_KEY is not set — add it to your .env file.")
if not TAVILY_API_KEY:
    raise RuntimeError("TAVILY_API_KEY is not set — add it to your .env file.")

# ── LeetCode ──────────────────────────────────────────────────────────────────
LEETCODE_GRAPHQL_URL: str = "https://leetcode.com/graphql"

# ── Memory (Phase 3) ─────────────────────────────────────────────────────────
MEMORY_DIR: Path = Path(__file__).resolve().parent.parent / "memory"
MEMORY_FILE: Path = MEMORY_DIR / "memory.json"

# ── Model ─────────────────────────────────────────────────────────────────────
DEFAULT_MODEL: str = "mistral-large-latest"
MODEL_TEMPERATURE: float = 0.2

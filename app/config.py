import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = Path(os.environ.get("KIVI_DB_PATH", BASE_DIR / "db" / "kivi.db"))
MIGRATIONS_DIR = BASE_DIR / "db" / "migrations"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# "anthropic" is the documented provider for submission. "groq" is a
# temporary dev-time substitute for when no Anthropic key is available —
# see app/services/llm.py. Swap back by unsetting KIVI_LLM_PROVIDER (or
# setting it to "anthropic") once an Anthropic key exists.
LLM_PROVIDER = os.environ.get("KIVI_LLM_PROVIDER", "groq" if GROQ_API_KEY and not ANTHROPIC_API_KEY else "anthropic")

_DEFAULT_MODELS = {
    "anthropic": {"extraction": "claude-haiku-4-5", "generation": "claude-sonnet-5"},
    "groq": {"extraction": "openai/gpt-oss-120b", "generation": "openai/gpt-oss-120b"},
}

# Cheap/fast model for high-volume extraction & intent classification.
EXTRACTION_MODEL = os.environ.get("KIVI_EXTRACTION_MODEL", _DEFAULT_MODELS[LLM_PROVIDER]["extraction"])
# Stronger model for Hey Kivi generation, tool use, and grounded Q&A.
GENERATION_MODEL = os.environ.get("KIVI_GENERATION_MODEL", _DEFAULT_MODELS[LLM_PROVIDER]["generation"])

# Below this confidence, an extracted candidate is held for manual confirmation
# rather than auto-committed. See docs/POSITIONING.md / README for the reasoning.
AUTO_CONFIRM_THRESHOLD = float(os.environ.get("KIVI_AUTO_CONFIRM_THRESHOLD", "0.85"))

# Default lifetime for an open task with no further activity.
TASK_EXPIRY_DAYS = int(os.environ.get("KIVI_TASK_EXPIRY_DAYS", "14"))

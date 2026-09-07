import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = Path(os.environ.get("KIVI_DB_PATH", BASE_DIR / "db" / "kivi.db"))
MIGRATIONS_DIR = BASE_DIR / "db" / "migrations"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Cheap/fast model for high-volume extraction & intent classification.
EXTRACTION_MODEL = os.environ.get("KIVI_EXTRACTION_MODEL", "claude-haiku-4-5")
# Stronger model for Hey Kivi generation, tool use, and grounded Q&A.
GENERATION_MODEL = os.environ.get("KIVI_GENERATION_MODEL", "claude-sonnet-5")

# Below this confidence, an extracted candidate is held for manual confirmation
# rather than auto-committed. See docs/POSITIONING.md / README for the reasoning.
AUTO_CONFIRM_THRESHOLD = float(os.environ.get("KIVI_AUTO_CONFIRM_THRESHOLD", "0.85"))

# Default lifetime for an open task with no further activity.
TASK_EXPIRY_DAYS = int(os.environ.get("KIVI_TASK_EXPIRY_DAYS", "14"))

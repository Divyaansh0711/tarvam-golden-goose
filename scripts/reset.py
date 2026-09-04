"""Wipe the database back to an empty, freshly-migrated state.

Usage: python scripts/reset.py [--seed]
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DB_PATH


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"removed {DB_PATH}")

    subprocess.run([sys.executable, str(Path(__file__).parent / "migrate.py")], check=True)

    if "--seed" in sys.argv:
        subprocess.run([sys.executable, str(Path(__file__).parent / "seed.py")], check=True)


if __name__ == "__main__":
    main()

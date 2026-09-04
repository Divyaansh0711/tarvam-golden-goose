"""Apply all pending SQL migrations under db/migrations/, in filename order.

Usage: python scripts/migrate.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DB_PATH, MIGRATIONS_DIR


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    ensure_migrations_table(conn)
    already = applied_migrations(conn)

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"No migration files found in {MIGRATIONS_DIR}")
        return

    for path in migration_files:
        if path.name in already:
            print(f"skip  {path.name} (already applied)")
            continue
        sql = path.read_text()
        print(f"apply {path.name}")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,)
        )
        conn.commit()

    conn.close()
    print(f"Database ready at {DB_PATH}")


if __name__ == "__main__":
    main()

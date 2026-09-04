"""Insert a small hand-written set of confirmed memories + dictations so the
Memory screen has something to show before the extraction pipeline (phase 3)
exists. Safe to run multiple times against a freshly-migrated DB only.

Usage: python scripts/seed.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import dumps, get_db


def main() -> None:
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO dictations (app, occurred_at, raw_asr, formatted_text, metadata_json, source)
            VALUES
                ('slack', datetime('now', '-2 days'),
                 'thats rahul from engineering not the rahul in finance',
                 'That''s Rahul from engineering, not the Rahul in finance.',
                 '{}', 'manual'),
                ('email', datetime('now', '-1 day'),
                 'always cc my manager on client emails',
                 'Always CC my manager on client emails.',
                 '{}', 'manual')
            """
        )
        first_id = cur.lastrowid - 1

        conn.execute(
            """
            INSERT INTO entities
                (surface_forms_json, resolved_as, role_context, scope_json,
                 status, source_dictation_id, source_quote, confidence, confirmed_at)
            VALUES (?, ?, ?, ?, 'confirmed', ?, ?, 0.97, datetime('now'))
            """,
            (
                dumps(["Rahul", "Rahul from engineering"]),
                "Rahul (engineering)",
                "engineering, disambiguated from Rahul in finance",
                dumps({"apps": ["slack"]}),
                first_id,
                "thats rahul from engineering not the rahul in finance",
            ),
        )

        conn.execute(
            """
            INSERT INTO instructions
                (rule_text, scope_json, status, source_dictation_id, source_quote, confidence, confirmed_at)
            VALUES (?, ?, 'confirmed', ?, ?, 0.95, datetime('now'))
            """,
            (
                "CC manager on client emails",
                dumps({"app": "email"}),
                first_id + 1,
                "always cc my manager on client emails",
            ),
        )

        conn.execute(
            """
            INSERT INTO memory_events (dictation_id, candidate_type, action, memory_table, memory_id, payload_json, reasoning, confidence)
            VALUES
                (?, 'entity', 'confirmed', 'entities', 1, '{}', 'seed data: explicit disambiguating statement', 0.97),
                (?, 'instruction', 'confirmed', 'instructions', 1, '{}', 'seed data: explicit standing instruction', 0.95)
            """,
            (first_id, first_id + 1),
        )

    print("Seeded 2 dictations, 1 entity, 1 instruction.")


if __name__ == "__main__":
    main()

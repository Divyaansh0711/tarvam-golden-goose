-- Recurring commitments (e.g. "weekly call with Rahul") don't fit entity,
-- instruction, or one-off task cleanly: they have no natural end, so the
-- existing 14-day-inactivity task expiry is wrong for them. Rather than
-- auto-committing them as ordinary tasks, they go through the same
-- confirm/dismiss flow entities and instructions already have — hence the
-- new 'pending' (and 'rejected', for symmetry) status. SQLite can't alter a
-- CHECK constraint in place, so this rebuilds the table.

CREATE TABLE tasks_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    app TEXT NOT NULL,
    last_state_summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'open', 'done', 'expired', 'rejected')) DEFAULT 'open',
    recurring INTEGER NOT NULL DEFAULT 0,
    scope_json TEXT NOT NULL DEFAULT '{}',
    source_dictation_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT
);

INSERT INTO tasks_new (id, label, app, last_state_summary, status, scope_json, source_dictation_ids_json, created_at, updated_at, expires_at)
    SELECT id, label, app, last_state_summary, status, scope_json, source_dictation_ids_json, created_at, updated_at, expires_at FROM tasks;

DROP TABLE tasks;
ALTER TABLE tasks_new RENAME TO tasks;

CREATE INDEX idx_tasks_status ON tasks(status, app);

-- Core schema for Kivi semantic memory (entities, instructions, tasks),
-- the dictation log they trace back to, and the audit/telemetry tables
-- that make every decision inspectable.

CREATE TABLE dictations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    raw_asr TEXT NOT NULL,
    formatted_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL CHECK (source IN ('own_corpus', 'sarvam_import', 'manual')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surface_forms_json TEXT NOT NULL,      -- JSON array of strings
    resolved_as TEXT NOT NULL,
    role_context TEXT,
    scope_json TEXT NOT NULL DEFAULT '{}', -- {"apps": ["slack"]} or {"global": true}
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'rejected')) DEFAULT 'pending',
    source_dictation_id INTEGER REFERENCES dictations(id),
    source_quote TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    confirmed_at TEXT,
    last_used_at TEXT
);

CREATE TABLE instructions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_text TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '{}', -- {"app": "email", "persona": "work"}
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'rejected')) DEFAULT 'pending',
    active INTEGER NOT NULL DEFAULT 1,
    source_dictation_id INTEGER REFERENCES dictations(id),
    source_quote TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    confirmed_at TEXT,
    last_used_at TEXT
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    app TEXT NOT NULL,
    last_state_summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'expired')) DEFAULT 'open',
    scope_json TEXT NOT NULL DEFAULT '{}',
    source_dictation_ids_json TEXT NOT NULL DEFAULT '[]', -- JSON array, accretes
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT
);

-- Append-only audit trail: the "why" behind every memory decision.
CREATE TABLE memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dictation_id INTEGER REFERENCES dictations(id),
    candidate_type TEXT CHECK (candidate_type IN ('entity', 'instruction', 'task', NULL)),
    action TEXT NOT NULL CHECK (
        action IN ('extracted', 'proposed', 'confirmed', 'rejected', 'updated', 'expired', 'deleted', 'used')
    ),
    memory_table TEXT CHECK (memory_table IN ('entities', 'instructions', 'tasks', NULL)),
    memory_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    reasoning TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every LLM call, logged for honest latency/cost reporting.
CREATE TABLE model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose TEXT NOT NULL CHECK (purpose IN ('extraction', 'hey_kivi_intent', 'hey_kivi_action', 'hey_kivi_qa')),
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    related_dictation_id INTEGER REFERENCES dictations(id),
    related_request_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every Hey Kivi action/question, with full retrieval provenance.
CREATE TABLE hey_kivi_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('action', 'question')),
    utterance TEXT NOT NULL,
    app TEXT,
    persona TEXT,
    intent TEXT,
    retrieved_entity_ids_json TEXT NOT NULL DEFAULT '[]',
    retrieved_instruction_ids_json TEXT NOT NULL DEFAULT '[]',
    retrieved_task_ids_json TEXT NOT NULL DEFAULT '[]',
    retrieved_dictation_ids_json TEXT NOT NULL DEFAULT '[]',
    result_text TEXT,
    grounded INTEGER NOT NULL DEFAULT 0,
    refused INTEGER NOT NULL DEFAULT 0,
    reasoning TEXT,
    latency_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_entities_status ON entities(status);
CREATE INDEX idx_instructions_status ON instructions(status);
CREATE INDEX idx_tasks_status ON tasks(status, app);
CREATE INDEX idx_memory_events_dictation ON memory_events(dictation_id);
CREATE INDEX idx_dictations_source ON dictations(source);

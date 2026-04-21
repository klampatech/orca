"""Database schema definitions and initialization for the Ralph Loop Orchestrator."""

INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    spec_path       TEXT,
    description     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'available',
    priority        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    claimed_at      TEXT,
    completed_at    TEXT,
    result_summary  TEXT,
    parent_id       TEXT REFERENCES tasks(id),
    root_spec_path  TEXT,
    ir_snippet      TEXT,  -- JSON IR section for this task (Phase 1 IR validator)
    CHECK (status IN ('available', 'claimed', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS task_runs (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    loop_id         TEXT NOT NULL,
    claimed_at      TEXT NOT NULL,
    heartbeat_at    TEXT NOT NULL,
    completed_at    TEXT,
    exit_status     INTEGER,
    result_summary  TEXT
);

CREATE TABLE IF NOT EXISTS loops (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    started_at      TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    current_task_id TEXT REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_avail ON tasks(priority DESC, created_at ASC) WHERE status = 'available';
CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_expire ON task_runs(heartbeat_at) WHERE completed_at IS NULL;
"""

HEARTBEAT_TIMEOUT_SECONDS = 300  # 5 minutes to handle long-running tasks

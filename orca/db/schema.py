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
    CHECK (status IN ('available', 'claimed', 'completed', 'failed',
                      'validation', 'blocked'))  -- Phase 2: validation, blocked
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

CREATE TABLE IF NOT EXISTS hidden_scenario_runs (
    id                  TEXT PRIMARY KEY,
    feature_id          TEXT NOT NULL REFERENCES tasks(id),
    loop_id             TEXT,
    generated_at        TEXT NOT NULL DEFAULT (datetime(utcnow())),
    scenarios_found     INTEGER NOT NULL DEFAULT 0,
    scenarios_passed    INTEGER NOT NULL DEFAULT 0,
    scenarios_failed    INTEGER NOT NULL DEFAULT 0,
    scenarios_errored   INTEGER NOT NULL DEFAULT 0,
    duration_ms         INTEGER,
    output_snippet      TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_avail ON tasks(priority DESC, created_at ASC) WHERE status = 'available';
-- idx_tasks_claimable: fast claim excluding children of validation roots
CREATE INDEX IF NOT EXISTS idx_tasks_claimable ON tasks(priority DESC, created_at ASC)
    WHERE status = 'available'
      AND (parent_id IS NULL
           OR parent_id NOT IN (SELECT id FROM tasks WHERE status = 'validation'));
CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_expire ON task_runs(heartbeat_at) WHERE completed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_hsr_feature ON hidden_scenario_runs(feature_id);
CREATE INDEX IF NOT EXISTS idx_hsr_generated ON hidden_scenario_runs(generated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_claimable ON tasks(priority DESC, created_at ASC)
    WHERE status = 'available'
      AND (parent_id IS NULL
           OR parent_id NOT IN (SELECT id FROM tasks WHERE status = 'validation'));
"""

HEARTBEAT_TIMEOUT_SECONDS = 300  # 5 minutes to handle long-running tasks
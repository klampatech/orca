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
    ir_snippet      TEXT,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    CHECK (status IN ('available', 'claimed', 'completed', 'failed',
                      'validation', 'blocked'))
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
    generated_at        TEXT NOT NULL,
    scenarios_found     INTEGER NOT NULL DEFAULT 0,
    scenarios_passed    INTEGER NOT NULL DEFAULT 0,
    scenarios_failed    INTEGER NOT NULL DEFAULT 0,
    scenarios_errored   INTEGER NOT NULL DEFAULT 0,
    duration_ms         INTEGER,
    output_snippet      TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_avail ON tasks(priority DESC, created_at ASC) WHERE status = 'available';

-- Tasks that have failed too many times are excluded from claiming
CREATE INDEX IF NOT EXISTS idx_tasks_failure ON tasks(failure_count) WHERE failure_count >= 5;
CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_expire ON task_runs(heartbeat_at) WHERE completed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_hsr_feature ON hidden_scenario_runs(feature_id);
CREATE INDEX IF NOT EXISTS idx_hsr_generated ON hidden_scenario_runs(generated_at);
"""

HEARTBEAT_TIMEOUT_SECONDS = 300  # 5 minutes


def init_db_schema(conn):
    """Initialize database schema with version detection.

    Creates additional indexes based on SQLite version capabilities.
    Note: Subqueries in partial indexes are not supported in this SQLite build.

    Args:
        conn: Active SQLite connection.
    """
    import sqlite3

    # Get SQLite version
    version = sqlite3.sqlite_version
    major, minor = map(int, version.split(".")[:2])

    # Note: Even with SQLite 3.35+, subqueries in partial indexes are disabled
    # in this Python/SQLite build. Using simpler fallback index.
    #
    # The claim_task logic in models/task.py handles filtering out children
    # of validation tasks at the application layer instead of the database layer.
    try:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_claimable ON tasks(priority DESC, created_at ASC)
            WHERE status = 'available' AND parent_id IS NULL
        """)
    except Exception:
        # Index may already exist from previous init
        pass

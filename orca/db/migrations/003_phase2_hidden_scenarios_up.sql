-- Phase 2 migration: Add hidden scenario validation support
--
-- Adds Phase 2 features:
--   - New task statuses: 'validation', 'blocked'
--   - hidden_scenario_runs audit table
--   - idx_tasks_claimable partial index (excludes children of validation roots)
--
-- SQLite does not support ALTER TABLE ... DROP CONSTRAINT.
-- This migration recreates the tasks table atomically:
--   1. Create new table with updated CHECK constraint
--   2. Copy data from old table
--   3. Drop old table
--   4. Rename new table
--   5. Recreate indexes
--   6. Create hidden_scenario_runs table
--   7. Create remaining indexes
--
-- Requires: SQLite >= 3.35.0 for RETURNING clause support

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- ============================================================
-- Step 1: Recreate tasks table with expanded CHECK constraint
-- ============================================================

CREATE TABLE IF NOT EXISTS tasks_new (
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
    CHECK (status IN (
        'available', 'claimed', 'completed', 'failed',
        'validation', 'blocked'  -- Phase 2: validation, blocked
    ))
);

-- Copy all data from existing tasks table
INSERT INTO tasks_new
  SELECT * FROM tasks;

-- Drop old table and rename
DROP TABLE tasks;
ALTER TABLE tasks_new RENAME TO tasks;

-- Re-create Phase 1 indexes
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_avail ON tasks(priority DESC, created_at ASC) WHERE status = 'available';

-- Re-create task_runs indexes
CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_expire ON task_runs(heartbeat_at) WHERE completed_at IS NULL;

-- ============================================================
-- Step 2: Phase 2 — idx_tasks_claimable partial index
-- ============================================================
--
-- Fast claim: exclude children of validation roots.
-- The WHERE clause ensures only tasks whose parent is NOT a validation
-- root are returned. This prevents claiming blocked descendants during
-- hidden scenario validation.

CREATE INDEX IF NOT EXISTS idx_tasks_claimable ON tasks(priority DESC, created_at ASC)
    WHERE status = 'available'
      AND (parent_id IS NULL
           OR parent_id NOT IN (SELECT id FROM tasks WHERE status = 'validation'));

-- ============================================================
-- Step 3: Create hidden_scenario_runs audit table
-- ============================================================

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

-- ============================================================
-- Step 4: Create hidden_scenario_runs indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_hsr_feature ON hidden_scenario_runs(feature_id);
CREATE INDEX IF NOT EXISTS idx_hsr_generated ON hidden_scenario_runs(generated_at);

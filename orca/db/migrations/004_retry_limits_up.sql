-- Retry limits migration: Add failure tracking for tasks
--
-- Adds retry limit support:
--   - failure_count: how many times a task has failed
--   - last_error: the most recent error message
--
-- Tasks with failure_count >= 5 are excluded from claiming.
--
-- Requires: SQLite >= 3.7.2 for ALTER TABLE ADD COLUMN

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- Add failure_count column (default 0)
ALTER TABLE tasks ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0;

-- Add last_error column for tracking the most recent failure
ALTER TABLE tasks ADD COLUMN last_error TEXT;

-- Index for finding over-failed tasks quickly
CREATE INDEX IF NOT EXISTS idx_tasks_failure ON tasks(failure_count) WHERE failure_count >= 5;

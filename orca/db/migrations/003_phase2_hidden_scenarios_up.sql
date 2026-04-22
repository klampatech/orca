-- Phase 2 migration: Add hidden scenario validation support
-- Adds: validation/blocked task states, hidden_scenario_runs table, idx_tasks_claimable index

-- This migration is for fresh databases (already applied via schema.py INIT_SQL)
-- For existing databases, run this SQL manually:

-- 1. Recreate tasks table with expanded CHECK constraint
--    (SQLite does not support ALTER TABLE ... DROP CONSTRAINT)
--    Steps: create new table → copy data → drop old → rename new

-- PRAGMA journal_mode=WAL;  -- Already set
-- PRAGMA busy_timeout=5000;  -- Already set
-- PRAGMA foreign_keys=ON;  -- Already set

-- For existing databases, the schema.py handles this on init.
-- Manual migration for production:
-- CREATE TABLE IF NOT EXISTS hidden_scenario_runs (
--     id                  TEXT PRIMARY KEY,
--     feature_id          TEXT NOT NULL REFERENCES tasks(id),
--     loop_id             TEXT,
--     generated_at        TEXT NOT NULL DEFAULT (datetime(utcnow())),
--     scenarios_found     INTEGER NOT NULL DEFAULT 0,
--     scenarios_passed    INTEGER NOT NULL DEFAULT 0,
--     scenarios_failed    INTEGER NOT NULL DEFAULT 0,
--     scenarios_errored   INTEGER NOT NULL DEFAULT 0,
--     duration_ms         INTEGER,
--     output_snippet      TEXT
-- );
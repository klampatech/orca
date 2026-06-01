"""Regression tests for metrics command utcnow SQLite function crash.

Tests that metrics command properly registers the utcnow function
as a SQLite function and can execute queries without errors.
"""

import pytest
from pathlib import Path
import tempfile
import os

from orca.db.connection import init_database, get_connection
from orca.commands.metrics import handle_metrics


@pytest.fixture
def temp_orch_dir():
    """Create a temporary orch directory with initialized database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        init_database()
        yield Path(tmpdir)
        os.chdir(orig_cwd)


@pytest.fixture
def db_connection(temp_orch_dir):
    """Provide a database connection for test setup."""
    conn = get_connection()
    yield conn
    conn.close()


def create_task(conn, task_id: str, status: str, description: str = "Test task",
                claimed_at: str | None = None, completed_at: str | None = None) -> None:
    """Helper to create a task in the database."""
    from orca.utils.time import utcnow
    now = utcnow()
    conn.execute(
        """
        INSERT INTO tasks (id, description, status, priority, created_at, claimed_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, description, status, 5, now, claimed_at, completed_at),
    )


def create_loop(conn, loop_id: str, heartbeat_offset: int = 0) -> None:
    """Helper to create a loop in the database."""
    from orca.utils.time import utcnow
    from datetime import datetime, timedelta, timezone

    now = utcnow()
    # Create heartbeat in the past based on offset
    if heartbeat_offset > 0:
        past = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_offset)
        heartbeat = past.isoformat().replace("+00:00", "Z")
    else:
        heartbeat = now

    conn.execute(
        """
        INSERT INTO loops (id, started_at, last_heartbeat_at)
        VALUES (?, ?, ?)
        """,
        (loop_id, now, heartbeat),
    )


class TestMetricsUtcnowFunction:
    """Tests for utcnow SQLite function registration."""

    def test_metrics_runs_without_error(self, temp_orch_dir):
        """Metrics command should run without SQLite errors."""
        # This should not raise any exceptions
        result = handle_metrics(None)

        assert result["command"] == "metrics"
        assert "total_tasks" in result

    def test_metrics_returns_by_status(self, db_connection):
        """Metrics should return task counts by status."""
        create_task(db_connection, "TASK-001", "available")
        create_task(db_connection, "TASK-002", "claimed")
        create_task(db_connection, "TASK-003", "completed")

        result = handle_metrics(None)

        assert "by_status" in result
        assert result["total_tasks"] == 3

    def test_metrics_active_loops_query(self, db_connection):
        """Metrics should correctly query active loops using utcnow."""
        # Create a loop with recent heartbeat (active)
        create_loop(db_connection, "LOOP-001", heartbeat_offset=30)
        # Create a loop with old heartbeat (inactive)
        create_loop(db_connection, "LOOP-002", heartbeat_offset=120)

        result = handle_metrics(None)

        # The query uses utcnow() to filter active loops
        assert "active_loops" in result
        # LOOP-001 should be active (30s < 60s timeout), LOOP-002 inactive
        assert result["active_loops"] >= 1


class TestMetricsWithHeartbeatData:
    """Tests for metrics with heartbeat data."""

    def test_metrics_with_completed_tasks(self, db_connection):
        """Metrics should calculate duration stats for completed tasks."""
        from orca.utils.time import utcnow
        from datetime import datetime, timedelta, timezone

        # Create completed task with timing data
        now = datetime.now(timezone.utc)
        claimed = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        completed = now.isoformat().replace("+00:00", "Z")

        create_task(db_connection, "TASK-001", "completed", claimed_at=claimed, completed_at=completed)

        result = handle_metrics(None)

        assert result["total_tasks"] == 1
        assert result["by_status"]["completed"]["count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
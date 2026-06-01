"""Regression tests for status command KeyError crash.

Tests that status command handles all task statuses without crashing,
specifically the 'validation' and 'blocked' statuses which were missing
from the by_status dict causing KeyError crashes.
"""

import pytest
from pathlib import Path
import tempfile
import os

from orca.db.connection import init_database, get_connection, get_db_path
from orca.commands.status import handle_status, format_status_human


@pytest.fixture
def temp_orch_dir():
    """Create a temporary orch directory with initialized database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        db_path = init_database()
        yield Path(tmpdir)
        os.chdir(orig_cwd)


@pytest.fixture
def db_connection(temp_orch_dir):
    """Provide a database connection for test setup."""
    conn = get_connection()
    yield conn
    conn.close()


def create_task(conn, task_id: str, status: str, description: str = "Test task") -> None:
    """Helper to create a task in the database."""
    from orca.utils.time import utcnow
    now = utcnow()
    conn.execute(
        """
        INSERT INTO tasks (id, description, status, priority, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (task_id, description, status, 5, now),
    )


class TestStatusValidationTasks:
    """Tests for handling validation status tasks."""

    def test_status_with_validation_task(self, db_connection):
        """Status command should handle tasks in 'validation' status."""
        create_task(db_connection, "TASK-001", "validation", "Task needing validation")

        result = handle_status(None)

        assert result["command"] == "status"
        assert "validation" in result["by_status"]
        assert len(result["by_status"]["validation"]) == 1
        assert result["by_status"]["validation"][0]["id"] == "TASK-001"

    def test_status_format_validation_tasks(self, db_connection):
        """Format status should display validation tasks correctly."""
        create_task(db_connection, "TASK-002", "validation", "Another validation task")

        result = handle_status(None)
        formatted = format_status_human(result)

        assert "Validation" in formatted
        assert "TASK-002" in formatted


class TestStatusBlockedTasks:
    """Tests for handling blocked status tasks."""

    def test_status_with_blocked_task(self, db_connection):
        """Status command should handle tasks in 'blocked' status."""
        create_task(db_connection, "TASK-003", "blocked", "Blocked task")

        result = handle_status(None)

        assert result["command"] == "status"
        assert "blocked" in result["by_status"]
        assert len(result["by_status"]["blocked"]) == 1
        assert result["by_status"]["blocked"][0]["id"] == "TASK-003"

    def test_status_format_blocked_tasks(self, db_connection):
        """Format status should display blocked tasks correctly."""
        create_task(db_connection, "TASK-004", "blocked", "Another blocked task")

        result = handle_status(None)
        formatted = format_status_human(result)

        assert "Blocked" in formatted
        assert "TASK-004" in formatted


class TestStatusAllStatuses:
    """Tests for handling all task statuses together."""

    def test_status_with_all_statuses(self, db_connection):
        """Status command should handle all task statuses without KeyError."""
        statuses = ["available", "claimed", "validation", "blocked", "completed", "failed"]
        for i, status in enumerate(statuses):
            create_task(db_connection, f"TASK-{i:03d}", status, f"Task in {status} status")

        result = handle_status(None)

        assert result["command"] == "status"
        for status in statuses:
            assert status in result["by_status"], f"Missing status: {status}"

    def test_status_empty_by_status_keys(self, db_connection):
        """All status keys should exist even when no tasks in that status."""
        create_task(db_connection, "TASK-001", "available", "Only available task")

        result = handle_status(None)

        expected_statuses = ["available", "claimed", "validation", "blocked", "completed", "failed"]
        for status in expected_statuses:
            assert status in result["by_status"], f"Missing status key: {status}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""Integration tests for orch fail command."""

import pytest
from pathlib import Path
import os

from orca.db.connection import get_connection
from orca.commands.fail import handle_fail, format_fail_human


class TestFailCommand:
    """Tests for handle_fail function."""

    def test_fail_task_returns_to_pool(self, temp_orch_dir, db_connection):
        """Failing a task without --permanent should return it to pool."""
        from tests.integration.test_commands.conftest import create_task, create_loop
        from orca.utils.time import utcnow

        now = utcnow()
        create_task(
            db_connection,
            "TASK-001",
            "claimed",
            "Task to fail",
            claimed_at=now,
        )
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            task_id = "TASK-001"
            loop_id = "LOOP-001"
            error = "Rate limit exceeded"
            permanent = False

        result = handle_fail(MockArgs())

        assert result["command"] == "fail"
        assert result["status"] == "success"
        assert result["returned_to_pool"] is True

        # Verify in database - task should be back to available
        task = db_connection.execute(
            "SELECT status FROM tasks WHERE id = ?", ("TASK-001",)
        ).fetchone()
        assert task[0] == "available"

    def test_fail_task_permanent(self, temp_orch_dir, db_connection):
        """Failing with --permanent should mark as failed permanently."""
        from tests.integration.test_commands.conftest import create_task, create_loop
        from orca.utils.time import utcnow

        now = utcnow()
        create_task(
            db_connection,
            "TASK-001",
            "claimed",
            "Task to fail permanently",
            claimed_at=now,
        )
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            task_id = "TASK-001"
            loop_id = "LOOP-001"
            error = "Unrecoverable error"
            permanent = True

        result = handle_fail(MockArgs())

        assert result["status"] == "success"
        assert result["returned_to_pool"] is False

        # Verify in database - task should be marked failed
        task = db_connection.execute(
            "SELECT status FROM tasks WHERE id = ?", ("TASK-001",)
        ).fetchone()
        assert task[0] == "failed"

    def test_fail_creates_task_run(self, temp_orch_dir, db_connection):
        """Failing should create a task run record with exit status 1."""
        from tests.integration.test_commands.conftest import create_task, create_loop, create_task_run
        from orca.utils.time import utcnow

        now = utcnow()
        create_task(
            db_connection,
            "TASK-002",
            "claimed",
            "Task with run record",
            claimed_at=now,
        )
        create_loop(db_connection, "LOOP-002")
        create_task_run(db_connection, "TASK-002", "LOOP-002", now)

        class MockArgs:
            task_id = "TASK-002"
            loop_id = "LOOP-002"
            error = "Test error"
            permanent = False

        result = handle_fail(MockArgs())

        # Check task run was created with exit_status 1 (failure)
        run = db_connection.execute(
            "SELECT exit_status, result_summary FROM task_runs WHERE task_id = ?",
            ("TASK-002",),
        ).fetchone()
        assert run is not None, "Task run should be created on failure"
        assert run[0] == 1  # exit_status for failure
        assert "Test error" in run[1]


class TestFailFormat:
    """Tests for format_fail_human function."""

    def test_format_fail_returned_to_pool(self):
        """Formatting failure with pool return should show it."""
        result = {
            "status": "success",
            "task_id": "TASK-001",
            "error": "Rate limit exceeded",
            "returned_to_pool": True,
        }

        formatted = format_fail_human(result)

        assert "TASK-001" in formatted
        assert "returned to pool" in formatted
        assert "Rate limit exceeded" in formatted

    def test_format_fail_permanent(self):
        """Formatting permanent failure should show it."""
        result = {
            "status": "success",
            "task_id": "TASK-001",
            "error": "Unrecoverable",
            "returned_to_pool": False,
        }

        formatted = format_fail_human(result)

        assert "TASK-001" in formatted
        assert "marked failed" in formatted
        assert "returned to pool" not in formatted

    def test_format_fail_minimal(self):
        """Formatting should work with minimal result dict."""
        result = {
            "task_id": "TASK-999",
            "returned_to_pool": True,
        }

        formatted = format_fail_human(result)

        assert "TASK-999" in formatted
"""Integration tests for orch complete command."""

import pytest
from pathlib import Path
import os
import tempfile
from unittest.mock import patch

from orca.db.connection import get_connection
from orca.commands.complete import handle_complete, format_complete_human


class TestCompleteCommand:
    """Tests for handle_complete function."""

    def test_complete_claimed_task(self, temp_orch_dir, db_connection):
        """Completing a claimed task should update status to completed."""
        from tests.integration.test_commands.conftest import create_task, create_loop
        from orca.utils.time import utcnow

        now = utcnow()
        create_task(
            db_connection,
            "TASK-001",
            "claimed",
            "Claimed task",
            claimed_at=now,
        )
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            task_id = "TASK-001"
            loop_id = "LOOP-001"
            result = None
            no_verify = True  # Skip verification in tests

        # Mock the validation trigger to avoid needing root_spec_path
        with patch('orca.commands.complete._trigger_feature_validation_if_complete'):
            result = handle_complete(MockArgs())

        assert result["command"] == "complete"
        assert result["task_id"] == "TASK-001"

        # Verify in database
        task = db_connection.execute(
            "SELECT status FROM tasks WHERE id = ?", ("TASK-001",)
        ).fetchone()
        assert task[0] == "completed"

    def test_complete_with_result_summary(self, temp_orch_dir, db_connection):
        """Completing with result summary should store it."""
        from tests.integration.test_commands.conftest import create_task, create_loop
        from orca.utils.time import utcnow

        now = utcnow()
        create_task(
            db_connection,
            "TASK-001",
            "claimed",
            "Task with result",
            claimed_at=now,
        )
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            task_id = "TASK-001"
            loop_id = "LOOP-001"
            result = "All tests passed, 42 assertions"
            no_verify = True

        with patch('orca.commands.complete._trigger_feature_validation_if_complete'):
            result = handle_complete(MockArgs())

        assert result.get("task_id") == "TASK-001"
        # Verify result summary is stored
        task = db_connection.execute(
            "SELECT result_summary FROM tasks WHERE id = ?", ("TASK-001",)
        ).fetchone()
        assert task[0] == "All tests passed, 42 assertions"

    def test_complete_task_run_recorded(self, temp_orch_dir, db_connection):
        """Completing should create a task run record."""
        from tests.integration.test_commands.conftest import create_task, create_loop, create_task_run
        from orca.utils.time import utcnow

        now = utcnow()
        create_task(
            db_connection,
            "TASK-002",
            "claimed",
            "Task run recording",
            claimed_at=now,
        )
        create_loop(db_connection, "LOOP-002")
        create_task_run(db_connection, "TASK-002", "LOOP-002", now)

        class MockArgs:
            task_id = "TASK-002"
            loop_id = "LOOP-002"
            result = "Completed successfully"
            no_verify = True

        with patch('orca.commands.complete._trigger_feature_validation_if_complete'):
            result = handle_complete(MockArgs())

        # Check task run was created with exit_status 0
        run = db_connection.execute(
            "SELECT exit_status, result_summary FROM task_runs WHERE task_id = ?",
            ("TASK-002",),
        ).fetchone()
        assert run is not None
        assert run[0] == 0  # exit_status for success


class TestCompleteFormat:
    """Tests for format_complete_human function."""

    def test_format_complete_success(self):
        """Formatting complete result should show success message."""
        result = {
            "status": "success",
            "task_id": "TASK-001",
            "result": None,
        }

        formatted = format_complete_human(result)

        assert "TASK-001" in formatted
        assert "completed" in formatted.lower()

    def test_format_complete_with_result(self):
        """Formatting should include result when present."""
        result = {
            "status": "success",
            "task_id": "TASK-001",
            "result": "All tests passed",
        }

        formatted = format_complete_human(result)

        assert "TASK-001" in formatted
        assert "All tests passed" in formatted

    def test_format_complete_minimal(self):
        """Formatting should work with minimal result dict."""
        result = {
            "task_id": "TASK-999",
        }

        formatted = format_complete_human(result)

        assert "TASK-999" in formatted
"""Integration tests for orch info command."""

import pytest
from pathlib import Path
import os

from orca.db.connection import get_connection
from orca.commands.info import handle_info, format_info_human


class TestInfoCommand:
    """Tests for handle_info function."""

    def test_info_existing_task(self, temp_orch_dir, db_connection):
        """Getting info for existing task should return full details."""
        from tests.integration.test_commands.conftest import create_task

        create_task(
            db_connection,
            "TASK-001",
            "claimed",
            "Detailed task",
            priority=7,
            spec_path="/path/to/spec.md",
        )

        class MockArgs:
            task_id = "TASK-001"

        result = handle_info(MockArgs())

        assert result["command"] == "info"
        assert result["id"] == "TASK-001"
        assert result["description"] == "Detailed task"
        assert result["priority"] == 7
        assert result["status"] == "claimed"

    def test_info_nonexistent_task(self, temp_orch_dir, db_connection):
        """Getting info for non-existent task should return error."""
        class MockArgs:
            task_id = "TASK-DOES-NOT-EXIST"

        result = handle_info(MockArgs())

        assert result["command"] == "info"
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_info_task_with_timestamps(self, temp_orch_dir, db_connection):
        """Info should include timing information when present."""
        from tests.integration.test_commands.conftest import create_task
        from orca.utils.time import utcnow

        now = utcnow()
        create_task(
            db_connection,
            "TASK-001",
            "completed",
            "Completed task",
            claimed_at=now,
            completed_at=now,
        )

        class MockArgs:
            task_id = "TASK-001"

        result = handle_info(MockArgs())

        assert result["claimed_at"] is not None
        assert result["completed_at"] is not None

    def test_info_task_with_hierarchy(self, temp_orch_dir, db_connection):
        """Info should show parent info when present."""
        from tests.integration.test_commands.conftest import create_task

        create_task(
            db_connection,
            "TASK-PARENT",
            "completed",
            "Parent task",
        )
        create_task(
            db_connection,
            "TASK-CHILD",
            "available",
            "Child task",
            parent_id="TASK-PARENT",
            root_spec_path="/root/spec.md",
        )

        class MockArgs:
            task_id = "TASK-CHILD"

        result = handle_info(MockArgs())

        assert result["parent_id"] == "TASK-PARENT"
        assert result["root_spec_path"] == "/root/spec.md"


class TestInfoFormat:
    """Tests for format_info_human function."""

    def test_format_basic_task(self):
        """Formatting should show all task details."""
        result = {
            "id": "TASK-001",
            "description": "Test task",
            "status": "claimed",
            "priority": 5,
            "created_at": "2024-01-01T00:00:00Z",
            "claimed_at": "2024-01-01T01:00:00Z",
        }

        formatted = format_info_human(result)

        assert "Task: TASK-001" in formatted
        assert "Test task" in formatted
        assert "Status: claimed" in formatted
        assert "Priority: 5" in formatted
        assert "Created:" in formatted
        assert "Claimed:" in formatted

    def test_format_task_with_spec(self):
        """Formatting should include spec paths when present."""
        result = {
            "id": "TASK-001",
            "description": "Task with specs",
            "status": "available",
            "priority": 3,
            "created_at": "2024-01-01T00:00:00Z",
            "spec_path": "/path/to/spec.md",
            "root_spec_path": "/root/spec.md",
        }

        formatted = format_info_human(result)

        assert "Spec:" in formatted
        assert "Root spec:" in formatted

    def test_format_error_task(self):
        """Formatting error result should show error message."""
        result = {
            "status": "error",
            "message": "Task TASK-999 not found.",
        }

        formatted = format_info_human(result)

        assert "Task TASK-999 not found." in formatted
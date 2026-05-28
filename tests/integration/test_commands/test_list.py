"""Integration tests for orch list command."""

import pytest
from pathlib import Path
import os

from orca.db.connection import get_connection
from orca.commands.list import handle_list, format_list_human


class TestListCommand:
    """Tests for handle_list function."""

    def test_list_all_tasks(self, temp_orch_dir, db_connection):
        """Listing all tasks should return all tasks."""
        from tests.integration.test_commands.conftest import create_task

        create_task(db_connection, "TASK-001", "available", "Task 1")
        create_task(db_connection, "TASK-002", "claimed", "Task 2")
        create_task(db_connection, "TASK-003", "completed", "Task 3")

        class MockArgs:
            status = None

        result = handle_list(MockArgs())

        assert result["command"] == "list"
        assert result["status"] == "success"
        assert result["count"] == 3
        assert len(result["tasks"]) == 3

    def test_list_filter_by_status(self, temp_orch_dir, db_connection):
        """Listing with status filter should return only matching tasks."""
        from tests.integration.test_commands.conftest import create_task

        create_task(db_connection, "TASK-001", "available", "Available task 1")
        create_task(db_connection, "TASK-002", "available", "Available task 2")
        create_task(db_connection, "TASK-003", "claimed", "Claimed task")
        create_task(db_connection, "TASK-004", "completed", "Completed task")

        class MockArgs:
            status = "available"

        result = handle_list(MockArgs())

        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["filter"] == "available"
        assert all(t["status"] == "available" for t in result["tasks"])

    def test_list_empty_result(self, temp_orch_dir, db_connection):
        """Listing with no tasks should return empty list."""
        class MockArgs:
            status = None

        result = handle_list(MockArgs())

        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["tasks"] == []

    def test_list_filter_no_matches(self, temp_orch_dir, db_connection):
        """Listing with filter returning no matches should return empty list."""
        from tests.integration.test_commands.conftest import create_task

        create_task(db_connection, "TASK-001", "available", "Available task")

        class MockArgs:
            status = "completed"

        result = handle_list(MockArgs())

        assert result["count"] == 0
        assert result["tasks"] == []


class TestListFormat:
    """Tests for format_list_human function."""

    def test_format_list_with_tasks(self):
        """Formatting list with tasks should show task details."""
        result = {
            "filter": None,
            "count": 2,
            "tasks": [
                {"id": "TASK-001", "description": "Task 1", "priority": 5},
                {"id": "TASK-002", "description": "Task 2", "priority": 3},
            ],
        }

        formatted = format_list_human(result)

        assert "Tasks" in formatted
        assert "TASK-001" in formatted
        assert "Task 1" in formatted
        assert "P5" in formatted
        assert "TASK-002" in formatted

    def test_format_filtered_list(self):
        """Formatting filtered list should show filter in header."""
        result = {
            "filter": "completed",
            "count": 1,
            "tasks": [
                {"id": "TASK-001", "description": "Done task", "priority": 5},
            ],
        }

        formatted = format_list_human(result)

        assert "[completed]" in formatted

    def test_format_empty_list(self):
        """Formatting empty list should show no tasks message."""
        result = {
            "filter": "failed",
            "count": 0,
            "tasks": [],
        }

        formatted = format_list_human(result)

        assert "No tasks found" in formatted
        assert "(failed)" in formatted
"""Integration tests for orch add command."""

import pytest
from pathlib import Path
import tempfile
import os

from orca.db.connection import get_connection
from orca.commands.add import handle_add, format_add_human


class TestAddCommand:
    """Tests for handle_add function."""

    def test_add_basic_task(self, temp_orch_dir, db_connection):
        """Adding a basic task should succeed with all fields."""
        # Create a mock args object
        class MockArgs:
            spec = None
            description = "Implement user authentication"
            priority = 3

        result = handle_add(MockArgs())

        assert result["command"] == "add"
        assert result["id"] is not None
        assert result["description"] == "Implement user authentication"
        assert result["priority"] == 3
        assert "created_at" in result

    def test_add_task_with_priority(self, temp_orch_dir, db_connection):
        """Adding task with high priority should store it correctly."""
        class MockArgs:
            spec = None
            description = "Critical bug fix"
            priority = 9

        result = handle_add(MockArgs())

        assert result["priority"] == 9

    def test_add_task_with_spec_path(self, temp_orch_dir, db_connection):
        """Adding task with spec path should copy the file."""
        # Create a temporary spec file
        spec_content = """---
title: Test Task
description: A test task spec
---
# Task
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(spec_content)
            spec_file = f.name

        try:
            class MockArgs:
                spec = spec_file
                description = "Spec task"
                priority = 5

            result = handle_add(MockArgs())

            assert result.get("id") is not None
            assert result["spec_path"] is not None
            # The spec should be copied to the tasks directory
            assert "tasks" in result["spec_path"]
        finally:
            os.unlink(spec_file)

    def test_add_multiple_tasks(self, temp_orch_dir, db_connection):
        """Adding multiple tasks should create unique IDs."""
        class MockArgs:
            spec = None
            priority = 5

        results = []
        for i in range(3):
            MockArgs.description = f"Task {i}"
            results.append(handle_add(MockArgs()))

        # All should have unique IDs
        ids = [r["id"] for r in results]
        assert len(ids) == len(set(ids))


class TestAddFormat:
    """Tests for format_add_human function."""

    def test_format_basic_task(self):
        """Formatting should include task ID, priority, and description."""
        result = {
            "id": "TASK-001",
            "description": "Test task",
            "priority": 3,
        }

        formatted = format_add_human(result)

        assert "TASK-001" in formatted
        assert "priority: 3" in formatted
        assert "Test task" in formatted

    def test_format_task_with_spec(self):
        """Formatting should include spec path when present."""
        result = {
            "id": "TASK-002",
            "description": "Task with spec",
            "priority": 5,
            "spec_path": "/path/to/spec.md",
        }

        formatted = format_add_human(result)

        assert "Spec:" in formatted
        assert "/path/to/spec.md" in formatted
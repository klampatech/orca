"""Integration tests for orch claim command."""

import pytest
from pathlib import Path
import os

from orca.db.connection import get_connection
from orca.commands.claim import handle_claim, format_claim_human


class TestClaimCommand:
    """Tests for handle_claim function."""

    def test_claim_available_task(self, temp_orch_dir, db_connection):
        """Claiming an available task should return task details."""
        from tests.integration.test_commands.conftest import create_task, create_loop

        # Create a task
        create_task(db_connection, "TASK-001", "available", "Claimable task", priority=5)
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            loop_id = "LOOP-001"

        result = handle_claim(MockArgs())

        assert result["command"] == "claim"
        assert result["status"] == "success"
        assert result["task_id"] == "TASK-001"
        assert result["loop_id"] == "LOOP-001"
        assert "claimed_at" in result

    def test_claim_empty_backlog(self, temp_orch_dir, db_connection):
        """Claiming when no tasks available should return empty status."""
        from tests.integration.test_commands.conftest import create_loop

        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            loop_id = "LOOP-001"

        result = handle_claim(MockArgs())

        assert result["command"] == "claim"
        assert result["status"] == "empty"
        assert "No available tasks" in result["message"]

    def test_claim_highest_priority(self, temp_orch_dir, db_connection):
        """Should claim highest priority task first."""
        from tests.integration.test_commands.conftest import create_task, create_loop

        # Create tasks with different priorities
        create_task(db_connection, "TASK-LOW", "available", "Low priority", priority=1)
        create_task(db_connection, "TASK-HIGH", "available", "High priority", priority=10)
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            loop_id = "LOOP-001"

        result = handle_claim(MockArgs())

        assert result["status"] == "success"
        assert result["task_id"] == "TASK-HIGH"

    def test_claim_skips_claimed_tasks(self, temp_orch_dir, db_connection):
        """Should skip already claimed tasks."""
        from tests.integration.test_commands.conftest import create_task, create_loop

        create_task(db_connection, "TASK-CLAIMED", "claimed", "Already claimed")
        create_task(db_connection, "TASK-AVAIL", "available", "Available task")
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            loop_id = "LOOP-001"

        result = handle_claim(MockArgs())

        assert result["status"] == "success"
        assert result["task_id"] == "TASK-AVAIL"

    def test_claim_skips_validation_tasks(self, temp_orch_dir, db_connection):
        """Should skip tasks in validation status."""
        from tests.integration.test_commands.conftest import create_task, create_loop

        create_task(db_connection, "TASK-VALIDATION", "validation", "Validation task")
        create_task(db_connection, "TASK-AVAIL", "available", "Available task")
        create_loop(db_connection, "LOOP-001")

        class MockArgs:
            loop_id = "LOOP-001"

        result = handle_claim(MockArgs())

        assert result["status"] == "success"
        assert result["task_id"] == "TASK-AVAIL"


class TestClaimFormat:
    """Tests for format_claim_human function."""

    def test_format_claimed_task(self):
        """Formatting claimed task should show all details."""
        result = {
            "status": "success",
            "task_id": "TASK-001",
            "description": "Test task",
            "spec_path": "/path/to/spec.md",
            "priority": 5,
            "loop_id": "LOOP-001",
        }

        formatted = format_claim_human(result)

        assert "TASK-001" in formatted
        assert "Test task" in formatted
        assert "Spec:" in formatted
        assert "Priority: 5" in formatted
        assert "LOOP-001" in formatted

    def test_format_empty_status(self):
        """Formatting empty status should show no tasks message."""
        result = {
            "status": "empty",
        }

        formatted = format_claim_human(result)

        assert "No available tasks" in formatted
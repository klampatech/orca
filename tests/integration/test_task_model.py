"""Integration tests for the task data access layer."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


# Reusable database fixture
@pytest.fixture
def db(initialized_db: Path):
    """Provide an initialized database (alias for convenience)."""
    return initialized_db


class TestCreateTask:
    """Tests for create_task()."""

    def test_creates_task_with_required_fields(self, db):
        """Should create a task with only the required description."""
        from orca.models.task import create_task

        task = create_task("Test task description")

        assert task["description"] == "Test task description"
        assert task["status"] == "available"
        assert task["priority"] == 0
        assert task["id"] is not None

    def test_creates_task_with_spec_path(self, db):
        """Should create a task with spec_path."""
        from orca.models.task import create_task

        task = create_task("Test task", spec_path="/path/to/spec.md")

        assert task["spec_path"] == "/path/to/spec.md"

    def test_creates_task_with_priority(self, db):
        """Should create a task with specified priority."""
        from orca.models.task import create_task

        task = create_task("High priority task", priority=10)

        assert task["priority"] == 10

    def test_creates_task_with_parent(self, db):
        """Should create a task with parent_id."""
        from orca.models.task import create_task, get_task

        # Create a parent task first
        parent = create_task("Parent task")
        # Create child with reference to parent
        task = create_task("Child task", parent_id=parent["id"])

        assert task["parent_id"] == parent["id"]

    def test_generates_unique_id(self, db):
        """Should generate unique IDs for each task."""
        from orca.models.task import create_task

        task1 = create_task("Task 1")
        task2 = create_task("Task 2")

        assert task1["id"] != task2["id"]


class TestGetTask:
    """Tests for get_task()."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Setup: create a test task."""
        from orca.models.task import create_task

        self.task = create_task("Test task for get_task")

    def test_returns_task_when_exists(self):
        """Should return task record when task exists."""
        from orca.models.task import get_task

        result = get_task(self.task["id"])

        assert result is not None
        assert result["id"] == self.task["id"]
        assert result["description"] == "Test task for get_task"

    def test_returns_none_when_not_found(self):
        """Should return None when task doesn't exist."""
        from orca.models.task import get_task

        result = get_task("nonexistent-id")

        assert result is None


class TestListTasks:
    """Tests for list_tasks()."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Setup: create test tasks."""
        from orca.models.task import create_task

        create_task("Task 1", priority=1)
        create_task("Task 2", priority=2)
        create_task("Task 3", priority=3)

    def test_returns_all_tasks(self):
        """Should return all tasks."""
        from orca.models.task import list_tasks

        tasks = list_tasks()

        assert len(tasks) >= 3

    def test_returns_tasks_ordered_by_priority(self):
        """Should return tasks ordered by priority descending."""
        from orca.models.task import list_tasks

        tasks = list_tasks()

        assert tasks[0]["priority"] >= tasks[1]["priority"]

    def test_filters_by_status(self):
        """Should filter tasks by status."""
        from orca.models.task import list_tasks

        tasks = list_tasks(status="available")

        assert all(t["status"] == "available" for t in tasks)


class TestUpdateTaskStatus:
    """Tests for update_task_status()."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Setup: create a test task."""
        from orca.models.task import create_task

        self.task = create_task("Task to update")

    def test_updates_status(self):
        """Should update task status."""
        from orca.models.task import get_task, update_task_status

        update_task_status(self.task["id"], "completed", "Done!")
        result = get_task(self.task["id"])

        assert result["status"] == "completed"
        assert result["result_summary"] == "Done!"

    def test_returns_true_on_success(self):
        """Should return True on successful update."""
        from orca.models.task import update_task_status

        result = update_task_status(self.task["id"], "failed")

        assert result is True


class TestClaimTask:
    """Tests for claim_task()."""

    def test_claims_available_task(self, db):
        """Should claim an available task."""
        from orca.models.task import claim_task, create_task

        task = create_task("Task to claim")
        loop_id = "test-loop-123"

        result = claim_task(loop_id)

        assert result is not None
        assert result["status"] == "claimed"
        assert result["id"] == task["id"]

    def test_returns_none_when_no_tasks(self):
        """Should return None when no available tasks."""
        from orca.models.task import claim_task

        # Claim all tasks first
        while True:
            result = claim_task("loop1")
            if result is None:
                break

        # Now should return None
        result = claim_task("loop2")
        assert result is None

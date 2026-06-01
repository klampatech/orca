"""Shared fixtures for command integration tests."""

import pytest
from pathlib import Path
import tempfile
import os

from orca.db.connection import init_database, get_connection


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


def create_task(
    conn,
    task_id: str,
    status: str = "available",
    description: str = "Test task",
    priority: int = 5,
    **kwargs,
) -> None:
    """Helper to create a task in the database."""
    from orca.utils.time import utcnow

    now = utcnow()
    conn.execute(
        """
        INSERT INTO tasks (id, description, status, priority, created_at,
                          claimed_at, completed_at, spec_path, parent_id, root_spec_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            description,
            status,
            priority,
            now,
            kwargs.get("claimed_at"),
            kwargs.get("completed_at"),
            kwargs.get("spec_path"),
            kwargs.get("parent_id"),
            kwargs.get("root_spec_path"),
        ),
    )


def create_loop(conn, loop_id: str, heartbeat_offset: int = 0, current_task_id: str | None = None) -> None:
    """Helper to create a loop in the database."""
    from orca.utils.time import utcnow
    from datetime import datetime, timedelta, timezone

    now = utcnow()
    if heartbeat_offset > 0:
        past = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_offset)
        heartbeat = past.isoformat().replace("+00:00", "Z")
    else:
        heartbeat = now

    conn.execute(
        """
        INSERT INTO loops (id, started_at, last_heartbeat_at, current_task_id)
        VALUES (?, ?, ?, ?)
        """,
        (loop_id, now, heartbeat, current_task_id),
    )


def create_task_run(conn, task_id: str, loop_id: str, claimed_at: str | None = None) -> None:
    """Helper to create a task run record in the database.

    Args:
        conn: Database connection
        task_id: ID of the task
        loop_id: ID of the loop
        claimed_at: ISO8601 timestamp when task was claimed (defaults to now)
    """
    from orca.utils.time import utcnow
    import uuid

    now = utcnow()
    run_id = str(uuid.uuid4())

    conn.execute(
        """
        INSERT INTO task_runs (id, task_id, loop_id, claimed_at, heartbeat_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, task_id, loop_id, claimed_at or now, now),
    )
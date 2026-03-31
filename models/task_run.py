"""Task run data access layer for the Ralph Loop Orchestrator."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from db.connection import get_connection
from db.schema import HEARTBEAT_TIMEOUT_SECONDS
from utils.time import utcnow


def create_task_run(
    conn: sqlite3.Connection,
    task_id: str,
    loop_id: str,
    claimed_at: str,
) -> dict[str, Any]:
    """Create a new task run record within an existing transaction.

    Args:
        conn: Active database connection.
        task_id: ID of the task being run.
        loop_id: ID of the loop running the task.
        claimed_at: ISO8601 timestamp when the task was claimed.

    Returns:
        The created task run record.
    """
    run_id = str(uuid.uuid4())
    now = utcnow()

    conn.execute(
        """
        INSERT INTO task_runs (id, task_id, loop_id, claimed_at, heartbeat_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, task_id, loop_id, claimed_at, now),
    )

    return {
        "id": run_id,
        "task_id": task_id,
        "loop_id": loop_id,
        "claimed_at": claimed_at,
        "heartbeat_at": now,
    }


def heartbeat_task_run(task_id: str, loop_id: str) -> bool:
    """Update the heartbeat for a task run.

    Args:
        task_id: ID of the task.
        loop_id: ID of the loop (must match the current owner).

    Returns:
        True if the heartbeat was updated, False if not found or not owned by loop.

    Raises:
        RuntimeError: if the task is not claimed by this loop.
    """
    conn = get_connection()
    now = utcnow()

    row = conn.execute(
        "SELECT id FROM task_runs WHERE task_id = ? AND completed_at IS NULL",
        (task_id,),
    ).fetchone()

    if not row:
        raise RuntimeError(f"No active task run found for task {task_id}.")

    run_id = row[0]

    cursor = conn.execute(
        """
        UPDATE task_runs SET heartbeat_at = ? WHERE id = ? AND loop_id = ?
        """,
        (now, run_id, loop_id),
    )

    if cursor.rowcount == 0:
        raise RuntimeError(f"Task {task_id} is not claimed by loop {loop_id}.")

    conn.execute(
        "UPDATE loops SET last_heartbeat_at = ? WHERE id = ?",
        (now, loop_id),
    )

    return True


def complete_task_run(
    task_id: str,
    loop_id: str,
    exit_status: int,
    result_summary: Optional[str] = None,
) -> bool:
    """Mark a task run as completed or failed.

    Args:
        task_id: ID of the task.
        loop_id: ID of the loop (must match the current owner).
        exit_status: 0 for success, 1 for failure.
        result_summary: Optional result or error message.

    Returns:
        True if the task run was completed, False if not found or not owned.
    """
    conn = get_connection()
    now = utcnow()

    cursor = conn.execute(
        """
        UPDATE task_runs
        SET completed_at = ?, exit_status = ?, result_summary = ?
        WHERE task_id = ? AND loop_id = ? AND completed_at IS NULL
        """,
        (now, exit_status, result_summary, task_id, loop_id),
    )

    if cursor.rowcount == 0:
        return False

    conn.execute(
        "UPDATE loops SET current_task_id = NULL WHERE id = ?",
        (loop_id,),
    )

    return True


def reclaim_stale_task_runs(conn: sqlite3.Connection) -> int:
    """Reclaim task runs whose heartbeat has expired.

    This method should be called within an existing transaction context
    (or it will create its own).

    Args:
        conn: Active database connection.

    Returns:
        The number of task runs reclaimed.
    """
    import sqlite3

    now = datetime.now(timezone.utc)
    threshold = now.isoformat().replace("+00:00", "Z")
    timeout_str = f"-{HEARTBEAT_TIMEOUT_SECONDS} seconds"
    threshold_dt = datetime.now(timezone.utc).timestamp() - HEARTBEAT_TIMEOUT_SECONDS
    threshold_dt = datetime.fromtimestamp(threshold_dt, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    rows = conn.execute(
        """
        SELECT tr.id, tr.task_id, tr.loop_id
        FROM task_runs tr
        JOIN tasks t ON t.id = tr.task_id
        WHERE t.status = 'claimed'
          AND tr.completed_at IS NULL
          AND tr.heartbeat_at < ?
        """,
        (threshold_dt,),
    ).fetchall()

    if not rows:
        return 0

    reclaimed = 0
    for run_id, task_id, loop_id in rows:
        conn.execute(
            "UPDATE tasks SET status = 'available', claimed_at = NULL WHERE id = ?",
            (task_id,),
        )
        conn.execute(
            "UPDATE task_runs SET completed_at = ?, exit_status = -1 WHERE id = ?",
            (utcnow(), run_id),
        )
        conn.execute(
            "UPDATE loops SET current_task_id = NULL WHERE id = ? AND current_task_id = ?",
            (loop_id, task_id),
        )
        reclaimed += 1

    return reclaimed


def reclaim_stale(where_conn: bool = False):
    """Public entry point for reclaiming stale tasks.

    Args:
        where_conn: If False (default), manages its own connection.
                   If True, caller is managing the connection.

    Returns:
        The number of task runs reclaimed.
    """
    if where_conn:
        conn = get_connection()
        return reclaim_stale_task_runs(conn)
    else:
        conn = get_connection()
        conn.execute("BEGIN")
        count = reclaim_stale_task_runs(conn)
        conn.commit()
        return count


def get_task_runs(task_id: str) -> list[dict[str, Any]]:
    """Get all task runs for a task (including history).

    Args:
        task_id: ID of the task.

    Returns:
        List of task run records ordered by claimed_at descending.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, task_id, loop_id, claimed_at, heartbeat_at, completed_at, exit_status, result_summary
        FROM task_runs
        WHERE task_id = ?
        ORDER BY claimed_at DESC
        """,
        (task_id,),
    ).fetchall()

    return [
        {
            "id": r[0],
            "task_id": r[1],
            "loop_id": r[2],
            "claimed_at": r[3],
            "heartbeat_at": r[4],
            "completed_at": r[5],
            "exit_status": r[6],
            "result_summary": r[7],
        }
        for r in rows
    ]

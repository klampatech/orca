"""Task data access layer for the Ralph Loop Orchestrator."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from ..db.connection import get_connection
from ..utils.time import utcnow


def create_task(
    description: str,
    spec_path: str | None = None,
    priority: int = 0,
    parent_id: str | None = None,
    root_spec_path: str | None = None,
    ir_snippet: str | None = None,
) -> dict[str, Any]:
    """Add a new task to the backlog.

    Args:
        description: Human-readable task description.
        spec_path: Optional path to the task specification file.
        priority: Task priority (higher = more important).
        parent_id: Optional ID of parent task (for decomposed sub-tasks).
        root_spec_path: Optional path to the original spec file.
        ir_snippet: Optional JSON IR section for IR-based tasks (Phase 1).

    Returns:
        The created task record.
    """
    conn = get_connection()
    task_id = str(uuid.uuid4())
    now = utcnow()

    conn.execute(
        """
        INSERT INTO tasks (id, spec_path, description, status, priority, created_at, parent_id, root_spec_path, ir_snippet)
        VALUES (?, ?, ?, 'available', ?, ?, ?, ?, ?)
        """,
        (task_id, spec_path, description, priority, now, parent_id, root_spec_path, ir_snippet),
    )

    return {
        "id": task_id,
        "spec_path": spec_path,
        "description": description,
        "status": "available",
        "priority": priority,
        "created_at": now,
        "claimed_at": None,
        "completed_at": None,
        "result_summary": None,
        "parent_id": parent_id,
        "root_spec_path": root_spec_path,
        "ir_snippet": ir_snippet,
    }


def create_tasks_batch(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add multiple tasks to the backlog in a single transaction.

    Args:
        tasks: List of task dicts with keys: description, spec_path, priority, parent_id, root_spec_path, ir_snippet.

    Returns:
        List of created task records with generated IDs.
    """
    conn = get_connection()
    now = utcnow()
    created = []

    for task_data in tasks:
        task_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO tasks (id, spec_path, description, status, priority, created_at, parent_id, root_spec_path, ir_snippet)
            VALUES (?, ?, ?, 'available', ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                task_data.get("spec_path"),
                task_data["description"],
                task_data.get("priority", 0),
                now,
                task_data.get("parent_id"),
                task_data.get("root_spec_path"),
                task_data.get("ir_snippet"),
            ),
        )
        created.append({
            "id": task_id,
            "spec_path": task_data.get("spec_path"),
            "description": task_data["description"],
            "status": "available",
            "priority": task_data.get("priority", 0),
            "created_at": now,
            "claimed_at": None,
            "completed_at": None,
            "result_summary": None,
            "parent_id": task_data.get("parent_id"),
            "root_spec_path": task_data.get("root_spec_path"),
            "ir_snippet": task_data.get("ir_snippet"),
        })

    conn.commit()
    return created


def get_task(task_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a task by ID.

    Returns:
        Task record dict, or None if not found.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT id, spec_path, description, status, priority, created_at, claimed_at, completed_at, result_summary, parent_id, root_spec_path, ir_snippet FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "spec_path": row[1],
        "description": row[2],
        "status": row[3],
        "priority": row[4],
        "created_at": row[5],
        "claimed_at": row[6],
        "completed_at": row[7],
        "result_summary": row[8],
        "parent_id": row[9],
        "root_spec_path": row[10],
        "ir_snippet": row[11],
    }


def list_tasks(status: Optional[str] = None) -> list[dict[str, Any]]:
    """List all tasks, optionally filtered by status.

    Args:
        status: If provided, only return tasks with this status.

    Returns:
        List of task records.
    """
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT id, spec_path, description, status, priority, created_at, claimed_at, completed_at, result_summary, parent_id, root_spec_path, ir_snippet FROM tasks WHERE status = ? ORDER BY priority DESC, created_at ASC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, spec_path, description, status, priority, created_at, claimed_at, completed_at, result_summary, parent_id, root_spec_path, ir_snippet FROM tasks ORDER BY priority DESC, created_at ASC",
        ).fetchall()

    return [
        {
            "id": r[0],
            "spec_path": r[1],
            "description": r[2],
            "status": r[3],
            "priority": r[4],
            "created_at": r[5],
            "claimed_at": r[6],
            "completed_at": r[7],
            "result_summary": r[8],
            "parent_id": r[9],
            "root_spec_path": r[10],
            "ir_snippet": r[11],
        }
        for r in rows
    ]


def update_task_status(
    task_id: str,
    status: str,
    result_summary: Optional[str] = None,
) -> bool:
    """Update a task's status.

    Args:
        task_id: Task ID.
        status: New status ('completed' or 'failed').
        result_summary: Optional result or error message.

    Returns:
        True if the task was updated, False if not found.
    """
    conn = get_connection()
    now = utcnow()
    cursor = conn.execute(
        f"UPDATE tasks SET status = ?, completed_at = ?, result_summary = ? WHERE id = ?",
        (status, now, result_summary, task_id),
    )
    return cursor.rowcount > 0


def claim_task(loop_id: str) -> Optional[dict[str, Any]]:
    """Atomically claim the highest-priority available task.

    Args:
        loop_id: ID of the loop claiming the task.

    Returns:
        The claimed task record, or None if no tasks are available.
    """
    from .loop import ensure_loop
    from .task_run import create_task_run, reclaim_stale_task_runs

    conn = get_connection()
    ensure_loop(conn, loop_id)

    conn.execute("BEGIN IMMEDIATE")
    reclaim_stale_task_runs(conn)

    row = conn.execute(
        """
        SELECT id, spec_path, description, priority, parent_id, root_spec_path, ir_snippet
        FROM tasks
        WHERE status = 'available'
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
        """,
    ).fetchone()

    if not row:
        conn.rollback()
        return None

    task_id = row[0]
    now = utcnow()

    conn.execute(
        "UPDATE tasks SET status = 'claimed', claimed_at = ? WHERE id = ? AND status = 'available'",
        (now, task_id),
    )

    if conn.total_changes == 0:
        conn.rollback()
        return None

    create_task_run(conn, task_id, loop_id, now)
    conn.execute(
        "UPDATE loops SET current_task_id = ?, last_heartbeat_at = ? WHERE id = ?",
        (task_id, now, loop_id),
    )

    conn.commit()

    return {
        "id": task_id,
        "spec_path": row[1],
        "description": row[2],
        "priority": row[3],
        "parent_id": row[4],
        "root_spec_path": row[5],
        "ir_snippet": row[6],
        "status": "claimed",
        "claimed_at": now,
        "loop_id": loop_id,
    }
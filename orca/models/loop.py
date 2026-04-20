"""Loop data access layer for the Ralph Loop Orchestrator."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from ..db.connection import get_connection
from ..utils.time import utcnow


def ensure_loop(conn: sqlite3.Connection, loop_id: str) -> dict[str, Any]:
    """Register a loop if it hasn't been seen before, or update its heartbeat.

    Args:
        conn: Active database connection.
        loop_id: Unique loop identifier.

    Returns:
        The loop record.
    """
    now = utcnow()
    row = conn.execute("SELECT id FROM loops WHERE id = ?", (loop_id,)).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO loops (id, started_at, last_heartbeat_at)
            VALUES (?, ?, ?)
            """,
            (loop_id, now, now),
        )
    else:
        conn.execute(
            "UPDATE loops SET last_heartbeat_at = ? WHERE id = ?",
            (now, loop_id),
        )

    return {"id": loop_id, "last_heartbeat_at": now}


def get_loop(loop_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a loop by ID.

    Returns:
        Loop record dict, or None if not found.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT id, name, started_at, last_heartbeat_at, current_task_id FROM loops WHERE id = ?",
        (loop_id,),
    ).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "started_at": row[2],
        "last_heartbeat_at": row[3],
        "current_task_id": row[4],
    }


def list_loops() -> list[dict[str, Any]]:
    """List all registered loops.

    Returns:
        List of loop records.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, started_at, last_heartbeat_at, current_task_id FROM loops ORDER BY started_at DESC",
    ).fetchall()

    return [
        {
            "id": r[0],
            "name": r[1],
            "started_at": r[2],
            "last_heartbeat_at": r[3],
            "current_task_id": r[4],
        }
        for r in rows
    ]

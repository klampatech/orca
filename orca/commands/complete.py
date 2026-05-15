"""orch complete — Mark a task as successfully completed."""

from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path

import shutil
import subprocess as _subprocess

# Detect SQLite version at module load time
_SQLITE_SUPPORTS_RETURNING = sqlite3.sqlite_version_info >= (3, 35, 0)

if not _SQLITE_SUPPORTS_RETURNING:
    warnings.warn(
        f"SQLite {sqlite3.sqlite_version} does not support RETURNING clause "
        "(requires ≥ 3.35.0). Atomic last-child detection is degraded — "
        "two children completing simultaneously may both trigger validation. "
        "Upgrade SQLite for correct behavior.",
        UserWarning,
        stacklevel=2,
    )


def _verify_task_complete() -> tuple[bool, str]:
    """Run validation tests before completing. Returns (verified, output).

    Detects project type and runs appropriate test command.
    """
    cwd = Path.cwd()

    # Detect Node.js project
    if (cwd / "package.json").exists():
        result = _subprocess.run(
            ["npm", "test"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        verified = result.returncode == 0
        output = result.stdout[:3000] if result.stdout else result.stderr[:3000]
        return verified, output

    # Detect Python project
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists() or (cwd / "requirements.txt").exists():
        python_cmd = shutil.which("python3") or shutil.which("python")
        result = _subprocess.run(
            [python_cmd, "-m", "pytest", "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        verified = result.returncode == 0
        output = result.stdout[:2000] if result.stdout else result.stderr[:2000]
        return verified, output

    # Detect Go project
    if (cwd / "go.mod").exists():
        result = _subprocess.run(
            ["go", "test", "./..."],
            capture_output=True,
            text=True,
            timeout=300,
        )
        verified = result.returncode == 0
        output = result.stdout[:2000] if result.stdout else result.stderr[:2000]
        return verified, output

    # Detect Ruby project
    if (cwd / "Gemfile").exists():
        result = _subprocess.run(
            ["bundle", "exec", "rspec"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        verified = result.returncode == 0
        output = result.stdout[:2000] if result.stdout else result.stderr[:2000]
        return verified, output

    # No known project type
    return True, "No test runner detected — skipping verification"


def handle_complete(args) -> dict:
    """Mark a task as completed.

    Args:
        args.task_id: ID of the task to mark complete.
        args.loop_id: Loop ID (optional, resolved automatically).
        args.result: Optional result summary.
        args.no_verify: If True, skip test verification.

    Returns:
        A result dict with completion confirmation.
    """
    from ..utils.identity import resolve_loop_id

    loop_id = resolve_loop_id(args.loop_id)

    from ..models.task_run import complete_task_run
    from ..models.task import update_task_status

    run_verification = not getattr(args, "no_verify", False)

    if run_verification:
        print(f"[complete] Running validation tests for task {args.task_id}...")
        verified, output = _verify_task_complete()
        if not verified:
            update_task_status(args.task_id, "available", result_summary="Tests failed - returned to pool")
            complete_task_run(args.task_id, loop_id, exit_status=1, result_summary="Tests failed")
            return {
                "command": "complete",
                "status": "validation_failed",
                "task_id": args.task_id,
                "loop_id": loop_id,
                "reason": "Tests failed - task returned to available pool",
                "test_output": output,
            }
        print(f"[complete] Validation passed")

    complete_task_run(args.task_id, loop_id, exit_status=0, result_summary=args.result)
    update_task_status(args.task_id, "completed", result_summary=args.result)

    _trigger_feature_validation_if_complete(args.task_id, loop_id)

    return {
        "command": "complete",
        "status": "success",
        "task_id": args.task_id,
        "loop_id": loop_id,
        "result": args.result,
    }


def _trigger_feature_validation_if_complete(task_id: str, loop_id: str) -> None:
    """Check if task was last child of a feature root; if so, trigger HSV.

    Handles three trigger paths:
    1. Standalone root completes (no children) → trigger HSV on self
    2. Last child completes → lock tree + trigger validation (first run)
    3. Root is in 'validation' + all blocked children are 'completed' → re-run validation
    """
    import argparse
    from ..db.connection import get_connection
    from .validate_scenarios import handle_validate_scenarios

    conn = get_connection()

    row = conn.execute(
        "SELECT parent_id, status FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        return
    parent_id, task_status = row[0], row[1]

    # Case 3: Re-validation after hidden tasks complete.
    # Task is 'completed' and parent is in 'validation' — check if all done.
    if parent_id is not None and task_status == "completed":
        parent_row = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (parent_id,)
        ).fetchone()
        if parent_row and parent_row[0] == "validation":
            remaining = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE parent_id = ?
                  AND status NOT IN ('completed', 'blocked')
            """, (parent_id,)).fetchone()[0]
            if remaining == 0:
                handle_validate_scenarios(
                    argparse.Namespace(feature_id=parent_id, check_all=False, loop_id=loop_id)
                )
        return

    # Case 1: Standalone root (no parent, no children) → validate self directly.
    if parent_id is None:
        children = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE parent_id = ?", (task_id,)
        ).fetchone()[0]
        if children == 0:
            _lock_feature_tree_inline(conn, task_id)
            handle_validate_scenarios(
                argparse.Namespace(feature_id=task_id, check_all=False, loop_id=loop_id)
            )
        return

    # Case 2: Last child completing — promote root to 'validation'.
    try:
        result = conn.execute("""
            WITH remaining AS (
                SELECT COUNT(*) as cnt FROM tasks
                WHERE parent_id = (
                    SELECT parent_id FROM tasks WHERE id = ?
                )
                  AND status != 'completed'
                  AND id != ?
            )
            UPDATE tasks
            SET status = 'validation'
            WHERE id = (
                SELECT parent_id FROM tasks WHERE id = ?
            )
              AND (SELECT cnt FROM remaining) = 0
              AND status IN ('available', 'claimed')
            RETURNING id;
        """, (task_id, task_id, task_id)).fetchone()
    except Exception:
        if not _SQLITE_SUPPORTS_RETURNING:
            warnings.warn(
                f"SQLite {sqlite3.sqlite_version} does not support RETURNING. "
                "Degraded atomic last-child detection.",
                UserWarning,
                stacklevel=2,
            )
        conn.execute("BEGIN IMMEDIATE")
        row_inner = conn.execute(
            "SELECT parent_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row_inner or row_inner[0] is None:
            conn.rollback()
            return

        parent_id_inner = row_inner[0]
        remaining = conn.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE parent_id = ?
              AND status != 'completed'
              AND id != ?
        """, (parent_id_inner, task_id)).fetchone()[0]

        if remaining == 0:
            conn.execute(
                "UPDATE tasks SET status='validation' WHERE id=? AND status IN ('available', 'claimed')",
                (parent_id_inner,)
            )
            conn.commit()
        else:
            conn.rollback()
            return
        result = (parent_id_inner,)

    if not result:
        return

    root_id = result[0]

    # Lock descendants as 'blocked'
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("""
        WITH RECURSIVE descendants AS (
            SELECT id FROM tasks WHERE parent_id = ?
            UNION ALL
            SELECT t.id FROM tasks t JOIN descendants d ON t.parent_id = d.id
        )
        UPDATE tasks SET status='blocked'
        WHERE id IN (SELECT id FROM descendants)
    """, (root_id,))
    conn.commit()

    handle_validate_scenarios(
        argparse.Namespace(feature_id=root_id, check_all=False, loop_id=loop_id)
    )


def _lock_feature_tree_inline(conn, root_id: str) -> None:
    """Lock a feature tree inline within an existing transaction."""
    conn.execute(
        "UPDATE tasks SET status='validation' WHERE id=?",
        (root_id,)
    )


def format_complete_human(result: dict) -> str:
    note = f" — {result['result']}" if result.get("result") else ""
    return f"Task {result['task_id']} marked completed{note}"

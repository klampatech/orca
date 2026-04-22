"""orch complete — Mark a task as successfully completed."""

from pathlib import Path

import shutil
import subprocess as _subprocess


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
        args.verify: If True, run tests before marking complete.
                     Defaults to True (tests must pass).
        args.no_verify: If True, skip test verification.

    Returns:
        A result dict with completion confirmation.
    """
    from ..utils.identity import resolve_loop_id

    loop_id = resolve_loop_id(args.loop_id)

    from ..models.task_run import complete_task_run
    from ..models.task import update_task_status

    # Run verification by default (tests must pass to complete)
    # Use --no-verify to skip verification
    run_verification = not getattr(args, "no_verify", False)

    if run_verification:
        print(f"[complete] Running validation tests for task {args.task_id}...")
        verified, output = _verify_task_complete()
        if not verified:
            # Return task to available pool so it can be re-claimed
            update_task_status(args.task_id, "available", result_summary="Tests failed - returned to pool")
            # Complete the task run record with failure status
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

    # --- Phase 2: hidden scenario validation trigger ---
    # Check if this was the last child of a feature root.
    # If yes, atomically lock the feature tree and trigger validation.
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

    Uses atomic SQL to detect "is this the last incomplete child?" and
    promote the root to 'validation' in one shot.
    This prevents the double-validation race (two children completing simultaneously).
    """
    from ..db.connection import get_connection

    conn = get_connection()

    # Get parent_id before we touch anything
    row = conn.execute(
        "SELECT parent_id FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        return
    parent_id = row[0]

    # No parent → standalone root, not a feature-child completion
    if parent_id is None:
        return

    # Atomic last-child detection + root promotion
    # Use nested SELECT to ensure consistent parent_id resolution
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
        # SQLite version < 3.35.0 doesn't support RETURNING
        # Fall back to two-query approach (with race condition window)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT parent_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row or row[0] is None:
            conn.rollback()
            return

        parent_id = row[0]

        # Check if any remaining incomplete siblings
        remaining = conn.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE parent_id = ?
              AND status != 'completed'
              AND id != ?
        """, (parent_id, task_id)).fetchone()[0]

        if remaining == 0:
            # Last child — promote root to validation
            conn.execute(
                "UPDATE tasks SET status='validation' WHERE id=? AND status IN ('available', 'claimed')",
                (parent_id,)
            )
            conn.commit()
        else:
            conn.rollback()
            return
        result = (parent_id,)

    if not result:
        return  # Not the last child, nothing to do

    root_id = result[0]

    # Mark all descendants as 'blocked'
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

    # Trigger HSV (non-blocking — runs synchronously after 'orca complete' returns)
    from .validate_scenarios import handle_validate_scenarios
    import argparse
    validate_result = handle_validate_scenarios(
        argparse.Namespace(feature_id=root_id, check_all=False)
    )


def format_complete_human(result: dict) -> str:
    note = f" — {result['result']}" if result.get("result") else ""
    return f"Task {result['task_id']} marked completed{note}"

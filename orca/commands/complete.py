"""orch complete — Mark a task as successfully completed."""

import shutil
import subprocess as _subprocess


def _verify_task_complete(task_id: str) -> tuple[bool, str]:
    """Run validation tests before completing. Returns (verified, output)."""
    python_cmd = shutil.which("python3") or shutil.which("python")
    result = _subprocess.run(
        [python_cmd, "-m", "pytest", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        timeout=300,  # Increased from 120s to handle longer test suites
    )
    verified = result.returncode == 0
    output = result.stdout[:2000] if result.stdout else result.stderr[:2000]
    return verified, output


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
        verified, output = _verify_task_complete(args.task_id)
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

    return {
        "command": "complete",
        "status": "success",
        "task_id": args.task_id,
        "loop_id": loop_id,
        "result": args.result,
    }


def format_complete_human(result: dict) -> str:
    note = f" — {result['result']}" if result.get("result") else ""
    return f"Task {result['task_id']} marked completed{note}"

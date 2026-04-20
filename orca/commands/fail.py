"""orch fail — Mark a task as failed and return to pool for re-claiming."""


def handle_fail(args) -> dict:
    """Mark a task as failed and return it to the available pool.

    Args:
        args.task_id: ID of the task to mark failed.
        args.loop_id: Loop ID (optional, resolved automatically).
        args.error: Error message.
        args.permanent: If True, mark as permanently failed (not returned to pool).

    Returns:
        A result dict with failure confirmation.
    """
    from ..utils.identity import resolve_loop_id

    loop_id = resolve_loop_id(args.loop_id)

    from ..models.task_run import complete_task_run
    from ..models.task import update_task_status

    # Complete the task run record with failure status
    complete_task_run(args.task_id, loop_id, exit_status=1, result_summary=args.error)

    # Return to pool by default (for transient failures like rate limits)
    # Use --permanent to mark as truly failed
    if getattr(args, "permanent", False):
        update_task_status(args.task_id, "failed", result_summary=args.error)
        return {
            "command": "fail",
            "status": "success",
            "task_id": args.task_id,
            "loop_id": loop_id,
            "error": args.error,
            "returned_to_pool": False,
        }
    else:
        update_task_status(args.task_id, "available", result_summary=f"Failed: {args.error[:200]} - returned to pool")
        return {
            "command": "fail",
            "status": "success",
            "task_id": args.task_id,
            "loop_id": loop_id,
            "error": args.error,
            "returned_to_pool": True,
        }


def format_fail_human(result: dict) -> str:
    note = f" — {result['error']}" if result.get("error") else ""
    if result.get("returned_to_pool"):
        return f"Task {result['task_id']} failed{note} — returned to pool"
    return f"Task {result['task_id']} marked failed{note}"

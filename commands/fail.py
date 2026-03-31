"""orch fail — Mark a task as failed."""


def handle_fail(args) -> dict:
    """Mark a task as failed.

    Args:
        args.task_id: ID of the task to mark failed.
        args.loop_id: Loop ID (optional, resolved automatically).
        args.error: Error message.

    Returns:
        A result dict with failure confirmation.
    """
    from utils.identity import resolve_loop_id

    loop_id = resolve_loop_id(args.loop_id)

    from models.task_run import complete_task_run
    from models.task import update_task_status

    complete_task_run(args.task_id, loop_id, exit_status=1, result_summary=args.error)
    update_task_status(args.task_id, "failed", result_summary=args.error)

    return {
        "command": "fail",
        "status": "success",
        "task_id": args.task_id,
        "loop_id": loop_id,
        "error": args.error,
    }


def format_fail_human(result: dict) -> str:
    note = f" — {result['error']}" if result.get("error") else ""
    return f"Task {result['task_id']} marked failed{note}"

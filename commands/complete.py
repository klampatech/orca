"""orch complete — Mark a task as successfully completed."""


def handle_complete(args) -> dict:
    """Mark a task as completed.

    Args:
        args.task_id: ID of the task to mark complete.
        args.loop_id: Loop ID (optional, resolved automatically).
        args.result: Optional result summary.

    Returns:
        A result dict with completion confirmation.
    """
    from utils.identity import resolve_loop_id

    loop_id = resolve_loop_id(args.loop_id)

    from models.task_run import complete_task_run
    from models.task import update_task_status

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

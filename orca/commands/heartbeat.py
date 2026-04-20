"""orch heartbeat — Update heartbeat for an active task run."""

from ..utils.identity import resolve_loop_id


def handle_heartbeat(args) -> dict:
    """Update heartbeat for a task run.

    Args:
        args.task_id: ID of the task being worked on.
        args.loop_id: Loop ID (optional, resolved automatically).

    Returns:
        A result dict with heartbeat confirmation.

    Raises:
        RuntimeError: if the task is not claimed by this loop.
    """
    loop_id = resolve_loop_id(args.loop_id)

    from ..models.task_run import heartbeat_task_run

    heartbeat_task_run(args.task_id, loop_id)

    from ..utils.time import utcnow

    return {
        "command": "heartbeat",
        "status": "success",
        "task_id": args.task_id,
        "loop_id": loop_id,
        "heartbeat_at": utcnow(),
    }


def format_heartbeat_human(result: dict) -> str:
    return f"Heartbeat updated for task {result['task_id']} (loop {result['loop_id']})"

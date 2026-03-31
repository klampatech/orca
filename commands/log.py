"""orch log — Show task run history for a task."""

from models.task import get_task
from models.task_run import get_task_runs


def handle_log(args) -> dict:
    """Show task run history for a task.

    Args:
        args.task_id: ID of the task.

    Returns:
        A result dict with task info and run history.
    """
    task = get_task(args.task_id)
    if not task:
        return {
            "command": "log",
            "status": "error",
            "message": f"Task {args.task_id} not found.",
        }

    runs = get_task_runs(args.task_id)

    return {
        "command": "log",
        "status": "success",
        "task": task,
        "runs": runs,
    }


def format_log_human(result: dict) -> str:
    if result["status"] == "error":
        return result["message"]

    task = result["task"]
    lines = [
        f"Task: {task['id']} - {task['description']}",
        "=" * 60,
        "",
    ]

    for i, run in enumerate(result["runs"], 1):
        loop = run["loop_id"][:8]
        claimed = run["claimed_at"]
        completed = run["completed_at"]
        exit_s = run["exit_status"]
        summary = run["result_summary"] or ""

        if exit_s == 0:
            status_label = "completed"
        elif exit_s == -1:
            status_label = "reclaimed (stale)"
        else:
            status_label = f"failed (exit {exit_s})"

        lines.append(f"Run {i}: loop-{loop} ({claimed})")
        lines.append(f"  Status: {status_label}")
        if completed:
            lines.append(f"  Completed: {completed}")
        if summary:
            lines.append(f"  Result: {summary}")
        lines.append("")

    return "\n".join(lines).strip()

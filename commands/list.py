"""orch list — Filter and list tasks."""

from models.task import list_tasks


def handle_list(args) -> dict:
    """List tasks, optionally filtered by status.

    Args:
        args.status: Optional status filter.

    Returns:
        A result dict with filtered task list.
    """
    tasks = list_tasks(status=args.status)

    return {
        "command": "list",
        "status": "success",
        "filter": args.status,
        "count": len(tasks),
        "tasks": tasks,
    }


def format_list_human(result: dict) -> str:
    if not result["tasks"]:
        status_note = f" ({result['filter']})" if result["filter"] else ""
        return f"No tasks found{status_note}."

    lines = []
    filter_note = f" [{result['filter']}]" if result["filter"] else ""
    lines.append(f"Tasks{filter_note} ({result['count']}):")

    for t in result["tasks"]:
        priority = t["priority"]
        tid = t["id"][:8]
        desc = t["description"]
        lines.append(f"  [P{priority}] {tid} - {desc}")

    return "\n".join(lines)

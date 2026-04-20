"""orch status — Show all tasks grouped by status."""

from ..models.task import list_tasks
from ..models.loop import list_loops
from ..models.task_run import reclaim_stale


def handle_status(args) -> dict:
    """Show all tasks grouped by status.

    Returns:
        A result dict with tasks grouped by status and loop info.
    """
    reclaim_stale()

    tasks = list_tasks()
    loops = list_loops()

    by_status: dict[str, list] = {
        "available": [],
        "claimed": [],
        "completed": [],
        "failed": [],
    }

    for task in tasks:
        by_status[task["status"]].append(task)

    return {
        "command": "status",
        "status": "success",
        "total": len(tasks),
        "by_status": by_status,
        "loops": loops,
    }


def format_status_human(result: dict) -> str:
    lines = [
        "Ralph Loop Orchestrator Status",
        "=" * 40,
        f"Total: {result['total']} tasks\n",
    ]

    for status in ("available", "claimed", "completed", "failed"):
        tasks = result["by_status"].get(status, [])
        if tasks:
            label = status.capitalize()
            lines.append(f"{label} ({len(tasks)}):")
            for t in tasks:
                priority = t["priority"]
                tid = t["id"][:8]
                desc = t["description"]
                lines.append(f"  [P{priority}] {tid} - {desc}")
            lines.append("")

    if result["loops"]:
        lines.append(f"Active loops: {len(result['loops'])}")
        for loop in result["loops"]:
            current = loop.get("current_task_id", "")
            cur = f" (working on {current[:8]})" if current else " (idle)"
            lines.append(f"  {loop['id'][:8]}{cur}")

    return "\n".join(lines).strip()

"""orch info — Show detailed information about a task."""

from models.task import get_task


def handle_info(args) -> dict:
    """Show detailed task information.

    Args:
        args.task_id: ID of the task.

    Returns:
        A result dict with full task details.
    """
    task = get_task(args.task_id)
    if not task:
        return {
            "command": "info",
            "status": "error",
            "message": f"Task {args.task_id} not found.",
        }

    return {
        "command": "info",
        "status": "success",
        **task,
    }


def format_info_human(result: dict) -> str:
    if result["status"] == "error":
        return result["message"]

    task = result
    lines = [
        f"Task: {task['id']}",
        "-" * 60,
        f"Description: {task['description']}",
        f"Status: {task['status']}",
        f"Priority: {task['priority']}",
        f"Created: {task['created_at']}",
    ]

    if task.get("claimed_at"):
        lines.append(f"Claimed: {task['claimed_at']}")
    if task.get("completed_at"):
        lines.append(f"Completed: {task['completed_at']}")
    if task.get("spec_path"):
        lines.append(f"Spec: {task['spec_path']}")
    if task.get("root_spec_path"):
        lines.append(f"Root spec: {task['root_spec_path']}")
    if task.get("parent_id"):
        lines.append(f"Parent: {task['parent_id']}")
    if task.get("result_summary"):
        lines.append(f"Result: {task['result_summary']}")

    return "\n".join(lines)

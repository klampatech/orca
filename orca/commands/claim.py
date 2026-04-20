"""orch claim — Atomically claim the highest-priority available task."""

from ..utils.identity import resolve_loop_id


def handle_claim(args) -> dict:
    """Atomically claim an available task.

    Args:
        args.loop_id: Optional loop ID override.

    Returns:
        A result dict with task details, or 'empty' status if no tasks available.
    """
    loop_id = resolve_loop_id(args.loop_id)

    from ..models.task import claim_task

    task = claim_task(loop_id)

    if task is None:
        return {
            "command": "claim",
            "status": "empty",
            "message": "No available tasks in backlog",
        }

    return {
        "command": "claim",
        "status": "success",
        "task_id": task["id"],
        "loop_id": loop_id,
        "description": task["description"],
        "spec_path": task.get("spec_path"),
        "priority": task["priority"],
        "claimed_at": task["claimed_at"],
    }


def format_claim_human(result: dict) -> str:
    if result["status"] == "empty":
        return f"No available tasks in backlog"

    spec_note = f"\n  Spec: {result['spec_path']}" if result.get("spec_path") else ""
    return (
        f"Claimed task: {result['task_id']}\n"
        f"  Description: {result['description']}{spec_note}\n"
        f"  Priority: {result['priority']}\n"
        f"  Assigned to: {result['loop_id']}"
    )

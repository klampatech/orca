"""orch add — Add a task to the backlog."""

import shutil
from pathlib import Path

from ..db.connection import get_orch_dir, get_connection
from ..models.task import create_task


def handle_add(args) -> dict:
    """Add a task to the backlog.

    Args:
        args.spec: Path to the task spec file, or '-' for inline.
        args.description: Human-readable task description.
        args.priority: Task priority (default 0).

    Returns:
        A result dict with task details.
    """
    spec_path = None
    description = args.description

    if args.spec and args.spec != "-":
        spec_path = args.spec
        if Path(spec_path).exists():
            task_dir = get_orch_dir() / "tasks"
            task_dir.mkdir(parents=True, exist_ok=True)
            dest = task_dir / f"{args.description[:32]}.spec"  # will be overwritten by task id
            shutil.copy(spec_path, dest)
            spec_path = str(dest)

    task = create_task(
        description=description,
        spec_path=spec_path,
        priority=args.priority,
    )

    return {
        "command": "add",
        "status": "success",
        **task,
    }


def format_add_human(result: dict) -> str:
    priority = result.get("priority", 0)
    spec_note = f"\n  Spec: {result['spec_path']}" if result.get("spec_path") else ""
    return (
        f"Task added: {result['id']} (priority: {priority})\n"
        f"  Description: {result['description']}{spec_note}"
    )

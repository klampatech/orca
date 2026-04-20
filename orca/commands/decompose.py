"""orch decompose — Break a markdown TDD spec into claimable tasks."""

import re
import shutil
from pathlib import Path

from ..db.connection import get_orch_dir
from ..models.task import create_tasks_batch


# --------------------------------------------------------------------
# Markdown TDD parsing
# --------------------------------------------------------------------

_SCENARIO_PATTERNS = (
    re.compile(r"^##?\s+Scenario(?:\s+Outline)?:\s*(.+)$", re.IGNORECASE),
    re.compile(r"^##?\s+Example:\s*(.+)$", re.IGNORECASE),
)

_CHECKBOX_PAT = re.compile(r"^\s*-\s+\[[ x]\]\s*(.+)$", re.IGNORECASE)
_BULLET_PAT = re.compile(r"^\s*-\s+(?!\-)(\S.*)$", re.IGNORECASE)

_FEATURE_PAT = re.compile(r"^#\s*Feature:\s*(.+)$", re.IGNORECASE)

_STEP_PATTERNS = (
    re.compile(r"^\s*Given\s+(.+)$", re.IGNORECASE),
    re.compile(r"^\s*When\s+(.+)$", re.IGNORECASE),
    re.compile(r"^\s*Then\s+(.+)$", re.IGNORECASE),
    re.compile(r"^\s*And\s+(.+)$", re.IGNORECASE),
    re.compile(r"^\s*But\s+(.+)$", re.IGNORECASE),
)


def _parse_scenarios(content: str) -> list[dict]:
    """Extract scenarios from TDD markdown content.

    Args:
        content: Raw markdown text content.

    Returns:
        List of dicts with keys: title, steps, criteria.
    """
    scenarios = []
    current = None

    for line in content.splitlines():
        # New scenario?
        for pat in _SCENARIO_PATTERNS:
            m = pat.match(line)
            if m:
                if current:
                    scenarios.append(current)
                title = m.group(1).strip()
                current = {"title": title, "steps": [], "criteria": []}
                break
        else:
            # Steps or criteria for current scenario
            if current:
                step_matched = False
                for step_pat in _STEP_PATTERNS:
                    m = step_pat.match(line)
                    if m:
                        current["steps"].append(m.group(1).strip())
                        step_matched = True
                        break
                if not step_matched:
                    # Checkbox criteria
                    m = _CHECKBOX_PAT.match(line)
                    if m:
                        current["criteria"].append(m.group(1).strip())
                    else:
                        # General bullet criteria
                        m = _BULLET_PAT.match(line)
                        if m:
                            stripped = m.group(1).strip()
                            if stripped:
                                current["criteria"].append(stripped)

    if current:
        scenarios.append(current)

    return scenarios


def _extract_feature_title(content: str) -> str | None:
    """Extract the Feature title from markdown content."""
    for line in content.splitlines():
        m = _FEATURE_PAT.match(line)
        if m:
            return m.group(1).strip()
    return None


def _build_description(scenario: dict) -> str:
    """Build a one-line description from scenario steps + criteria."""
    parts = []
    for step in scenario["steps"][:3]:
        parts.append(step)
    for crit in scenario["criteria"][:2]:
        parts.append(crit)
    return " | ".join(parts) if parts else scenario["title"]


# --------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------


def handle_decompose(args) -> dict:
    """Decompose a markdown TDD spec into multiple tasks.

    Args:
        args.spec: Path to the markdown spec file.
        args.description: Optional override description for the spec-root task.
        args.priority: Base priority for generated tasks.
        args.dry_run: If True, don't persist to database.

    Returns:
        A result dict with created task details.
    """
    spec_path = Path(args.spec)
    if not spec_path.exists():
        raise RuntimeError(f"Spec file not found: {spec_path}")

    content = spec_path.read_text()

    # Parse
    scenarios = _parse_scenarios(content)
    if not scenarios:
        raise RuntimeError(
            f"No scenarios found in {spec_path}. Is this a valid TDD spec?"
        )

    # Copy spec to .orch/tasks/ (same as add.py)
    task_dir = get_orch_dir() / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    dest = task_dir / f"{spec_path.stem[:32]}.md"
    shutil.copy(spec_path, dest)
    stored_spec_path = str(dest)

    # Feature title as root description (or user-provided)
    feature_title = args.description
    if not feature_title:
        feature_title = _extract_feature_title(content)
        if not feature_title:
            feature_title = spec_path.stem

    # Prepare task records
    # Spec-root task gets elevated priority
    root_priority = max(args.priority, 10)
    tasks_to_create = [{
        "description": feature_title,
        "spec_path": stored_spec_path,
        "priority": root_priority,
        "parent_id": None,
        "root_spec_path": stored_spec_path,
    }]

    # Sub-tasks for each scenario
    priority = args.priority
    for scenario in scenarios:
        desc = _build_description(scenario)
        tasks_to_create.append({
            "description": desc,
            "spec_path": stored_spec_path,
            "priority": max(priority, 0),
            "parent_id": None,  # will be set after root is created
            "root_spec_path": stored_spec_path,
        })
        priority = max(priority - 1, 0)

    if args.dry_run:
        # Return tasks without persisting (IDs will be None)
        for task in tasks_to_create:
            task["id"] = "<would-create>"
        result_tasks = tasks_to_create
    else:
        # Create all tasks in batch
        result_tasks = create_tasks_batch(tasks_to_create)

        # Update sub-tasks with parent_id (root is first) - persist to DB
        from ..db.connection import get_connection
        root_id = result_tasks[0]["id"]
        conn = get_connection()
        for task in result_tasks[1:]:
            task["parent_id"] = root_id
            conn.execute(
                "UPDATE tasks SET parent_id = ? WHERE id = ?",
                (root_id, task["id"]),
            )
        conn.commit()

    return {
        "command": "decompose",
        "status": "success",
        "spec_root_id": result_tasks[0]["id"],
        "spec_path": stored_spec_path,
        "total_tasks": len(result_tasks),
        "tasks": result_tasks,
    }


def format_decompose_human(result: dict) -> str:
    lines = [
        f"Decomposed spec into {result['total_tasks']} tasks:",
        f"  Spec root: {result['spec_root_id']} ({result['spec_path']})",
        "",
    ]
    for i, task in enumerate(result["tasks"]):
        parent = ""
        if task.get("parent_id"):
            parent = f"  [parent: {str(task['parent_id'])[:8]}]"
        lines.append(
            f"  [{i}] {str(task['id'])[:8]} P{task['priority']} - "
            f"{task['description'][:60]}{parent}"
        )
    return "\n".join(lines)

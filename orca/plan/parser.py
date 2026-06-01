"""Plan file parser — extract structured data from markdown plans.

Provides utilities to parse implementation plans into Python objects
for further processing (decomposition, validation, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .schema import (
    Plan,
    Task,
    PlanMetadata,
    compute_hash,
    validate_format,
    deduplicate_features,
    deduplicate_tasks,
)


def parse_plan(path: Path | str) -> Plan:
    """Parse a plan file into a Plan object.

    Args:
        path: Path to the plan file (markdown format).

    Returns:
        Parsed Plan object with metadata, features, and tasks.

    Raises:
        FileNotFoundError: If plan file doesn't exist.
        ValueError: If plan format is invalid.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Plan file not found: {path}")

    content = path.read_text()

    # Auto-deduplicate FEAT and TASK sections before processing
    content = deduplicate_features(content)
    content = deduplicate_tasks(content)
    plan = Plan.from_content(content)

    # Validate format
    valid, errors = validate_format(content)
    if not valid:
        raise ValueError("Invalid plan format:\n  - " + "\n  - ".join(errors))

    return plan


def parse_plan_content(content: str) -> Plan:
    """Parse plan content directly from a string.

    Args:
        content: Raw markdown content of a plan.

    Returns:
        Parsed Plan object.

    Raises:
        ValueError: If plan format is invalid.
    """
    # Auto-deduplicate FEAT and TASK sections before validation
    content = deduplicate_features(content)
    content = deduplicate_tasks(content)

    valid, errors = validate_format(content)
    if not valid:
        raise ValueError("Invalid plan format:\n  - " + "\n  - ".join(errors))

    return Plan.from_content(content)


def extract_tasks(plan: Plan) -> list[Task]:
    """Extract all tasks from a plan.

    Args:
        plan: Parsed Plan object.

    Returns:
        List of all tasks including uncategorized.
    """
    return plan.get_all_tasks()


def extract_features(plan: Plan) -> dict[str, list[Task]]:
    """Group tasks by feature.

    Args:
        plan: Parsed Plan object.

    Returns:
        Dictionary mapping feature IDs to lists of tasks.
        Includes "uncategorized" key for tasks without a feature.
    """
    result: dict[str, list[Task]] = {}

    for feature in plan.features:
        result[feature.feature_id] = list(feature.tasks)

    if plan.uncategorized_tasks:
        result["uncategorized"] = list(plan.uncategorized_tasks)

    return result


def get_feature_tasks(plan: Plan, feature_id: str) -> list[Task]:
    """Get all tasks for a specific feature.

    Args:
        plan: Parsed Plan object.
        feature_id: Feature ID (e.g., "FEAT-001").

    Returns:
        List of tasks for the feature, empty if not found.
    """
    for feature in plan.features:
        if feature.feature_id == feature_id:
            return list(feature.tasks)
    return []


def compute_stability_hash(plan: Plan) -> str:
    """Compute hash for stability detection.

    This hash only considers task IDs to detect when the task list
    changes, regardless of description edits.

    Args:
        plan: Parsed Plan object.

    Returns:
        10-character hex hash of task IDs.
    """
    return compute_hash(plan.get_all_tasks())


def is_plan_stable(
    plan: Plan,
    previous_hash: str,
    iterations_without_change: int,
    stability_threshold: int = 2,
) -> bool:
    """Check if a plan is stable (ready for decomposition).

    A plan is stable when its hash matches the previous hash for
    a threshold number of consecutive iterations.

    Args:
        plan: Current plan.
        previous_hash: Hash from previous iteration.
        iterations_without_change: Number of iterations with same hash.
        stability_threshold: Number of matching iterations needed (default: 2).

    Returns:
        True if plan is stable and ready for decomposition.
    """
    current_hash = compute_stability_hash(plan)
    return (
        current_hash == previous_hash
        and iterations_without_change >= stability_threshold
    )


def get_task_count(plan: Plan) -> int:
    """Get total count of tasks in a plan."""
    return len(plan.get_all_tasks())


def get_feature_count(plan: Plan) -> int:
    """Get total count of features in a plan."""
    return len(plan.features)


def find_task(plan: Plan, task_id: str) -> Optional[Task]:
    """Find a task by its ID.

    Args:
        plan: Parsed Plan object.
        task_id: Task ID (e.g., "TASK-001").

    Returns:
        Task if found, None otherwise.
    """
    return plan.get_task_by_id(task_id)


def update_task_status(plan: Plan, task_id: str, checked: bool) -> bool:
    """Update the checked status of a task.

    Args:
        plan: Parsed Plan object (mutated in place).
        task_id: Task ID to update.
        checked: New checked status.

    Returns:
        True if task was found and updated, False otherwise.
    """
    for task in plan.get_all_tasks():
        if task.task_id == task_id:
            task.checked = checked
            return True
    return False


def validate_plan_format(path: Path | str) -> tuple[bool, list[str]]:
    """Validate that a plan file follows the expected format.

    This is a convenience wrapper around validate_format() that
    reads the file first.

    Args:
        path: Path to the plan file.

    Returns:
        Tuple of (is_valid, list_of_errors).
    """
    try:
        content = Path(path).read_text()
        return validate_format(content)
    except FileNotFoundError:
        return False, [f"File not found: {path}"]


def get_plan_summary(plan: Plan) -> dict:
    """Get a summary of the plan for display/logging.

    Args:
        plan: Parsed Plan object.

    Returns:
        Dictionary with summary statistics.
    """
    all_tasks = plan.get_all_tasks()
    completed = sum(1 for t in all_tasks if t.checked)

    return {
        "project": plan.metadata.project,
        "spec_path": plan.metadata.spec_path,
        "hash": plan.metadata.hash,
        "feature_count": len(plan.features),
        "task_count": len(all_tasks),
        "completed_tasks": completed,
        "pending_tasks": len(all_tasks) - completed,
        "completion_percent": (
            round(completed / len(all_tasks) * 100, 1) if all_tasks else 0
        ),
    }


def generate_empty_plan(project: str, spec_path: str) -> Plan:
    """Generate an empty plan with just metadata.

    Useful as a starting point for iterative plan generation.

    Args:
        project: Project name.
        spec_path: Path to source spec.

    Returns:
        Empty Plan object with no features or tasks.
    """
    metadata = PlanMetadata(
        project=project,
        spec_path=spec_path,
        hash="0000000000",  # Placeholder until tasks added
    )
    return Plan(metadata=metadata, features=[])


def generate_tasks_from_plan(plan: Plan) -> list[dict]:
    """Generate task records from a parsed plan.

    Args:
        plan: Parsed Plan object.

    Returns:
        List of task dicts ready for create_tasks_batch().
    """
    tasks: list[dict] = []

    # Process features and their tasks
    for feature in plan.features:
        feat_id = feature.feature_id
        feat_desc = feature.description

        # Feature root task
        feature_snippet = {
            "id": feat_id,
            "description": feat_desc,
            "tasks": [
                {"id": t.task_id, "description": t.description} for t in feature.tasks
            ],
        }

        tasks.append(
            {
                "description": f"{feat_id} | {feat_desc[:60]}",
                "spec_path": plan.metadata.spec_path,
                "priority": 10,
                "parent_id": None,
                "root_spec_path": plan.metadata.spec_path,
                "ir_snippet": json.dumps(feature_snippet),
            }
        )

        # Individual task records
        for task in feature.tasks:
            task_snippet = {
                "id": task.task_id,
                "description": task.description,
                "feature_id": feat_id,
            }
            tasks.append(
                {
                    "description": f"{task.task_id} | {task.description[:60]}",
                    "spec_path": plan.metadata.spec_path,
                    "priority": 8,
                    "parent_id": None,
                    "root_spec_path": plan.metadata.spec_path,
                    "ir_snippet": json.dumps(task_snippet),
                }
            )

    # Process uncategorized tasks
    for task in plan.uncategorized_tasks:
        task_snippet = {
            "id": task.task_id,
            "description": task.description,
            "feature_id": "",
        }
        tasks.append(
            {
                "description": f"{task.task_id} | {task.description[:60]}",
                "spec_path": plan.metadata.spec_path,
                "priority": 7,
                "parent_id": None,
                "root_spec_path": plan.metadata.spec_path,
                "ir_snippet": json.dumps(task_snippet),
            }
        )

    return tasks


def _get_feature_block_boundaries(plan: Plan) -> list[tuple[int, int]]:
    """Get start/end indices for each feature's task block.

    For linking parent-child relationships in the database.
    """
    blocks: list[tuple[int, int]] = []
    for feature in plan.features:
        # Find where this feature's tasks are in the flat list
        block_start = 0
        for prev_feat in plan.features:
            if prev_feat == feature:
                break
            block_start += 1 + len(prev_feat.tasks)  # 1 for feature root + task count

        block_end = block_start + 1 + len(feature.tasks)
        blocks.append((block_start, block_end))

    return blocks


def is_plan_format(path: Path | str) -> bool:
    """Check if a file contains plan format (TASK-NNN patterns).

    Args:
        path: Path to the file to check.

    Returns:
        True if the file contains plan format patterns.
    """
    try:
        content = Path(path).read_text()
        # Check for plan header
        has_header = (
            "# Implementation Plan" in content or "Implementation Plan" in content
        )

        # Check for task patterns (both checked and unchecked)
        import re

        # Match both `- [ ] TASK-001:` and `- [x] TASK-001:`
        has_tasks = bool(re.search(r"- \[.?\] (TASK-\d+):", content))

        # Also check for ## Features or ## Phase sections (both are valid)
        has_features = bool(re.search(r"^##\s+(Features|Phase\s+)", content, re.MULTILINE))

        return has_header and has_tasks and has_features
    except Exception:
        return False

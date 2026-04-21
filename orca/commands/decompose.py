"""orch decompose — Break a spec into claimable tasks.

Supports dual input modes:
- Gherkin markdown (.md): Existing TDD parsing logic
- JSON IR (.json): Phase 1 IR validator spec.ir.json decomposition

The IR mode creates a hierarchical task tree:
  Feature (root) → Acceptance Criteria (children) → Edge Cases (grandchildren)
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import NamedTuple

from ..db.connection import get_orch_dir
from ..models.task import create_tasks_batch
from ..utils.validator import SpecIRValidator


# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

# Priority tiers for IR decomposition
PRIORITY_TIER = {
    "mustHave": 10,
    "shouldHave": 7,
    "niceToHave": 4,
}

# Within a feature, scenario priorities
PRIORITY_AC_HAPPY_PATH = 8
PRIORITY_AC_ERROR_HANDLING = 8
PRIORITY_EDGE_CASE = 6


# --------------------------------------------------------------------
# Markdown TDD parsing (existing Gherkin path)
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
# JSON IR parsing (Phase 1: IR validator)
# --------------------------------------------------------------------

def _build_feature_snippet(feature: dict) -> str:
    """Build ir_snippet for a feature (root) task.
    
    Includes full feature object for holistic context.
    """
    return json.dumps({
        "id": feature.get("id", ""),
        "description": feature.get("description", ""),
        "acceptanceCriteria": feature.get("acceptanceCriteria", {}),
        "edgeCases": feature.get("edgeCases", []),
    })


def _build_ac_snippet(ac: dict, feature_context: dict) -> str:
    """Build ir_snippet for an AC (child) task.
    
    Includes AC criterion + feature context.
    """
    return json.dumps({
        "id": ac.get("id", ""),
        "criterion": ac.get("criterion", ""),
        "feature": {
            "id": feature_context.get("id", ""),
            "description": feature_context.get("description", ""),
        },
    })


def _build_edge_snippet(edge_idx: int, edge_case: str, feature_context: dict) -> str:
    """Build ir_snippet for an edge case (grandchild) task.
    
    Includes edge case string + feature context.
    Edge case index is 1-based.
    """
    return json.dumps({
        "id": f"{feature_context.get('id', 'FEAT')}/edge-{edge_idx:03d}",
        "edgeCase": edge_case,
        "feature": {
            "id": feature_context.get("id", ""),
            "description": feature_context.get("description", ""),
        },
    })


def _parse_ir_decompose(spec_path: Path) -> tuple[list[dict], list[tuple[int, int]]]:
    """Decompose JSON IR into task records.
    
    Creates hierarchical task tree:
    - Root: Feature (mustHave/shouldHave/niceToHave)
    - Children: Acceptance criteria (happyPath, errorHandling)
    - Grandchildren: Edge cases (per feature, not per AC)
    
    The returned list is ordered by feature, with each feature's block being:
    [root, ac1, ac2, ..., edge1, edge2, ...]
    
    Args:
        spec_path: Path to spec.ir.json file.
        
    Returns:
        Tuple of (tasks, feature_blocks) where:
        - tasks: List of task dicts ready for create_tasks_batch()
        - feature_blocks: List of (start_idx, end_idx) tuples for each feature block
    """
    with open(spec_path) as f:
        ir = json.load(f)
    
    tasks: list[dict] = []
    feature_blocks: list[tuple[int, int]] = []
    feature_ids_seen: set[str] = set()
    
    # Process features in tier order
    for tier, priority in [("mustHave", 10), ("shouldHave", 7), ("niceToHave", 4)]:
        features = ir.get("coreFeatures", {}).get(tier, [])
        
        for feature in features:
            feat_id = feature.get("id", "")
            feat_desc = feature.get("description", "")
            
            # Skip duplicates
            if feat_id in feature_ids_seen:
                continue
            feature_ids_seen.add(feat_id)
            
            # Feature context for children
            feature_context = {
                "id": feat_id,
                "description": feat_desc,
            }
            
            # Record block start
            block_start = len(tasks)
            
            # Root task: Feature
            feature_snippet = _build_feature_snippet(feature)
            tasks.append({
                "description": f"{feat_id} | {feat_desc[:60]}",
                "spec_path": str(spec_path),
                "priority": priority,
                "parent_id": None,
                "root_spec_path": str(spec_path),
                "ir_snippet": feature_snippet,
            })
            
            # Children: Acceptance criteria (happyPath + errorHandling)
            acs = feature.get("acceptanceCriteria", {})
            
            for ac in acs.get("happyPath", []):
                ac_id = ac.get("id", f"{feat_id}/AC-???")
                criterion = ac.get("criterion", "")
                tasks.append({
                    "description": f"{ac_id} | {criterion[:60]}",
                    "spec_path": str(spec_path),
                    "priority": PRIORITY_AC_HAPPY_PATH,
                    "parent_id": None,
                    "root_spec_path": str(spec_path),
                    "ir_snippet": _build_ac_snippet(ac, feature_context),
                })
            
            for ac in acs.get("errorHandling", []):
                ac_id = ac.get("id", f"{feat_id}/AC-???")
                criterion = ac.get("criterion", "")
                tasks.append({
                    "description": f"{ac_id} | {criterion[:60]}",
                    "spec_path": str(spec_path),
                    "priority": PRIORITY_AC_ERROR_HANDLING,
                    "parent_id": None,
                    "root_spec_path": str(spec_path),
                    "ir_snippet": _build_ac_snippet(ac, feature_context),
                })
            
            # Grandchildren: Edge cases (per feature, not per AC)
            for edge_idx, edge_case in enumerate(feature.get("edgeCases", []), start=1):
                edge_str = edge_case if isinstance(edge_case, str) else str(edge_case)
                tasks.append({
                    "description": f"{feat_id}/edge-{edge_idx:03d} | {edge_str[:60]}",
                    "spec_path": str(spec_path),
                    "priority": PRIORITY_EDGE_CASE,
                    "parent_id": None,
                    "root_spec_path": str(spec_path),
                    "ir_snippet": _build_edge_snippet(edge_idx, edge_str, feature_context),
                })
            
            # Record block end (exclusive, like range())
            feature_blocks.append((block_start, len(tasks)))
    
    return tasks, feature_blocks


# --------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------


def handle_decompose(args) -> dict:
    """Decompose a spec (markdown TDD or JSON IR) into tasks.

    Args:
        args.spec: Path to spec file (.md for Gherkin, .json for IR).
        args.description: Optional override description for the spec-root task.
        args.priority: Base priority for generated tasks.
        args.dry_run: If True, don't persist to database.

    Returns:
        A result dict with created task details.
    """
    spec_path = Path(args.spec)
    if not spec_path.exists():
        raise RuntimeError(f"Spec file not found: {spec_path}")

    # Copy spec to .orch/tasks/
    task_dir = get_orch_dir() / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine dest filename based on input type
    if spec_path.suffix.lower() == ".json":
        # Preserve original filename for JSON IR
        dest = task_dir / spec_path.name
    else:
        dest = task_dir / f"{spec_path.stem[:32]}.md"
    
    shutil.copy(spec_path, dest)
    stored_spec_path = str(dest)

    # Detect mode by file extension
    if spec_path.suffix.lower() == ".json":
        # IR mode: validate JSON IR first
        validator = SpecIRValidator()
        valid, errors = validator.validate_file(spec_path)
        
        if not valid:
            error_lines = [f"  ✗ {e.field}: {e.message}" for e in errors]
            error_msg = f"Invalid spec.ir.json:\n" + "\n".join(error_lines[:10])
            raise RuntimeError(error_msg)
        
        # IR mode: parse JSON IR
        tasks_to_create, feature_blocks = _parse_ir_decompose(spec_path)
        
        if not tasks_to_create:
            raise RuntimeError(
                f"No features found in {spec_path}. Is this a valid spec.ir.json?"
            )
        
        # For IR mode, the root task uses project name from IR
        try:
            with open(spec_path) as f:
                ir = json.load(f)
            project_name = ir.get("project", {}).get("name", spec_path.stem)
        except Exception:
            project_name = spec_path.stem
        
        feature_title = args.description or project_name
        
    else:
        # Gherkin markdown mode (existing behavior)
        content = spec_path.read_text()
        scenarios = _parse_scenarios(content)
        
        if not scenarios:
            raise RuntimeError(
                f"No scenarios found in {spec_path}. Is this a valid TDD spec?"
            )
        
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
            "ir_snippet": None,
        }]

        # Sub-tasks for each scenario
        priority = args.priority
        for scenario in scenarios:
            desc = _build_description(scenario)
            tasks_to_create.append({
                "description": desc,
                "spec_path": stored_spec_path,
                "priority": max(priority, 0),
                "parent_id": None,
                "root_spec_path": stored_spec_path,
                "ir_snippet": None,
            })
            priority = max(priority - 1, 0)
        
        feature_blocks = None  # Not used for Gherkin mode

    if args.dry_run:
        # Return tasks without persisting (IDs will be None)
        for task in tasks_to_create:
            task["id"] = "<would-create>"
        result_tasks = tasks_to_create
    else:
        # Create all tasks in batch
        result_tasks = create_tasks_batch(tasks_to_create)

        # Link parent-child relationships
        from ..db.connection import get_connection
        
        conn = get_connection()
        
        if spec_path.suffix.lower() == ".json":
            # IR mode: link children to their feature root using block boundaries
            # feature_blocks contains (start, end) for each feature's block
            for start_idx, end_idx in feature_blocks:
                root_id = result_tasks[start_idx]["id"]
                # Link all tasks in the block (except the root) to the root
                for i in range(start_idx + 1, end_idx):
                    result_tasks[i]["parent_id"] = root_id
                    conn.execute(
                        "UPDATE tasks SET parent_id = ? WHERE id = ?",
                        (root_id, result_tasks[i]["id"]),
                    )
        else:
            # Gherkin mode: link all sub-tasks to root
            root_id = result_tasks[0]["id"]
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
        "mode": "ir" if spec_path.suffix.lower() == ".json" else "gherkin",
        "spec_root_id": result_tasks[0]["id"],
        "spec_path": stored_spec_path,
        "total_tasks": len(result_tasks),
        "tasks": result_tasks,
    }


def format_decompose_human(result: dict) -> str:
    mode = result.get("mode", "gherkin")
    mode_str = "IR" if mode == "ir" else "Gherkin"
    
    lines = [
        f"Decomposed {mode_str} spec into {result['total_tasks']} tasks:",
        f"  Spec root: {result['spec_root_id']} ({result['spec_path']})",
        "",
    ]
    for i, task in enumerate(result["tasks"]):
        parent = ""
        if task.get("parent_id"):
            parent = f"  [parent: {str(task['parent_id'])[:8]}]"
        has_snippet = " [IR]" if task.get("ir_snippet") else ""
        lines.append(
            f"  [{i}] {str(task['id'])[:8]} P{task['priority']} - "
            f"{task['description'][:60]}{parent}{has_snippet}"
        )
    return "\n".join(lines)
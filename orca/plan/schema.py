"""Schema definitions for implementation plans.

Plan format is LLM-friendly markdown with structured task syntax:
- `- [ ] TASK-NNN: <description>` for tasks
- `### FEAT-NNN: <description>` for feature sections

This format is human-readable, editable, and easily parsed while being
consistent enough for reliable machine interpretation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional


# --------------------------------------------------------------------
# Regex Patterns
# --------------------------------------------------------------------

# Matches: `- [ ] TASK-001: Some task description` OR `- [x] TASK-001: Completed task`
TASK_PATTERN = re.compile(r"^- \[.\] (TASK-\d+):\s*(.+)$")

# Matches: `### FEAT-001: Some feature description`
FEAT_PATTERN = re.compile(r"^### (FEAT-\d+):\s*(.+)$")

# Matches: `**Key:**` metadata lines
METADATA_PATTERN = re.compile(r"^\*\*([^*]+):\*\*\s*(.+)$")

# Matches: `**Plan Hash:** <hash>` (allows any non-empty string after the colon)
PLAN_HASH_PATTERN = re.compile(r"^\*\*Plan Hash:\*\*\s*(.+)$", re.IGNORECASE)

# Matches the plan header
PLAN_HEADER_PATTERN = re.compile(r"^#\s*Implementation\s+Plan\s*$", re.IGNORECASE)

# Matches the features section header (## Features or ## Phase N: Name)
FEATURES_HEADER_PATTERN = re.compile(r"^##\s+(Features|Phase\s+\d+.*$)", re.IGNORECASE)

# Matches separator lines
SEPARATOR_PATTERN = re.compile(r"^---+$")


# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

PLAN_TEMPLATE = """# Implementation Plan

**Project:** {project_name}
**Spec:** {spec_path}

## Features

{features}

---

**Plan Hash:** {hash}
"""

FEAT_TEMPLATE = """### {feat_id}: {feat_desc}

{tasks}
"""

TASK_TEMPLATE = "- [ ] {task_id}: {task_desc}"


# --------------------------------------------------------------------
# Data Classes
# --------------------------------------------------------------------


@dataclass
class PlanMetadata:
    """Metadata extracted from plan header."""

    project: str
    spec_path: str
    hash: str
    created_at: Optional[str] = None

    @classmethod
    def from_content(cls, content: str) -> "PlanMetadata":
        """Parse metadata from plan content."""
        project = ""
        spec_path = ""
        hash_val = ""
        created = None

        for line in content.splitlines():
            # Check for Plan Hash
            m = PLAN_HASH_PATTERN.match(line)
            if m:
                hash_val = m.group(1)
                continue

            # Check for other metadata
            m = METADATA_PATTERN.match(line)
            if m:
                key = m.group(1).strip().lower()
                value = m.group(2).strip()
                if key == "project":
                    project = value
                elif key == "spec":
                    spec_path = value

        return cls(
            project=project,
            spec_path=spec_path,
            hash=hash_val,
            created_at=created,
        )


@dataclass
class Task:
    """A single task in the plan."""

    task_id: str  # e.g., "TASK-001"
    description: str
    feature_id: Optional[str] = None  # e.g., "FEAT-001"
    checked: bool = False  # True if `[x]` instead of `[ ]`

    @classmethod
    def from_line(cls, line: str, feature_id: Optional[str] = None) -> "Task":
        """Parse a task from a markdown line."""
        # Handle both checked and unchecked
        checked = "[x]" in line.lower()
        m = TASK_PATTERN.match(line)
        if m:
            return cls(
                task_id=m.group(1),
                description=m.group(2).strip(),
                feature_id=feature_id,
                checked=checked,
            )
        return cls(task_id="", description=line, feature_id=feature_id)

    def to_markdown(self) -> str:
        """Convert to markdown line."""
        checkbox = "[x]" if self.checked else "[ ]"
        return f"- [{checkbox[1:-1]}] {self.task_id}: {self.description}"

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "feature_id": self.feature_id,
            "checked": self.checked,
        }


@dataclass
class Feature:
    """A feature section containing related tasks."""

    feature_id: str  # e.g., "FEAT-001"
    description: str
    tasks: list[Task] = field(default_factory=list)

    @classmethod
    def from_lines(
        cls, feature_id: str, description: str, lines: list[str]
    ) -> "Feature":
        """Parse a feature from markdown lines."""
        tasks = []
        for line in lines:
            m = TASK_PATTERN.match(line)
            if m:
                tasks.append(
                    Task(
                        task_id=m.group(1),
                        description=m.group(2).strip(),
                        feature_id=feature_id,
                    )
                )
        return cls(feature_id=feature_id, description=description, tasks=tasks)

    def to_markdown(self) -> str:
        """Convert to markdown."""
        task_lines = [t.to_markdown() for t in self.tasks]
        return f"### {self.feature_id}: {self.description}\n\n" + "\n".join(task_lines)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "feature_id": self.feature_id,
            "description": self.description,
            "tasks": [t.to_dict() for t in self.tasks],
        }


@dataclass
class Plan:
    """A complete implementation plan."""

    metadata: PlanMetadata
    features: list[Feature] = field(default_factory=list)
    raw_content: str = ""
    uncategorized_tasks: list[Task] = field(default_factory=list)

    @classmethod
    def from_content(cls, content: str) -> "Plan":
        """Parse a plan from markdown content."""
        metadata = PlanMetadata.from_content(content)

        # Parse features
        features = []
        current_feature: Optional[Feature] = None
        current_lines: list[str] = []


        in_features = False
        # Track which entry mode: 'features', 'phase', or None
        # In 'phase' mode, ### FEAT- sections are subsections that should NOT be
        # separated by --- (--- is used between Phase groups, not as terminator)
        entry_mode: Optional[str] = None

        for line in content.splitlines():
            # Detect features section (either "## Features" or "## Phase N: name")
            fhdr_match = FEATURES_HEADER_PATTERN.match(line)
            if fhdr_match:
                in_features = True
                # Record entry mode: 'features' for ## Features, 'phase' for ## Phase X
                matched_text = fhdr_match.group(1)
                if matched_text.lower() == "features":
                    entry_mode = "features"
                else:
                    entry_mode = "phase"
                continue

            # Stop at separator only in features mode or at final footer
            # In phase mode, separators are between phase groups, not terminators
            if SEPARATOR_PATTERN.match(line):
                if entry_mode == "features":
                    break
                else:
                    # In phase mode, continue past --- separators
                    continue

            if not in_features:
                continue

            # Check for feature header
            m = FEAT_PATTERN.match(line)
            if m:
                # Save previous feature
                if current_feature is not None and current_lines:
                    feat = Feature.from_lines(
                        current_feature.feature_id,
                        current_feature.description,
                        current_lines,
                    )
                    features.append(feat)
                    current_lines = []

                current_feature = Feature(
                    feature_id=m.group(1), description=m.group(2).strip()
                )
                continue

            # Collect task lines
            if current_feature is not None and TASK_PATTERN.match(line):
                current_lines.append(line)


        # Save last feature
        if current_feature is not None:
            feat = Feature.from_lines(
                current_feature.feature_id,
                current_feature.description,
                current_lines,
            )
            features.append(feat)

        # Parse uncategorized tasks (before ## Features)
        uncategorized = []
        for line in content.splitlines():
            if FEATURES_HEADER_PATTERN.match(line):
                break
            if SEPARATOR_PATTERN.match(line):
                break
            m = TASK_PATTERN.match(line)
            if m:
                uncategorized.append(
                    Task(task_id=m.group(1), description=m.group(2).strip())
                )

        return cls(
            metadata=metadata,
            features=features,
            raw_content=content,
            uncategorized_tasks=uncategorized,
        )

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks including uncategorized."""
        tasks = list(self.uncategorized_tasks)
        for feature in self.features:
            tasks.extend(feature.tasks)
        return tasks

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """Find a task by its ID."""
        for task in self.get_all_tasks():
            if task.task_id == task_id:
                return task
        return None

    def to_markdown(self) -> str:
        """Convert plan back to markdown."""
        parts = [
            "# Implementation Plan",
            "",
            f"**Project:** {self.metadata.project}",
            f"**Spec:** {self.metadata.spec_path}",
            "",
            "## Features",
            "",
        ]

        for feature in self.features:
            parts.append(feature.to_markdown())
            parts.append("")

        parts.extend(["---", "", f"**Plan Hash:** {self.metadata.hash}"])

        return "\n".join(parts)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "metadata": {
                "project": self.metadata.project,
                "spec_path": self.metadata.spec_path,
                "hash": self.metadata.hash,
                "created_at": self.metadata.created_at,
            },
            "features": [f.to_dict() for f in self.features],
            "uncategorized_tasks": [t.to_dict() for t in self.uncategorized_tasks],
        }


# --------------------------------------------------------------------
# Utility Functions
# --------------------------------------------------------------------


def compute_hash(tasks: list[Task]) -> str:
    """Compute a stable hash of the task list for change detection.

    Uses only task IDs for hashing to detect when the task list changes,
    not when descriptions change.
    """
    # Sort by task ID for consistent ordering
    task_ids = sorted([t.task_id for t in tasks if t.task_id])
    hash_input = "|".join(task_ids)

    if not hash_input:
        hash_input = "empty"

    return hashlib.sha256(hash_input.encode()).hexdigest()[:10]


def compute_hash_from_content(content: str) -> str:
    """Compute hash directly from content."""
    plan = Plan.from_content(content)
    return compute_hash(plan.get_all_tasks())


def deduplicate_features(content: str) -> str:
    """Remove duplicate FEAT sections, keeping only the first occurrence.

    When Claude Code refines a plan iteratively, it sometimes appends duplicate
    FEAT sections instead of updating existing ones. This function deduplicates
    them by keeping only the first occurrence of each FEAT-ID.

    Args:
        content: Raw markdown plan content.

    Returns:
        Content with duplicate FEAT sections removed.
    """
    lines = content.splitlines()
    result_lines: list[str] = []
    seen_feature_ids: set[str] = set()
    skipping = False

    i = 0
    while i < len(lines):
        line = lines[i]
        m = FEAT_PATTERN.match(line)

        if m:
            feat_id = m.group(1)
            if feat_id in seen_feature_ids:
                # Start skipping this duplicate feature block
                skipping = True
                i += 1
                continue
            else:
                seen_feature_ids.add(feat_id)
                skipping = False
                result_lines.append(line)
                i += 1
                continue

        if skipping:
            # Skip lines until we hit a separator (end of features section)
            # or another feature header (which the loop above will handle)
            if SEPARATOR_PATTERN.match(line):
                skipping = False
                result_lines.append(line)
            i += 1
            continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def deduplicate_tasks(content: str) -> str:
    """Remove duplicate task lines, keeping only the first occurrence.

    When Claude Code refines a plan iteratively, it sometimes appends duplicate
    task lines instead of updating existing ones. This function deduplicates
    them by keeping only the first occurrence of each TASK-ID.

    Args:
        content: Raw markdown plan content.

    Returns:
        Content with duplicate task lines removed.
    """
    lines = content.splitlines()
    result_lines: list[str] = []
    seen_task_ids: set[str] = set()
    skipping = False

    i = 0
    while i < len(lines):
        line = lines[i]
        m = TASK_PATTERN.match(line)

        if m:
            task_id = m.group(1)
            if task_id in seen_task_ids:
                # Skip this duplicate task line
                skipping = True
                i += 1
                continue
            else:
                seen_task_ids.add(task_id)
                skipping = False
                result_lines.append(line)
                i += 1
                continue

        # Only skip if we're in a duplicate task block
        # Stop skipping at feature headers or separators
        if skipping:
            if FEAT_PATTERN.match(line) or SEPARATOR_PATTERN.match(line) or FEATURES_HEADER_PATTERN.match(line):
                skipping = False
                result_lines.append(line)
            i += 1
            continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def validate_format(content: str) -> tuple[bool, list[str]]:
    """Validate that content follows the plan format.

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors: list[str] = []
    lines = content.splitlines()

    # Find the header line (must be first non-empty line starting with #)
    header_found = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if "implementation" in stripped.lower() and "plan" in stripped.lower():
                header_found = True
                break

    if not header_found:
        errors.append("Missing '# Implementation Plan' header")

    # Check for ## Features OR ## Phase sections (both are valid plan formats)
    has_features = False
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower == "## features" or lower.startswith("## features") or lower.startswith("## phase"):
            has_features = True
            break

    if not has_features:
        errors.append("Missing '## Features' or '## Phase' section")

    # Check metadata
    metadata = PlanMetadata.from_content(content)
    if not metadata.project:
        errors.append("Missing '**Project:**' metadata")
    if not metadata.spec_path:
        errors.append("Missing '**Spec:**' metadata")

    # Check task format
    task_ids_seen: set[str] = set()
    for line in content.splitlines():
        m = TASK_PATTERN.match(line)
        if m:
            task_id = m.group(1)
            if task_id in task_ids_seen:
                errors.append(f"Duplicate task ID: {task_id}")
            task_ids_seen.add(task_id)

    # Check feature format
    feature_ids_seen: set[str] = set()
    for line in content.splitlines():
        m = FEAT_PATTERN.match(line)
        if m:
            feat_id = m.group(1)
            if feat_id in feature_ids_seen:
                errors.append(f"Duplicate feature ID: {feat_id}")
            feature_ids_seen.add(feat_id)

    # Check separator and plan hash at end
    has_separator = False
    has_plan_hash = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("---"):
            has_separator = True
        if PLAN_HASH_PATTERN.match(line):
            has_plan_hash = True

    if not has_separator:
        errors.append("Missing '---' separator before metadata footer")

    if not has_plan_hash:
        errors.append("Missing '**Plan Hash:**' in footer")

    return len(errors) == 0, errors


def format_task_id(n: int) -> str:
    """Format task number as TASK-NNN."""
    return f"TASK-{n:03d}"


def format_feature_id(n: int) -> str:
    """Format feature number as FEAT-NNN."""
    return f"FEAT-{n:03d}"

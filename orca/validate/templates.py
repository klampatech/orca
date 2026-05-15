"""Test template format for spec-based test generation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


@dataclass
class TestTemplate:
    """Template for generating test cases from task specifications."""

    task_id: str
    description: str
    functional_requirements: list[str] = field(default_factory=list)
    test_cases: list[dict] = field(default_factory=list)  # {id, description, steps}
    edge_cases: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "TestTemplate":
        """Create a TestTemplate from a dictionary."""
        return cls(
            task_id=data.get("task_id", ""),
            description=data.get("description", ""),
            functional_requirements=data.get("functional_requirements", []),
            test_cases=data.get("test_cases", []),
            edge_cases=data.get("edge_cases", []),
        )

    def to_dict(self) -> dict:
        """Convert template to dictionary."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "functional_requirements": self.functional_requirements,
            "test_cases": self.test_cases,
            "edge_cases": self.edge_cases,
        }


def load_template(path: Path) -> TestTemplate:
    """Load a test template from a JSON or YAML file.

    Args:
        path: Path to the template file (.json or .yaml/.yml)

    Returns:
        TestTemplate instance

    Raises:
        FileNotFoundError: If template file doesn't exist
        ValueError: If template format is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")

    content = path.read_text()

    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(content)
    elif path.suffix.lower() == ".json":
        data = json.loads(content)
    else:
        raise ValueError(f"Unsupported template format: {path.suffix}")

    if not isinstance(data, dict):
        raise ValueError("Template must be a dictionary")

    return TestTemplate.from_dict(data)


def format_task_test(task_id: str, template: TestTemplate) -> str:
    """Format a test template as markdown for LLM context.

    Args:
        task_id: Unique identifier for the task
        template: TestTemplate containing test case details

    Returns:
        Markdown formatted string with Given/When/Then test format
    """
    lines = [
        f"# Test Specification: {task_id}",
        "",
        f"## Description",
        template.description,
        "",
        "## Functional Requirements",
    ]

    for i, req in enumerate(template.functional_requirements, 1):
        lines.append(f"{i}. {req}")

    lines.extend(["", "## Test Cases", ""])

    for tc in template.test_cases:
        case_id = tc.get("id", "unknown")
        description = tc.get("description", "No description")
        steps = tc.get("steps", [])

        lines.append(f"### {case_id}: {description}")
        lines.append("")

        for step in steps:
            if isinstance(step, dict):
                step_type = step.get("type", "step").upper()
                step_text = step.get("text", "")
                lines.append(f"**{step_type}**: {step_text}")
            else:
                lines.append(f"- {step}")

        lines.append("")

    if template.edge_cases:
        lines.extend(["## Edge Cases", ""])
        for edge_case in template.edge_cases:
            lines.append(f"- {edge_case}")
        lines.append("")

    return "\n".join(lines)
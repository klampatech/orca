"""Core validation logic."""

import subprocess
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .templates import TestTemplate, load_template
from .generator import TestGenerator
from .installer import DependencyInstaller


@dataclass
class ValidationResult:
    """Result of a validation run."""

    passed: bool
    task_id: str
    errors: list[str] = field(default_factory=list)
    test_output: str = ""
    generated_files: list[Path] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Convert result to dictionary for serialization."""
        return {
            "passed": self.passed,
            "task_id": self.task_id,
            "errors": self.errors,
            "test_output": self.test_output,
            "generated_files": [str(f) for f in self.generated_files],
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ValidationResult":
        """Create result from dictionary."""
        return cls(
            passed=data.get("passed", False),
            task_id=data.get("task_id", ""),
            errors=data.get("errors", []),
            test_output=data.get("test_output", ""),
            generated_files=[Path(f) for f in data.get("generated_files", [])],
            duration_seconds=data.get("duration_seconds", 0.0),
        )

    def summary(self) -> str:
        """Generate human-readable summary."""
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Validation Result: {self.task_id}",
            f"Status: {status}",
        ]
        if self.errors:
            lines.append("Errors:")
            for error in self.errors:
                lines.append(f"  - {error}")
        if self.generated_files:
            lines.append("Generated files:")
            for f in self.generated_files:
                lines.append(f"  - {f}")
        return "\n".join(lines)


class ValidationEngine:
    """Engine for running validation on task implementations."""

    def __init__(
        self,
        template_dir: Optional[Path] = None,
        test_output_dir: Optional[Path] = None,
    ):
        """Initialize the validation engine.

        Args:
            template_dir: Directory containing test templates
            test_output_dir: Directory to write generated tests
        """
        self.template_dir = template_dir or Path("templates")
        self.test_output_dir = test_output_dir
        self.generator = TestGenerator(test_output_dir)
        self.installer = DependencyInstaller()

    def _load_task_spec(self, spec_path: Path) -> dict:
        """Load task specification from file.

        Args:
            spec_path: Path to task spec file (.json, .yaml, or .md)

        Returns:
            Task dictionary
        """
        if not spec_path.exists():
            return {}

        content = spec_path.read_text()

        if spec_path.suffix.lower() in (".yaml", ".yml"):
            import yaml

            return yaml.safe_load(content) or {}
        elif spec_path.suffix.lower() == ".json":
            return json.loads(content)
        else:
            # Try to parse as markdown with frontmatter
            return self._parse_markdown_spec(content)

    def _parse_markdown_spec(self, content: str) -> dict:
        """Parse task spec from markdown format."""
        import re

        spec: dict = {}

        # Look for YAML frontmatter
        frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if frontmatter_match:
            import yaml

            spec = yaml.safe_load(frontmatter_match.group(1)) or {}

        # Look for key sections
        task_id_match = re.search(r"#\s*Task[:\s]+([^\n]+)", content)
        if task_id_match:
            spec["task_id"] = task_id_match.group(1).strip()

        desc_match = re.search(
            r"##\s*Description\s*\n(.*?)(?=\n##|$)", content, re.DOTALL
        )
        if desc_match:
            spec["description"] = desc_match.group(1).strip()

        # Extract functional requirements
        req_match = re.search(
            r"##\s*Requirements?\s*\n(.*?)(?=\n##|$)", content, re.DOTALL
        )
        if req_match:
            req_text = req_match.group(1)
            requirements = re.findall(r"^\d+\.\s+(.+)$", req_text, re.MULTILINE)
            spec["functional_requirements"] = requirements

        return spec

    def _find_template(self, task_id: str) -> Optional[Path]:
        """Find template file for a task ID."""
        if self.template_dir.exists():
            # Check for exact match
            for ext in [".json", ".yaml", ".yml"]:
                template_path = self.template_dir / f"{task_id}{ext}"
                if template_path.exists():
                    return template_path

            # Check for any matching file
            for template_path in self.template_dir.glob(f"{task_id}*"):
                return template_path

        return None

    def _create_template_from_spec(self, spec: dict) -> TestTemplate:
        """Create a TestTemplate from a task specification."""
        return TestTemplate(
            task_id=spec.get("task_id", "unknown"),
            description=spec.get("description", ""),
            functional_requirements=spec.get("functional_requirements", []),
            test_cases=spec.get("test_cases", []),
            edge_cases=spec.get("edge_cases", []),
        )

    def validate(
        self,
        task_id: str,
        spec_path: Path,
        impl_path: Optional[Path] = None,
        project_path: Optional[Path] = None,
    ) -> ValidationResult:
        """Validate a task implementation against its specification.

        Args:
            task_id: Unique identifier for the task
            spec_path: Path to task specification file
            impl_path: Path to implementation (optional, for reference)
            project_path: Project root path for test generation

        Returns:
            ValidationResult with pass/fail and details
        """
        start_time = time.time()
        errors = []
        generated_files = []
        test_output = ""

        if project_path is None:
            project_path = impl_path.parent if impl_path else Path.cwd()

        try:
            # Load specification
            spec = self._load_task_spec(spec_path)
            if not spec:
                errors.append(f"Could not load specification from {spec_path}")
                return ValidationResult(
                    passed=False,
                    task_id=task_id,
                    errors=errors,
                    duration_seconds=time.time() - start_time,
                )

            # Get or create template
            template_path = self._find_template(task_id)
            if template_path:
                template = load_template(template_path)
            else:
                template = self._create_template_from_spec(spec)

            # Ensure test dependencies are available
            self.installer.ensure_deps(project_path)

            # Generate tests
            test_output_dir = self.test_output_dir or (project_path / "tests")
            generated_files = self.generator.generate_tests(
                {"task_id": task_id, "project_path": project_path},
                template,
                test_output_dir,
            )

            # Try to run tests
            framework = self.generator.detect_framework(project_path)
            if framework == "pytest":
                result = subprocess.run(
                    ["pytest", str(test_output_dir), "-v", "--tb=short"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                test_output = result.stdout + result.stderr

                if result.returncode != 0:
                    # Check for test failures vs actual errors
                    if (
                        "error" in result.stdout.lower()
                        or "error" in result.stderr.lower()
                    ):
                        errors.append("Test execution encountered errors")
                    else:
                        errors.append(
                            "Some tests failed - implementation may be incomplete"
                        )
            elif framework == "jest":
                result = subprocess.run(
                    ["npm", "test", "--", "--testPathPattern=" + task_id],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                test_output = result.stdout + result.stderr
                if result.returncode != 0:
                    errors.append("Test execution failed")

        except subprocess.TimeoutExpired:
            errors.append("Test execution timed out after 180 seconds")
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")

        duration = time.time() - start_time
        passed = bool(len(errors) == 0 and test_output)

        return ValidationResult(
            passed=passed,
            task_id=task_id,
            errors=errors,
            test_output=test_output,
            generated_files=generated_files,
            duration_seconds=duration,
        )

    def generate_summary(self, failed_attempt: dict) -> str:
        """Generate a summary of a failed validation attempt.

        Args:
            failed_attempt: Dictionary with keys: task_id, error, test_output, etc.

        Returns:
            Markdown-formatted summary for retry context
        """
        lines = [
            "# Validation Failure Summary",
            "",
            f"**Task**: {failed_attempt.get('task_id', 'unknown')}",
            "",
            "## What Was Tried",
        ]

        if "spec_path" in failed_attempt:
            lines.append(f"- Loaded specification from: {failed_attempt['spec_path']}")

        if "impl_path" in failed_attempt:
            lines.append(f"- Implementation at: {failed_attempt['impl_path']}")

        if failed_attempt.get("generated_files"):
            lines.append("- Generated test files:")
            for f in failed_attempt["generated_files"]:
                lines.append(f"  - `{f}`")

        lines.extend(["", "## How It Failed", ""])

        if failed_attempt.get("errors"):
            for error in failed_attempt["errors"]:
                lines.append(f"- {error}")

        if failed_attempt.get("test_output"):
            lines.append("")
            lines.append("### Test Output")
            lines.append("```")
            # Truncate long output
            output = failed_attempt["test_output"]
            if len(output) > 2000:
                output = output[:2000] + "\n... (truncated)"
            lines.append(output)
            lines.append("```")

        lines.extend(["", "## Suggested Fixes", ""])
        lines.append("1. Review the test expectations in the generated test files")
        lines.append("2. Ensure implementation matches the functional requirements")
        lines.append("3. Check that all edge cases are handled")

        return "\n".join(lines)

    def run_validation(
        self, task: dict, project_path: Optional[Path] = None
    ) -> ValidationResult:
        """Run validation for a task dictionary.

        This is a convenience method that extracts paths from a task dict.

        Args:
            task: Task dictionary with task_id, spec_path, impl_path
            project_path: Override project root path

        Returns:
            ValidationResult
        """
        task_id = task.get("task_id", "unknown")
        spec_path = Path(task.get("spec_path", ""))
        impl_path = Path(task.get("impl_path", "")) if task.get("impl_path") else None

        if project_path is None:
            project_path = task.get("project_path")
            if project_path:
                project_path = Path(project_path)

        return self.validate(
            task_id=task_id,
            spec_path=spec_path,
            impl_path=impl_path,
            project_path=project_path,
        )


def run_validation(task: dict, project_path: Optional[Path] = None) -> ValidationResult:
    """Convenience function to run validation.

    Args:
        task: Task dictionary with task_id, spec_path, etc.
        project_path: Project root path

    Returns:
        ValidationResult
    """
    engine = ValidationEngine()
    return engine.run_validation(task, project_path)

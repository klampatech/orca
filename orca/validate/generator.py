"""Test code generator from templates."""

import subprocess
from pathlib import Path
from typing import Optional

from .templates import TestTemplate


class TestGenerator:
    """Generator for creating test files from templates."""

    FRAMEWORKS = {
        "pytest": ("pyproject.toml", "pytest.ini", "setup.py", "setup.cfg"),
        "jest": ("package.json", "jest.config.js", "jest.config.ts"),
        "go": ("go.mod",),
        "rspec": ("Gemfile",),
        "unittest": ("unittest.cfg",),
    }

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize the test generator.

        Args:
            output_dir: Directory where test files will be written.
                       Defaults to ./tests relative to project root.
        """
        self.output_dir = output_dir

    def detect_framework(self, project_path: Path) -> Optional[str]:
        """Detect test framework from project files.

        Args:
            project_path: Root path of the project

        Returns:
            Framework name (pytest, jest, go, rspec) or None if undetected
        """
        if not project_path.exists():
            project_path = Path.cwd()

        for framework, indicators in self.FRAMEWORKS.items():
            for indicator in indicators:
                if (project_path / indicator).exists():
                    return framework

        # Check for Python files as fallback
        if any(project_path.glob("*.py")):
            return "pytest"

        # Check for JavaScript/TypeScript files
        if any(project_path.glob("*.js")) or any(project_path.glob("*.ts")):
            return "jest"

        return None

    def _get_output_dir(self, project_path: Path) -> Path:
        """Get or create the test output directory."""
        if self.output_dir:
            output = self.output_dir
        else:
            # Default to tests/ directory
            output = project_path / "tests"

        output.mkdir(parents=True, exist_ok=True)
        return output

    def _generate_pytest_test(
        self, task: dict, template: TestTemplate, output_dir: Path
    ) -> Path:
        """Generate a pytest test file."""
        test_name = f"test_{template.task_id.replace('-', '_')}.py"
        test_file = output_dir / test_name

        # Get implementation info
        impl = task.get("implementation", {})
        impl.get("file", "")  # kept for documentation

        content = [
            '"""Auto-generated test for task: {}""".'.format(template.task_id),
            "",
            "import pytest",
            "import sys",
            "from pathlib import Path",
            "",
            "# Add project root to path",
            "project_root = Path(__file__).parent.parent",
            "sys.path.insert(0, str(project_root))",
            "",
            "",
            f"class Test{template.task_id.replace('-', '_').title().replace('_', '')}:",
        ]

        for tc in template.test_cases:
            case_id = tc.get("id", "test_case")
            method_name = f"test_{case_id.replace('-', '_')}"
            lines = [
                "",
                f"    def {method_name}(self):",
                f'        """Test: {tc.get("description", "")}"""',
            ]

            steps = tc.get("steps", [])
            for step in steps:
                if isinstance(step, dict):
                    step_type = step.get("type", "step")
                    step_text = step.get("text", "")
                    if step_type.lower() == "given":
                        lines.append(f"        # Given: {step_text}")
                    elif step_type.lower() == "when":
                        lines.append(f"        # When: {step_text}")
                    elif step_type.lower() == "then":
                        lines.append(f"        # Then: {step_text}")
                    else:
                        lines.append(f"        # {step_text}")

            # Add assertion placeholder
            lines.append("        # TODO: Add assertions based on expected behavior")
            lines.append("        pass")

            content.extend(lines)

        # Add edge cases as skipped tests
        if template.edge_cases:
            content.extend(["", "    # Edge cases (not yet implemented)"])
            for edge in template.edge_cases:
                edge_name = edge.lower().replace(" ", "_").replace("-", "_")
                content.extend(
                    [
                        "",
                        "    @pytest.mark.skip(reason='Edge case not yet implemented')",
                        f"    def test_edge_{edge_name}(self):",
                        f'        """Edge case: {edge}"""',
                        "        pass",
                    ]
                )

        test_file.write_text("\n".join(content))
        return test_file

    def _generate_jest_test(
        self, task: dict, template: TestTemplate, output_dir: Path
    ) -> Path:
        """Generate a Jest test file."""
        test_name = f"{template.task_id.replace('-', '_')}.test.js"
        test_file = output_dir / test_name

        content = [
            "/**",
            f" * Auto-generated test for task: {template.task_id}",
            f" * Description: {template.description}",
            " */",
            "",
            "describe('{}', () => {{".format(
                template.task_id.replace("-", " ").title()
            ),
        ]

        for tc in template.test_cases:
            content.extend(
                [
                    "",
                    f"  test('{tc.get('description', '')}', () => {{",
                ]
            )

            steps = tc.get("steps", [])
            for step in steps:
                if isinstance(step, dict):
                    step_type = step.get("type", "step")
                    step_text = step.get("text", "")
                    comment = f"// {step_type.upper()}: {step_text}"
                    content.append(f"    {comment}")

            content.extend(
                [
                    "    // TODO: Add assertions",
                    "    expect(true).toBe(true);",
                    "  });",
                ]
            )

        content.append("});")

        test_file.write_text("\n".join(content))
        return test_file

    def _generate_go_test(
        self, task: dict, template: TestTemplate, output_dir: Path
    ) -> Path:
        """Generate a Go test file."""
        test_name = f"{template.task_id.replace('-', '_')}_test.go"
        test_file = output_dir / test_name

        content = [
            "// Package tests - auto-generated test for task: {}".format(
                template.task_id
            ),
            "package tests",
            "",
            'import "testing"',
            "",
        ]

        for tc in template.test_cases:
            case_id = tc.get("id", "test_case")
            func_name = f"Test{case_id.replace('-', '_').title().replace('_', '')}"

            content.extend(
                [
                    "",
                    f"func {func_name}(t *testing.T) {{",
                    f"    // Test: {tc.get('description', '')}",
                ]
            )

            steps = tc.get("steps", [])
            for step in steps:
                if isinstance(step, dict):
                    step_type = step.get("type", "step")
                    step_text = step.get("text", "")
                    content.append(f"    // {step_type.upper()}: {step_text}")

            content.extend(
                [
                    "    // TODO: Add assertions",
                    "}",
                ]
            )

        test_file.write_text("\n".join(content))
        return test_file

    def generate_tests(
        self, task: dict, template: TestTemplate, output_dir: Path
    ) -> list[Path]:
        """Generate test files from template for detected framework.

        Args:
            task: Task dictionary containing task metadata
            template: TestTemplate with test case definitions
            output_dir: Directory to write test files to

        Returns:
            List of generated test file paths
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Detect framework from task or use default
        project_path = task.get("project_path", Path.cwd())
        framework = task.get("test_framework", self.detect_framework(project_path))

        if framework == "pytest":
            return [self._generate_pytest_test(task, template, output_dir)]
        elif framework == "jest":
            return [self._generate_jest_test(task, template, output_dir)]
        elif framework == "go":
            return [self._generate_go_test(task, template, output_dir)]
        else:
            # Default to pytest
            return [self._generate_pytest_test(task, template, output_dir)]

    def generate_and_run(
        self, task: dict, template: TestTemplate, project_path: Path
    ) -> tuple[list[Path], subprocess.CompletedProcess | None]:
        """Generate tests and attempt to run them.

        Args:
            task: Task dictionary
            template: TestTemplate with test cases
            project_path: Project root path

        Returns:
            Tuple of (generated_files, run_result or None)
        """
        framework = task.get("test_framework", self.detect_framework(project_path))
        output_dir = self._get_output_dir(project_path)

        generated = self.generate_tests(task, template, output_dir)

        result = None
        try:
            if framework == "pytest":
                result = subprocess.run(
                    ["pytest", str(output_dir), "-v"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            elif framework == "jest":
                result = subprocess.run(
                    ["npm", "test", "--", str(output_dir)],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # Tests couldn't be run, but files were generated

        return generated, result


def generate_tests_for_task(
    task: dict, template: TestTemplate, output_dir: Path
) -> list[Path]:
    """Convenience function to generate tests for a task.

    Args:
        task: Task dictionary with metadata
        template: TestTemplate with test cases
        output_dir: Directory to write tests to

    Returns:
        List of generated test file paths
    """
    generator = TestGenerator()
    return generator.generate_tests(task, template, output_dir)

"""orch plan — Generate an implementation plan from a spec file.

Uses an iterative LLM-driven process to produce a structured
implementation plan (IMPLEMENTATION_PLAN.md) from a spec (markdown
or JSON IR). The plan follows the orca plan schema:

- `# Implementation Plan` header
- `**Project:**` and `**Spec:**` metadata
- `## Features` section with `### FEAT-NNN:` subsections
- `- [ ] TASK-NNN:` task lines
- `---` separator and `**Plan Hash:**` footer

Returns a result dict with status, iteration count, and a plan summary
(project name, feature count, task count).
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from ..plan.schema import validate_format


# --------------------------------------------------------------------
# PlanGenerator
# --------------------------------------------------------------------


class PlanGenerator:
    """Iteratively generate an implementation plan via LLM calls."""

    def __init__(
        self,
        max_iterations: int = 10,
        pi_skill: str = "plan",
    ):
        self.max_iterations = max_iterations
        self.pi_skill = pi_skill

    def generate(
        self,
        spec_content: str,
        spec_display: str,
        output_path: str | Path,
    ) -> dict[str, Any]:
        """Generate an implementation plan from spec content.

        Iteratively calls `pi -s <skill>` to refine the plan until it
        stabilises or max_iterations is reached.

        Args:
            spec_content: Raw content of the spec file(s).
            spec_display: Display name for spec (file path or dir description).
            output_path: Path where the plan will be written.

        Returns:
            Result dict with status, iterations, output_path, plan_summary.

        Raises:
            RuntimeError: If plan generation fails.
        """
        output_path = Path(output_path)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine project name from spec content
        project_name = self._extract_project_name(spec_content, spec_display)

        # Start with an empty plan or existing plan
        existing_content: str | None = None
        if output_path.exists():
            existing_content = output_path.read_text()

        plan_content = self._initial_plan(project_name, spec_path, existing_content)

        iterations = 0
        prev_hash = ""

        for i in range(1, self.max_iterations + 1):
            iterations = i

            # Build the prompt for pi
            prompt = self._build_prompt(spec_content, plan_content, i)

            # Call pi with the plan skill
            print(f"[plan] Iteration {i}/{self.max_iterations} — refining plan...")
            pi_result = subprocess.run(
                ["pi", "-s", self.pi_skill],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=Path.cwd(),
            )

            if pi_result.returncode != 0:
                stderr = pi_result.stderr[:1000] if pi_result.stderr else ""
                raise RuntimeError(
                    f"Plan generation failed at iteration {i}: {stderr}"
                )

            output = pi_result.stdout.strip()
            if not output:
                raise RuntimeError(
                    f"Plan generation returned empty output at iteration {i}"
                )

            plan_content = output

            # Check hash stability
            current_hash = self._compute_content_hash(plan_content)
            if current_hash == prev_hash and i > 1:
                print(f"[plan] Plan stabilised after {i} iterations")
                break
            prev_hash = current_hash

        # Write final plan
        output_path.write_text(plan_content)

        # Validate the generated plan
        valid, errors = validate_format(plan_content)
        if not valid:
            error_lines = "\n  - ".join(errors[:10])
            raise ValueError(f"Invalid plan format:\n  - {error_lines}")

        # Build summary
        summary = self._extract_summary(plan_content)

        return {
            "command": "plan",
            "status": "success",
            "iterations": iterations,
            "output_path": str(output_path),
            "plan_summary": summary,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_project_name(self, spec_content: str, spec_display: str) -> str:
        """Extract project name from spec content or display name."""
        for line in spec_content.splitlines():
            # Match **Project:** or Project: patterns
            m = re.match(r"^\*\*Project:\*\*\s*(.+)$", line)
            if m:
                return m.group(1).strip()
            m = re.match(r"^Project:\s*(.+)$", line)
            if m:
                return m.group(1).strip()
        # Fallback: use spec display (strip path prefix)
        return Path(spec_display.split("/")[-1].split(" ")[0]).stem or "Project"

    def _initial_plan(self, project_name: str, spec_display: str, existing: str | None) -> str:
        """Create the initial plan content."""
        if existing:
            return existing

        return (
            f"# Implementation Plan\n"
            f"\n"
            f"**Project:** {project_name}\n"
            f"**Spec:** {spec_display}\n"
            f"\n"
            f"## Features\n"
            f"\n"
            f"---\n"
            f"\n"
            f"**Plan Hash:** 0000000000\n"
        )

    def _build_prompt(self, spec_content: str, plan_content: str, iteration: int) -> str:
        """Build the prompt for the LLM plan refinement step."""
        return (
            f"You are generating an implementation plan. "
            f"This is iteration {iteration}.\n"
            f"\n"
            f"Source spec:\n"
            f"```\n"
            f"{spec_content}\n"
            f"```\n"
            f"\n"
            f"Current plan (refine and improve):\n"
            f"```\n"
            f"{plan_content}\n"
            f"```\n"
            f"\n"
            f"Rules:\n"
            f"- Start with '# Implementation Plan' header\n"
            f"- Include '**Project:**' and '**Spec:**' metadata\n"
            f"- Use '## Features' section header\n"
            f"- Use '### FEAT-NNN: <description>' for features\n"
            f"- Use '- [ ] TASK-NNN: <description>' for tasks\n"
            f"- End with '---' separator and '**Plan Hash:** <hash>'\n"
            f"- Each feature must have at least one task\n"
            f"- Use sequential IDs: FEAT-001, FEAT-002, TASK-001, etc.\n"
            f"\n"
            f"Output ONLY the plan markdown. No explanation.\n"
        )

    def _compute_content_hash(self, content: str) -> str:
        """Compute a simple hash of the plan content for stability detection."""
        import hashlib

        return hashlib.sha256(content.encode()).hexdigest()[:10]

    def _extract_summary(self, plan_content: str) -> dict[str, Any]:
        """Extract a summary from the plan content."""
        project = ""
        for line in plan_content.splitlines():
            m = re.match(r"^\*\*Project:\*\*\s*(.+)$", line)
            if m:
                project = m.group(1).strip()
                break

        feature_count = len(re.findall(r"^### (FEAT-\d+):", plan_content, re.MULTILINE))
        task_count = len(re.findall(r"^- \[ \] (TASK-\d+):", plan_content, re.MULTILINE))

        return {
            "project": project,
            "feature_count": feature_count,
            "task_count": task_count,
        }


# --------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------


def handle_plan(args) -> dict:
    """Handle the 'orca plan' command.

    Args:
        args.spec: Path to the spec file or directory containing specs.
        args.output: Output path for the plan (default: IMPLEMENTATION_PLAN.md).
        args.max_iterations: Maximum refinement iterations (default: 10).
        args.pi_skill: Pi skill name for LLM calls (default: plan).
        args.force: Overwrite existing plan (default: False).

    Returns:
        Result dict with status, iterations, output_path, plan_summary.

    Raises:
        FileNotFoundError: If spec file/directory does not exist.
        RuntimeError: If plan generation fails.
        ValueError: If generated plan has invalid format.
    """
    spec_path = Path(args.spec)
    output_path = Path(getattr(args, "output", None) or "IMPLEMENTATION_PLAN.md")
    max_iterations = getattr(args, "max_iterations", 10) or 10
    pi_skill = getattr(args, "pi_skill", None) or "plan"
    force = getattr(args, "force", False)

    # 1. Validate spec path exists
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec path not found: {spec_path}")

    # 2. Collect spec content (file or directory)
    if spec_path.is_dir():
        # Collect all .md and .json files from directory
        spec_files = sorted(spec_path.glob("*.md")) + sorted(spec_path.glob("*.json"))
        if not spec_files:
            raise RuntimeError(f"No spec files found in {spec_path}")
        
        print(f"[plan] Found {len(spec_files)} spec(s) in {spec_path}:")
        for f in spec_files:
            print(f"[plan]   - {f.name}")
        
        spec_contents = []
        for f in spec_files:
            content = f.read_text()
            spec_contents.append(f"--- {f.name} ---\n{content}")
        
        spec_content = "\n\n".join(spec_contents)
        spec_display = f"{spec_path}/ (contains {len(spec_files)} spec files)"
    else:
        # Single spec file
        spec_content = spec_path.read_text()
        spec_display = str(spec_path)

    # 3. Check output path doesn't exist (unless --force)
    if output_path.exists() and not force:
        raise RuntimeError(
            f"Output file already exists: {output_path}. "
            f"Use --force to overwrite."
        )

    # 5. Call PlanGenerator with spec content and display name
    generator = PlanGenerator(
        max_iterations=max_iterations,
        pi_skill=pi_skill,
    )

    result = generator.generate(spec_content, spec_display, output_path)

    # 4. Validate generated plan format (already done inside generate,
    #    but double-check the written file)
    plan_content = output_path.read_text()
    valid, errors = validate_format(plan_content)
    if not valid:
        error_lines = "\n  - ".join(errors[:10])
        raise ValueError(f"Invalid plan format:\n  - {error_lines}")

    # 5. Return result dict
    return {
        "command": "plan",
        "status": result["status"],
        "iterations": result["iterations"],
        "output_path": result["output_path"],
        "plan_summary": result["plan_summary"],
    }


# --------------------------------------------------------------------
# Formatter
# --------------------------------------------------------------------


def format_plan_human(result: dict) -> str:
    """Format the plan command result for human display.

    Args:
        result: Result dict from handle_plan.

    Returns:
        Formatted human-readable string.
    """
    status = result.get("status", "unknown")
    iterations = result.get("iterations", 0)
    output_path = result.get("output_path", "")
    summary = result.get("plan_summary", {})

    icon = "✓" if status == "success" else "✗" if status == "failed" else "⚠"
    project = summary.get("project", "?")
    feature_count = summary.get("feature_count", 0)
    task_count = summary.get("task_count", 0)

    lines = [
        f"{icon} Plan generated successfully",
        f"  Project: {project}",
        f"  Features: {feature_count}",
        f"  Tasks: {task_count}",
        f"  Iterations: {iterations}",
        f"  Output: {output_path}",
    ]
    return "\n".join(lines)

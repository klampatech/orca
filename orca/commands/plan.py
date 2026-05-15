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
        verbose: bool = False,
    ):
        self.max_iterations = max_iterations
        self.pi_skill = pi_skill
        self.verbose = verbose

    def generate(
        self,
        spec_content: str,
        spec_display: str,
        output_path: str | Path,
    ) -> dict[str, Any]:
        """Generate an implementation plan from spec content."""
        output_path = Path(output_path)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine project name from spec content
        project_name = self._extract_project_name(spec_content, spec_display)

        # Start with an empty plan or existing plan
        existing_content: str | None = None
        if output_path.exists():
            existing_content = output_path.read_text()

        plan_content = self._initial_plan(project_name, spec_display, existing_content)

        iterations = 0
        prev_hash = ""

        for i in range(1, self.max_iterations + 1):
            iterations = i

            # Build the prompt for pi
            prompt = self._build_prompt(spec_content, plan_content, i)

            # Call pi with retry logic for transient errors
            if self.verbose:
                print(f"[plan] Iteration {i}/{self.max_iterations}...")

            max_retries = 3
            retry_delay = 5  # seconds

            for attempt in range(max_retries):
                try:
                    pi_result = subprocess.run(
                        ["pi", "--skill", self.pi_skill, "-p", prompt],
                        capture_output=True,
                        text=True,
                        timeout=300,
                        cwd=Path.cwd(),
                    )

                    if pi_result.returncode != 0:
                        stderr = pi_result.stderr[:1000] if pi_result.stderr else ""
                        
                        # Check for retryable errors
                        retryable = any(err in stderr.lower() for err in [
                            "rate limit", "429", "timeout", "503", "502", "500",
                            "connection", "network", "temporarily"
                        ])
                        
                        if retryable and attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)
                            print(f"[plan] Retryable error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                        
                        raise RuntimeError(
                            f"Plan generation failed at iteration {i}: {stderr}"
                        )

                    output = pi_result.stdout.strip()
                    if not output:
                        stderr = pi_result.stderr[:500] if pi_result.stderr else ""
                        
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)
                            print(f"[plan] Empty output, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                        
                        # Last attempt - continue with existing plan if available
                        if plan_content:
                            print(f"[plan] Using existing plan after {max_retries} failed attempts")
                            break
                        raise RuntimeError(
                            f"Plan generation returned empty output at iteration {i}"
                        )

                    # Success - update plan content
                    plan_content = output

                    # Log for debugging
                    current_hash = self._compute_content_hash(plan_content)
                    if self.verbose:
                        stability = "✓" if current_hash == prev_hash and i > 1 else "✗"
                        print(f"[plan]   hash={current_hash} (prev={prev_hash}) {stability}")

                    break  # Exit retry loop on success

                except subprocess.TimeoutExpired:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"[plan] Timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        raise RuntimeError(f"pi timed out after {max_retries} attempts")

            # Check hash stability
            current_hash = self._compute_content_hash(plan_content)
            if self.verbose:
                feat_count = len([l for l in plan_content.split('\n') if l.startswith('### FEAT-')])
                task_count = len([l for l in plan_content.split('\n') if '- [ ] TASK-' in l])
                print(f"[plan]   hash={current_hash} prev={prev_hash} feats={feat_count} tasks={task_count}")

            if current_hash == prev_hash and i > 1:
                print(f"[plan] ✓ Plan stabilised after {i} iterations")
                output_path.write_text(plan_content)  # Final save
                break
            prev_hash = current_hash

        # Write final plan (save after loop ends)
        output_path.write_text(plan_content)

        # Validate the generated plan - try to fix if invalid
        valid, errors = validate_format(plan_content)
        if not valid:
            # Try to fix missing Plan Hash footer
            if not any("**Plan Hash:**" in l for l in plan_content.split('\n')):
                print(f"[plan] Fixing missing Plan Hash footer...")
                plan_hash = self._compute_content_hash(plan_content)
                plan_content = plan_content.rstrip() + "\n\n---\n\n**Plan Hash:** " + plan_hash + "\n"
                output_path.write_text(plan_content)
                valid, errors = validate_format(plan_content)

            if not valid:
                # Give up on strict validation, write what we have
                print(f"[plan] Warning: Plan validation issues: {errors[:3]}")
                summary = self._extract_summary(plan_content)
                return {
                    "command": "plan",
                    "status": "success",
                    "iterations": iterations,
                    "output_path": str(output_path),
                    "plan_summary": summary,
                    "warnings": errors,
                }

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
            m = re.match(r"^\*\*Project:\*\*\s*(.+)$", line)
            if m:
                return m.group(1).strip()
            m = re.match(r"^Project:\s*(.+)$", line)
            if m:
                return m.group(1).strip()
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
        """Build the prompt for the LLM plan refinement step.
        
        Uses Ralph playbook approach:
        - Study specs for requirements
        - Compare against current plan
        - Plan only, no implementation
        """
        
        # Check if this looks like an initial/empty plan
        is_initial = "## Features" not in plan_content or plan_content.count("TASK-") == 0
        
        if is_initial:
            # Initial generation - study specs and create plan
            prompt = (
                "You are generating an IMPLEMENTATION_PLAN.md from specifications.\n"
                "\n"
                "## YOUR TASK\n"
                "1. Study the specifications provided below\n"
                "2. Identify core features and their requirements\n"
                "3. Break features into concrete, actionable tasks\n"
                "4. Output ONLY the plan in the specified format\n"
                "\n"
                "## PLANNING RULES\n"
                "- Plan only — do NOT implement anything\n"
                "- Concrete tasks — each task is a single, testable step\n"
                "- Sequential IDs — FEAT-001, TASK-001, etc.\n"
                "- Compute Plan Hash — SHA256 of sorted task IDs, first 10 chars\n"
                "\n"
                "## SOURCE SPECIFICATIONS\n"
                "\n"
            )
            prompt += spec_content
            prompt += (
                "\n"
                "\n"
                "## OUTPUT FORMAT\n"
                "\n"
                "```markdown\n"
                "# Implementation Plan\n"
                "\n"
                "**Project:** <name>\n"
                "**Spec:** specs/ (contains multiple spec files)\n"
                "**Mode:** PLANNING\n"
                "\n"
                "## Features\n"
                "\n"
                "### FEAT-001: <feature name>\n"
                "- [ ] TASK-001: <concrete task description>\n"
                "- [ ] TASK-002: <concrete task description>\n"
                "\n"
                "---\n"
                "\n"
                "**Plan Hash:** <10-char hash of sorted task IDs>\n"
                "```\n"
                "\n"
                "## NOTES\n"
                "- Tasks should be small enough to implement in one session\n"
                "- Include: setup, core logic, error handling, edge cases, testing\n"
                "- Each feature must have at least one task\n"
                "\n"
                "Output ONLY the plan markdown, nothing else.\n"
            )
        else:
            # Refinement - compare current plan against specs, identify gaps
            prompt = (
                "You are refining an IMPLEMENTATION_PLAN.md based on specifications.\n"
                "\n"
                "## YOUR TASK\n"
                "1. Review the current plan below\n"
                "2. Compare it against the specifications\n"
                "3. Identify gaps, missing tasks, or areas needing refinement\n"
                "4. Update the plan to be comprehensive\n"
                "\n"
                "## CURRENT PLAN\n"
                "\n"
                "```\n"
            )
            prompt += plan_content
            prompt += (
                "\n"
                "```\n"
                "\n"
                "## SOURCE SPECIFICATIONS\n"
                "\n"
                "```\n"
            )
            prompt += spec_content
            prompt += (
                "\n"
                "```\n"
                "\n"
                "## REFINE INSTRUCTIONS\n"
                "- Keep correct parts of the current plan\n"
                "- Add missing features/tasks from the specs\n"
                "- Remove redundant or completed items\n"
                "- Ensure each task is concrete and actionable\n"
                "- Check that all spec requirements are covered\n"
                "\n"
                "## OUTPUT FORMAT\n"
                "\n"
                "```markdown\n"
                "# Implementation Plan\n"
                "\n"
                "**Project:** <name>\n"
                "**Spec:** specs/ (contains multiple spec files)\n"
                "**Mode:** PLANNING\n"
                "\n"
                "## Features\n"
                "\n"
                "### FEAT-001: <feature name>\n"
                "- [ ] TASK-001: <task>\n"
                "\n"
                "---\n"
                "\n"
                "**Plan Hash:** <10-char hash>\n"
                "```\n"
                "\n"
                "## IMPORTANT\n"
                "- Output ONLY the plan markdown\n"
                "- Do NOT include explanations or commentary\n"
                "- Re-compute the Plan Hash for the updated task list\n"
                "\n"
                "Output only the plan.\n"
            )
        
        return prompt

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
    """Handle the 'orca plan' command."""
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
        spec_content = spec_path.read_text()
        spec_display = str(spec_path)

    # 3. Check output path doesn't exist (unless --force)
    if output_path.exists() and not force:
        raise RuntimeError(
            f"Output file already exists: {output_path}. "
            f"Use --force to overwrite."
        )

    # Call PlanGenerator
    generator = PlanGenerator(
        max_iterations=max_iterations,
        pi_skill=pi_skill,
        verbose=getattr(args, "verbose", False),
    )

    result = generator.generate(spec_content, spec_display, output_path)

    # Validate generated plan format
    plan_content = output_path.read_text()
    valid, errors = validate_format(plan_content)
    if not valid:
        error_lines = "\n  - ".join(errors[:10])
        raise ValueError(f"Invalid plan format:\n  - {error_lines}")

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
    """Format the plan command result for human display."""
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

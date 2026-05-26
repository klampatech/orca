"""orch plan — Generate an implementation plan from a spec file.

Uses Claude Code with the same approach as Otto:
1. Pass spec content + existing plan + instructions directly via -p (not temp file with relative paths)
2. Refine existing IMPLEMENTATION_PLAN.md (don't recreate)
3. Plan hash stability detection with PLAN_STABILITY_THRESHOLD=2
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Set


PLAN_PROMPT_TEMPLATE = """
## Your Task

Generate or refine an implementation plan by analyzing the specs and existing plan below.

## Critical Rule: INCREMENTAL PLANNING

**The IMPLEMENTATION_PLAN.md already exists.** You MUST preserve it:

1. **Read the existing plan** (provided below)
2. **Analyze the specs** (provided below)  
3. **Make surgical updates only:**
   - Add new tasks that address gaps between specs and code
   - Refine incomplete tasks that need clarification
   - Mark tasks as complete [x] if they've been implemented
   - Remove tasks that are no longer relevant
4. **Do NOT recreate the entire plan** — only refine what's necessary

## Output Format

Output ONLY the complete, refined markdown plan. No explanation, no code blocks, no preamble.

Format:
# Implementation Plan

**Project:** {project_name}
**Spec:** {spec_display}

## Features

### FEAT-001: Feature Name

- [ ] TASK-001: Task description
- [x] TASK-002: Completed task

...

---

**Plan Hash:** <hash will be computed from task IDs>

## Important Refinement Rules

- **Preserve task descriptions** — do NOT rephrase or reword tasks unnecessarily
- **Consistency matters more than perfection** — minor description tweaks cause instability
- **Coordinate task renumbering** — if renumbering, update ALL references
- **Incremental only** — if plan looks reasonable, return it unchanged
- **Preserve existing structure** — if the existing plan uses Phases or Features sections, keep using that same structure

## Specs

{specs_content}

---
## Existing Plan

{existing_plan_content}
"""


# --------------------------------------------------------------------
# PlanGenerator
# --------------------------------------------------------------------


class PlanGenerator:
    """Generate an implementation plan via Claude Code."""

    _MAX_RETRIES = 3
    _RETRY_DELAY_BASE = 5  # seconds

    def __init__(
        self,
        max_iterations: int = 10,
        verbose: bool = False,
    ):
        """Initialize the plan generator."""
        self.max_iterations = max_iterations
        self.verbose = verbose

    def generate(
        self,
        spec_content: str,
        spec_display: str,
        output_path: str | Path,
        existing_plan_content: str = "",
    ) -> dict[str, Any]:
        """Generate an implementation plan using Claude Code."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Extract project name from spec
        project_name = self._extract_project_name(spec_content, spec_display)

        # Track "existing" plan separately so we don't feed back our own output
        # First iteration: no existing plan (starts from scratch)
        # Subsequent iterations: refine the plan from PREVIOUS iteration
        previous_plan = ""
        prev_hash = ""
        stable_count = 0
        PLAN_STABILITY_THRESHOLD = 2

        # Semantic tracking: use task IDs (not file hash) for stability
        # This means "stable" when the same task IDs appear across iterations,
        # regardless of description changes or formatting differences
        prev_task_ids: Set[str] = set()

        # Phase 1: Generate plan until stable
        for i in range(1, self.max_iterations + 1):
            if self.verbose:
                print(f"[plan] Iteration {i}/{self.max_iterations}...")

            # Build prompt with current "existing" plan (prev iteration's output)
            # Escape curly braces in previous_plan to avoid .format() interpolation issues
            escaped_previous = previous_plan.replace("{", "{{}}").replace("}", "{{}}")
            prompt = PLAN_PROMPT_TEMPLATE.format(
                project_name=project_name,
                spec_display=spec_display,
                specs_content=spec_content,
                existing_plan_content=escaped_previous if previous_plan else "N/A - no existing plan",
            )

            # Run Claude Code with context directly in prompt
            plan_content = self._call_claude(prompt)
            if not plan_content:
                if self.verbose:
                    print("[plan] No content returned, trying again...")
                prev_hash = ""  # Reset hash to force another iteration
                continue

            # Clean markdown code blocks if Claude wrapped output
            plan_content = self._unwrap_markdown(plan_content)

            # Save this iteration's output as "previous" for next iteration
            previous_plan = plan_content

            # Extract current task IDs for semantic stability check
            current_task_ids = set(self._extract_task_ids(plan_content))

            # Write plan for this iteration
            output_path.write_text(plan_content)

            # Check FILE hash stability (md5 like Otto) - printed for debugging
            current_hash = self._file_hash(str(output_path))

            # Semantic stability: same task IDs = stable plan content
            # Don't rephrase descriptions unnecessarily!
            if prev_task_ids and current_task_ids == prev_task_ids:
                stable_count += 1
                if self.verbose:
                    print(f"[plan]   task_ids={len(current_task_ids)} stable_count={stable_count} (semantically stable)")
                if stable_count >= PLAN_STABILITY_THRESHOLD:
                    if self.verbose:
                        print(f"[plan] ✓ Plan semantically stable after {i} iterations")
                    break
            else:
                stable_count = 0

            prev_task_ids = current_task_ids
            prev_hash = current_hash

        # Extract summary
        feat_count = len(self._extract_feature_ids(plan_content))
        task_count = len(self._extract_task_ids(plan_content))

        return {
            "command": "plan",
            "status": "success",
            "iterations": i,
            "output_path": str(output_path),
            "plan_summary": {
                "project": project_name,
                "feature_count": feat_count,
                "task_count": task_count,
            },
        }

    def _call_claude(self, prompt: str) -> str:
        """Call Claude Code and return the result text."""
        for attempt in range(self._MAX_RETRIES):
            try:
                result = subprocess.run(
                    [
                        "claude",
                        "-p",
                        prompt,
                        "--dangerously-skip-permissions",
                        "--output-format=json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    cwd=Path.cwd(),
                )

                if result.returncode != 0:
                    stderr = result.stderr[:500] if result.stderr else ""
                    if self.verbose:
                        print(f"[plan] Claude error: {stderr[:200]}")
                    if attempt < self._MAX_RETRIES - 1:
                        time.sleep(self._RETRY_DELAY_BASE * (2**attempt))
                        continue
                    return ""

                output = result.stdout.strip()
                if not output:
                    if attempt < self._MAX_RETRIES - 1:
                        time.sleep(self._RETRY_DELAY_BASE * (2**attempt))
                        continue
                    return ""

                # Parse JSON output if available
                try:
                    data = json.loads(output)
                    if "result" in data:
                        return data["result"]
                    elif "content" in data:
                        return data["content"]
                except (json.JSONDecodeError, TypeError):
                    pass  # Use raw output

                return output

            except subprocess.TimeoutExpired:
                if self.verbose:
                    print(f"[plan] Timeout on attempt {attempt + 1}")
                if attempt < self._MAX_RETRIES - 1:
                    time.sleep(self._RETRY_DELAY_BASE * (2**attempt))
                else:
                    if self.verbose:
                        print("[plan] Timeout after 3 attempts")
                continue

        return ""

    def _unwrap_markdown(self, content: str) -> str:
        """Strip markdown code block wrappers if present."""
        # Strip ```markdown ... ``` or ``` ... ``` wrapper
        stripped = content.strip()
        if stripped.startswith("```markdown\n"):
            stripped = stripped[12:]
        elif stripped.startswith("```\n"):
            stripped = stripped[4:]
        if stripped.endswith("\n```"):
            stripped = stripped[:-4]
        elif stripped.endswith("```"):
            stripped = stripped[:-3]
        return stripped.strip()

    def _file_hash(self, filepath: str) -> str:
        """Compute md5 hash of file (like Otto's md5 -q)."""
        with open(filepath, "r") as f:
            return hashlib.md5(f.read().encode()).hexdigest()

    def _extract_project_name(self, spec_content: str, spec_display: str) -> str:
        """Extract project name from spec content."""
        for line in spec_content.splitlines()[:50]:
            m = re.match(r"^\*\*Project:\*\*\s*(.+)$", line)
            if m:
                return m.group(1).strip()
            m = re.match(r"^Project:\s*(.+)$", line)
            if m:
                return m.group(1).strip()
        return Path(spec_display.split("/")[-1].split(" ")[0]).stem or "Project"

    def _extract_task_ids(self, content: str) -> list[str]:
        """Extract task IDs from plan content."""
        return re.findall(r"(TASK-\d+)", content)

    def _extract_feature_ids(self, content: str) -> list[str]:
        """Extract feature IDs from plan content."""
        return re.findall(r"(FEAT-\d+)", content)


# --------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------


def handle_plan(args) -> dict:
    """Handle the 'orca plan' command."""
    spec_path = Path(args.spec)
    output_path = Path(getattr(args, "output", None) or "IMPLEMENTATION_PLAN.md")
    max_iterations = getattr(args, "max_iterations", 10) or 10
    force = getattr(args, "force", False)

    if not spec_path.exists():
        raise FileNotFoundError(f"Spec path not found: {spec_path}")

    # Collect spec content (for project name extraction only)
    if spec_path.is_dir():
        spec_files = sorted(spec_path.glob("*.md")) + sorted(spec_path.glob("*.json"))
        if not spec_files:
            raise RuntimeError(f"No spec files found in {spec_path}")
        print(f"[plan] Found {len(spec_files)} spec(s) in {spec_path}:")
        for f in spec_files:
            print(f"[plan]   - {f.name}")
        spec_contents = []
        for f in spec_files:
            spec_contents.append(f"--- {f.name} ---\n{f.read_text()}")
        spec_content = "\n\n".join(spec_contents)
        spec_display = f"{spec_path}/ (contains {len(spec_files)} spec files)"
    else:
        spec_content = spec_path.read_text()
        spec_display = str(spec_path)

    # Load existing plan if present (for incremental planning)
    existing_plan_content = ""
    if output_path.exists() and not force:
        # If --force not set, we still need existing content for incremental planning
        existing_plan_content = output_path.read_text()
    elif output_path.exists() and force:
        # With --force, start fresh but still read existing for context
        existing_plan_content = output_path.read_text()

    if output_path.exists() and not force:
        raise RuntimeError(
            f"Output file already exists: {output_path}. Use --force to overwrite."
        )

    generator = PlanGenerator(
        max_iterations=max_iterations,
        verbose=getattr(args, "verbose", False),
    )

    result = generator.generate(
        spec_content,
        spec_display,
        output_path,
        existing_plan_content=existing_plan_content,
    )

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

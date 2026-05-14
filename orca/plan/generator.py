"""Plan generator — create implementation plans from specs using LLM.

Iteratively generates and refines implementation plans until the task
structure stabilizes (hash unchanged for 2 consecutive iterations).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..utils.llm import LLMError, run_pi
from .schema import (
    Plan,
    PlanMetadata,
    Task,
    compute_hash,
    validate_format,
)


# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

# Minimum and maximum tasks per feature to guide granularity
MIN_TASKS_PER_FEATURE = 1
MAX_TASKS_PER_FEATURE = 15

# Stability threshold: number of consecutive iterations with same hash
STABILITY_THRESHOLD = 2

# Plan format instructions included in every prompt
PLAN_FORMAT_INSTRUCTIONS = """\
## Plan Format

Your response MUST be a valid implementation plan in this exact format:

### Header
```
# Implementation Plan

**Project:** <project_name>
**Spec:** <spec_path>
```

### Features Section
```
## Features

### FEAT-NNN: <feature description>

- [ ] TASK-NNN: <task description>
- [ ] TASK-NNN: <task description>
```

### Footer
```
---

**Plan Hash:** <sha256 of sorted task IDs, first 10 hex chars>
```

### Rules
- Feature IDs: `FEAT-001`, `FEAT-002`, etc.
- Task IDs: `TASK-001`, `TASK-002`, etc. (sequential across the entire plan)
- Each feature MUST have at least one task
- Use `- [ ]` (unchecked) for all tasks
- Include a `---` separator before the footer
- Compute the Plan Hash from the sorted list of all TASK-NNN IDs joined by `|`
- Do NOT include any text before `# Implementation Plan`
- Do NOT include any text after `**Plan Hash:** <hash>`
"""

GRANULARITY_GUIDANCE = """\
## Granularity Guidance

- Each feature should represent a cohesive, independently verifiable capability
- Each task should be a concrete, actionable step (not a vague goal)
- Prefer more features with fewer tasks over fewer features with many tasks
- Tasks should be small enough to implement in one focused session
- Include tasks for: setup, core logic, edge cases, testing, and integration
- Avoid tasks that are too broad (e.g., "implement everything") — break them down
"""

EDGE_CASE_GUIDANCE = """\
## Edge Cases to Consider

When creating the plan, ensure you include tasks for:
- Input validation and error handling
- Edge cases in user input (empty, null, oversized, malformed)
- Boundary conditions (zero, max values, single items)
- State transitions and consistency
- Concurrency or race conditions if applicable
- Resource cleanup and error recovery
- Security considerations (auth, authorization, injection)
- Performance implications of the implementation
- Data migration or backward compatibility if relevant
"""


class PlanGenerator:
    """Generate implementation plans from specs using LLM with iterative refinement."""

    def __init__(self, skill: str = "plan", max_iterations: int = 10):
        """Initialize generator with optional pi skill.

        Args:
            skill: Pi skill name to load for plan generation (default: "plan").
            max_iterations: Maximum refinement iterations before giving up.
        """
        self.skill = skill
        self.max_iterations = max_iterations

    def generate(self, spec_path: str, output_path: str | None = None) -> Plan:
        """Generate implementation plan from spec using LLM.

        Iteratively refines until plan is stable (hash matches for 2 iterations).

        Args:
            spec_path: Path to the spec file to generate a plan for.
            output_path: Optional path to save the final plan markdown.

        Returns:
            Parsed Plan object.

        Raises:
            FileNotFoundError: If spec file doesn't exist.
            LLMError: If LLM call fails.
            RuntimeError: If plan doesn't stabilize within max_iterations.
        """
        spec_file = Path(spec_path)
        if not spec_file.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_path}")

        spec_content = spec_file.read_text()
        project_name = spec_file.stem

        previous_hash: Optional[str] = None
        iterations_without_change = 0

        for iteration in range(1, self.max_iterations + 1):
            if iteration == 1:
                # First iteration: generate from scratch
                prompt = self._build_initial_prompt(spec_content)
                issues: list[str] = []
            else:
                # Subsequent iterations: refine based on gaps
                prompt = self._build_refinement_prompt(current_plan, issues)

            # Generate plan via LLM
            llm_output = self._generate_plan(prompt)

            # Extract and parse plan content
            plan_content = self._extract_plan_content(llm_output)
            current_plan = Plan.from_content(plan_content)

            # Compute hash for stability detection
            current_hash = self._compute_plan_hash(plan_content)

            # Check stability
            if previous_hash is not None and current_hash == previous_hash:
                iterations_without_change += 1
                if iterations_without_change >= STABILITY_THRESHOLD:
                    # Plan is stable
                    break
            else:
                iterations_without_change = 0

            previous_hash = current_hash

            # Detect gaps and issues for refinement
            issues = self._detect_plan_issues(current_plan, spec_content)

        else:
            raise RuntimeError(
                f"Plan did not stabilize after {self.max_iterations} iterations. "
                f"Last hash: {previous_hash}, issues: {issues}"
            )

        # Update plan hash in metadata
        current_plan.metadata.hash = current_hash

        # Save to output if requested
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(current_plan.to_markdown())

        return current_plan

    def _build_initial_prompt(self, spec_content: str) -> str:
        """Build prompt for initial plan generation.

        Args:
            spec_content: Raw content of the spec file.

        Returns:
            Prompt string for plan generation.
        """
        return f"""\
Create an implementation plan for the following spec.

## Spec Content

```
{spec_content}
```

## Plan Format

{PLAN_FORMAT_INSTRUCTIONS}

## Granularity Guidance

{GRANULARITY_GUIDANCE}

## Edge Cases to Consider

{EDGE_CASE_GUIDANCE}

## Instructions

1. Read the spec carefully and identify the core features needed
2. Break features into concrete, actionable tasks
3. Include edge cases, error handling, and validation
4. Compute the **Plan Hash** from your sorted task IDs (SHA-256, first 10 hex chars)
5. Output ONLY the plan markdown — no preamble, no explanation, no markdown code fences
"""

    def _build_refinement_prompt(
        self, current_plan: Plan, issues: list[str]
    ) -> str:
        """Build prompt for plan refinement.

        Args:
            current_plan: The current (unstable) plan.
            issues: List of detected gaps/issues to address.

        Returns:
            Prompt string for refinement.
        """
        plan_markdown = current_plan.to_markdown()

        issues_text = ""
        if issues:
            issues_text = "## Identified Gaps and Issues\n\n"
            for i, issue in enumerate(issues, 1):
                issues_text += f"{i}. {issue}\n"
            issues_text += "\nAddress these gaps in your refined plan.\n\n"

        return f"""\
The previous plan iteration did not fully address the spec. Refine it.

## Previous Plan

```
{plan_markdown}
```

{issues_text}## Plan Format

{PLAN_FORMAT_INSTRUCTIONS}

## Granularity Guidance

{GRANULARITY_GUIDANCE}

## Edge Cases to Consider

{EDGE_CASE_GUIDANCE}

## Instructions

1. Keep the same feature and task structure if it's correct
2. Add missing features, tasks, or edge cases to address the gaps above
3. Remove or merge tasks that are redundant
4. Compute the **Plan Hash** from your sorted task IDs (SHA-256, first 10 hex chars)
5. Output ONLY the plan markdown — no preamble, no explanation, no markdown code fences
"""

    def _generate_plan(self, prompt: str) -> str:
        """Call pi to generate plan text.

        Args:
            prompt: The prompt to send to pi.

        Returns:
            Raw output from pi.

        Raises:
            LLMError: If pi call fails.
        """
        return run_pi(prompt, skill=self.skill)

    def _extract_plan_content(self, llm_output: str) -> str:
        """Extract and validate plan markdown from LLM output.

        Looks for the plan in the output, handling markdown code fences
        and surrounding text.

        Args:
            llm_output: Raw output from pi.

        Returns:
            Extracted plan markdown content.

        Raises:
            ValueError: If no valid plan content found.
        """
        content = llm_output.strip()

        # Try to find plan within markdown code fences
        fence_pattern = re.compile(
            r"```(?:markdown)?\s*\n(.*?)```", re.DOTALL
        )
        match = fence_pattern.search(content)
        if match:
            content = match.group(1).strip()

        # Validate it looks like a plan
        if not content.startswith("# Implementation Plan"):
            # Try to find the plan header anywhere in the output
            header_match = re.search(
                r"(# Implementation Plan\n.*?)(?:\n\n---\n\n\*\*Plan Hash:\*\* \w+)",
                content,
                re.DOTALL,
            )
            if header_match:
                content = header_match.group(1).strip() + "\n---\n" + header_match.group(2).strip()
            else:
                raise ValueError(
                    "LLM output does not contain a valid implementation plan. "
                    f"Output preview: {content[:200]}..."
                )

        return content

    def _compute_plan_hash(self, content: str) -> str:
        """Compute hash for stability detection.

        Uses only task IDs for hashing to detect when the task list
        structure changes, not when descriptions change.

        Args:
            content: Plan markdown content.

        Returns:
            10-character hex hash of task IDs.
        """
        plan = Plan.from_content(content)
        return compute_hash(plan.get_all_tasks())

    def _detect_plan_issues(self, plan: Plan, spec_content: str) -> list[str]:
        """Detect gaps between the spec and the plan.

        Analyzes the plan against the spec to identify missing or
        insufficient coverage.

        Args:
            plan: The current plan to analyze.
            spec_content: Raw spec content for comparison.

        Returns:
            List of issue descriptions.
        """
        issues: list[str] = []

        # Check for features in spec that might be missing from plan
        # Look for high-level feature indicators in spec
        feature_indicators = self._extract_feature_candidates(spec_content)

        plan_feature_descriptions = {
            f.description.lower() for f in plan.features
        }

        for candidate in feature_indicators:
            # Check if any plan feature covers this candidate
            covered = False
            for pf in plan_feature_descriptions:
                if self._is_related(candidate, pf):
                    covered = True
                    break
            if not covered:
                issues.append(f"Spec mentions '{candidate}' but no corresponding feature in plan")

        # Check for too few tasks
        if plan.features:
            for feat in plan.features:
                if len(feat.tasks) < MIN_TASKS_PER_FEATURE:
                    issues.append(
                        f"Feature {feat.feature_id} has no tasks — "
                        "needs at least one task"
                    )

        # Check for overly broad tasks
        broad_task_keywords = [
            "implement everything",
            "handle all",
            "cover all",
            "do the",
            "set up the whole",
        ]
        for task in plan.get_all_tasks():
            desc_lower = task.description.lower()
            for keyword in broad_task_keywords:
                if keyword in desc_lower:
                    issues.append(
                        f"Task {task.task_id} is too broad: '{task.description}' — "
                        "break it into smaller, concrete steps"
                    )
                    break

        # Check for missing edge case coverage
        if "error" not in str(plan.get_all_tasks()).lower() and "edge case" not in spec_content.lower():
            # Spec likely has error/edge case requirements
            if any(
                kw in spec_content.lower()
                for kw in ["error", "exception", "failure", "invalid", "null", "empty"]
            ):
                issues.append(
                    "Plan may be missing error handling and edge case tasks — "
                    "spec contains error/edge case indicators"
                )

        return issues

    def _extract_feature_candidates(self, spec_content: str) -> list[str]:
        """Extract candidate feature descriptions from spec content.

        Looks for headings, bold text, and key phrases that indicate
        distinct features or capabilities.

        Args:
            spec_content: Raw spec content.

        Returns:
            List of candidate feature descriptions.
        """
        candidates: list[str] = []

        # Extract section headings (## or ### level)
        heading_pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
        for match in heading_pattern.finditer(spec_content):
            text = match.group(1).strip()
            if len(text) > 5 and len(text) < 120:
                candidates.append(text)

        # Extract bold phrases that look like feature names
        bold_pattern = re.compile(r"\*\*([^*]{10,80})\*\*")
        for match in bold_pattern.finditer(spec_content):
            text = match.group(1).strip()
            # Filter out common non-feature bold text
            if text.lower() not in (
                "required", "optional", "priority", "note", "important",
                "warning", "todo", "done", "status", "type",
            ):
                candidates.append(text)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_candidates: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique_candidates.append(c)

        return unique_candidates[:20]  # Limit to top 20 candidates

    @staticmethod
    def _is_related(candidate: str, plan_feature: str) -> bool:
        """Check if a spec candidate is related to a plan feature.

        Uses simple keyword overlap and substring matching.

        Args:
            candidate: Feature candidate from spec.
            plan_feature: Feature description from plan.

        Returns:
            True if they appear to be related.
        """
        cand_words = set(candidate.lower().split())
        feat_words = set(plan_feature.split())

        # Remove common stop words
        stop_words = {
            "the", "a", "an", "for", "and", "or", "not", "with", "in",
            "to", "of", "on", "at", "by", "is", "it", "this", "that",
            "from", "as", "be", "are", "was", "were", "have", "has",
            "had", "do", "does", "did", "will", "would", "can", "could",
            "should", "may", "might", "must", "shall", "to",
        }
        cand_words -= stop_words
        feat_words -= stop_words

        # Check keyword overlap
        overlap = cand_words & feat_words
        if len(overlap) >= 1:
            return True

        # Check substring (one contained in the other)
        if candidate.lower() in plan_feature or plan_feature in candidate.lower():
            return True

        # Check if most candidate words appear in feature
        if cand_words and len(cand_words & feat_words) / max(len(cand_words), 1) >= 0.5:
            return True

        return False

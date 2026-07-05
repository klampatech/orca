"""orca plan - Iteratively refine a markdown plan from spec file(s).

Uses an LLM as judge with two completion criteria:
1. LLM judge determines the plan is complete (satisfies all AC, edge cases,
   security, architectural considerations)
2. Hash of plan content matches across 2 consecutive iterations

The command runs up to max_iterations, producing an IMPLEMENTATION_PLAN.md
in the same directory as the primary spec file.

Supports multiple LLM harnesses:
- pi       (available via --harness pi)
- claude   (default as of this refactor; available via --harness claude)
- codex    (pass-through stub; available via --harness codex)
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import warnings
from pathlib import Path

# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_PI_SKILL = "plan"
DEFAULT_HARNESS = "claude"
VALID_HARNESSES = ["pi", "claude", "codex"]


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def _resolve_skill_path(skill_name: str) -> str | None:
    """Resolve a skill name to its path.

    Pi loads skills from:
    - ~/.pi/agent/skills/<name>
    - ~/.agents/skills/<name>
    - .pi/skills/<name> (cwd and ancestors)
    - .agents/skills/<name> (cwd and ancestors)

    Args:
        skill_name: Name of the skill (e.g., "plan" or "skill:plan")

    Returns:
        Resolved path to the skill directory, or None if not found.
    """
    # Strip "skill:" prefix if present
    name = skill_name
    if name.startswith("skill:"):
        name = name[6:]

    search_paths = [
        Path.cwd() / ".pi" / "skills" / name,
        Path.cwd() / ".pi" / "skills" / name / "SKILL.md",
        Path.cwd() / ".agents" / "skills" / name,
        Path.home() / ".pi" / "agent" / "skills" / name,
        Path.home() / ".agents" / "skills" / name,
    ]

    for path in search_paths:
        if path.exists():
            return str(path.parent if path.name == "SKILL.md" else path)
    return None


def _run_harness(harness: str, prompt: str, skill: str | None = None) -> str:
    """Dispatch to the appropriate LLM harness.

    Args:
        harness: One of "pi", "claude", "codex".
        prompt:  The prompt to send to the harness.
        skill:   pi skill name (only used when harness == "pi").

    Returns:
        The raw output from the harness.

    Raises:
        RuntimeError: If the harness binary is not found or fails.
    """
    if harness == "pi":
        return _run_pi(prompt, skill)
    elif harness == "claude":
        return _run_claude(prompt, skill)
    elif harness == "codex":
        return _run_codex(prompt, skill)
    else:
        raise ValueError(f"Unknown harness: {harness!r}. Valid: {VALID_HARNESSES}")


def _run_pi(prompt: str, skill: str | None = None) -> str:
    """Run pi with a prompt, optionally loading a skill.

    Args:
        prompt: The prompt to send to pi.
        skill: Optional skill name to load.

    Returns:
        The raw output from pi.

    Raises:
        RuntimeError: If pi is not found or fails.
    """
    pi_cmd = shutil.which("pi")
    if pi_cmd is None:
        raise RuntimeError(
            "pi CLI not found in PATH. Install it first:\n"
            "  npm install -g @badlogic/pi-coding-agent\n"
            "  # or follow instructions at https://github.com/badlogic/pi-mono"
        )

    cmd = [pi_cmd, "-p", prompt]
    if skill:
        skill_path = _resolve_skill_path(skill)
        if skill_path:
            cmd.extend(["--skill", skill_path])
        else:
            cmd.extend(["--skill", skill])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"pi exited with code {result.returncode}: {result.stderr[:500]}"
        )

    return result.stdout


def _run_claude(prompt: str, skill: str | None = None) -> str:
    """Run claude-code CLI in print mode with a prompt.

    Args:
        prompt: The prompt to send to claude.
        skill:  Ignored (claude-code skills are a different system from pi skills).

    Returns:
        The raw output from claude-code.

    Raises:
        RuntimeError: If claude is not found or fails.
    """
    claude_cmd = shutil.which("claude")
    if claude_cmd is None:
        raise RuntimeError(
            "claude CLI not found in PATH. Install it first:\n"
            "  npm install -g @anthropic-ai/claude-code\n"
            "  # or: npm install -g claude-code\n"
            "  # then authenticate: claude auth"
        )

    # Use -p - to read prompt from stdin, avoiding shell quoting issues
    # with very long prompts that would exceed argv limits.
    proc = subprocess.Popen(
        [claude_cmd, "-p", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError("claude timed out after 300 seconds")

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude exited with code {proc.returncode}: {stderr[:500]}"
        )

    return stdout


def _run_codex(prompt: str, skill: str | None = None) -> str:
    """Run codex CLI in print mode with a prompt (stub implementation).

    Args:
        prompt: The prompt to send to codex.
        skill:  Ignored.

    Returns:
        The raw output from codex.

    Raises:
        RuntimeError: If codex is not found or fails.
    """
    codex_cmd = shutil.which("codex")
    if codex_cmd is None:
        raise RuntimeError(
            "codex CLI not found in PATH. Install it first:\n"
            "  # OpenAI Codex: https://platform.openai.com/docs/codex\n"
            "  # Or use the official codex CLI package"
        )

    # codex CLI: `codex -p <prompt>` is typical
    cmd = [codex_cmd, "-p", prompt]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"codex exited with code {result.returncode}: {result.stderr[:500]}"
        )

    return result.stdout


def _compute_hash(content: str) -> str:
    """Compute SHA256 hash of content (first 12 chars)."""
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _is_valid_plan(content: str) -> bool:
    """Check if content looks like a valid IMPLEMENTATION_PLAN.md."""
    if not content:
        return False
    stripped = content.strip()
    # Must start with a markdown heading (plan header)
    if not stripped.startswith("#"):
        return False
    # Must contain "Implementation Plan" or at minimum feature/task markers
    if "FEAT-" not in content and "TASK-" not in content:
        return False
    return True


def _strip_markdown_fence(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) > 1:
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
    return text.strip()


def _build_plan_prompt(
    spec_contents: list[str],
    spec_names: list[str],
    mode: str,
    previous_plan: str | None = None,
    judge_notes: str | None = None,
) -> str:
    """Build the prompt for pi to generate or refine a plan.

    Args:
        spec_contents: List of spec file contents.
        spec_names: List of spec file names (for display).
        mode: "generate" or "refine".
        previous_plan: Previous plan content (if refining).
        judge_notes: Judge's notes on what's missing (if refining).

    Returns:
        The prompt string for pi.
    """
    parts = []

    # Header
    if mode == "generate":
        parts.append("You are generating an IMPLEMENTATION_PLAN.md from spec file(s).")
    else:
        parts.append("You are refining an IMPLEMENTATION_PLAN.md based on judge feedback.")

    parts.append("")
    parts.append("Load the `plan` skill first. It defines the plan format and rules.")
    parts.append("")

    # Spec files
    parts.append("## Spec Files")
    for name, content in zip(spec_names, spec_contents):
        parts.append(f"### {name}")
        parts.append(content)
        parts.append("")
    parts.append("")

    # Previous plan and judge notes (if refining)
    if previous_plan is not None:
        parts.append("## Current IMPLEMENTATION_PLAN.md (to be refined)")
        parts.append(previous_plan)
        parts.append("")

    if judge_notes:
        parts.append("## Judge Feedback")
        parts.append(judge_notes)
        parts.append("")
        parts.append("## Instructions")
        parts.append("The judge found the plan INCOMPLETE. You must produce a COMPLETE, ")
        parts.append("REVISED IMPLEMENTATION_PLAN.md that addresses ALL gaps listed above.")
        parts.append("")
        parts.append("CRITICAL: Output the COMPLETE revised IMPLEMENTATION_PLAN.md.")
        parts.append("Do NOT output a summary of changes. Do NOT output a list of changes.")
        parts.append("Output the full plan text, as if regenerating it from scratch,")
        parts.append("but with all gaps fixed.")
        parts.append("")
        parts.append("The plan must cover:")
        parts.append("- All acceptance criteria from the spec(s)")
        parts.append("- Edge cases and error conditions")
        parts.append("- Security considerations")
        parts.append("- Architectural decisions")
        parts.append("- Testing strategy")
    else:
        parts.append("")
        parts.append("Output ONLY the IMPLEMENTATION_PLAN.md content. No explanations, no preamble.")

    return "\n".join(parts)


def _build_judge_prompt(
    spec_contents: list[str],
    spec_names: list[str],
    current_plan: str,
) -> str:
    """Build the prompt for the LLM judge to evaluate plan completeness.

    Args:
        spec_contents: List of spec file contents.
        spec_names: List of spec file names (for display).
        current_plan: The current IMPLEMENTATION_PLAN.md content.

    Returns:
        The judge prompt string for pi.
    """
    parts = []

    parts.append("You are an expert judge evaluating whether an IMPLEMENTATION_PLAN.md "
                  "is complete and exhaustive.")
    parts.append("")
    parts.append("Study the spec file(s) and the current plan carefully.")
    parts.append("")
    parts.append("## Spec Files (what the plan must satisfy)")
    for name, content in zip(spec_names, spec_contents):
        parts.append(f"### {name}")
        parts.append(content)
        parts.append("")
    parts.append("")

    parts.append("## Current IMPLEMENTATION_PLAN.md (to be judged)")
    parts.append(current_plan)
    parts.append("")

    parts.append("""
## Your Task

Judge whether the plan above is COMPLETE and EXHAUSTIVE.

A complete plan must address ALL of the following:

1. **Acceptance Criteria Coverage** — Every AC from the spec(s) has a corresponding task
2. **Edge Cases** — Each feature has tasks covering boundary conditions, invalid inputs, error states
3. **Security** — Authentication, authorization, input validation, data protection
4. **Architecture** — Project structure, dependencies, infrastructure, scalability
5. **Testing** — Unit tests, integration tests, and how they map to features

For each area above, explicitly state whether the plan covers it adequately.

Then give your overall verdict:

**VERDICT: COMPLETE** — The plan is exhaustive and ready.
OR
**VERDICT: INCOMPLETE** — List every gap specifically (missing tasks, missing areas, weak areas).

Be strict. A plan that covers happy-path only is NOT complete.
""")

    return "\n".join(parts)


def _is_complete_verdict(output: str) -> tuple[bool, str]:
    """Parse judge output to determine if plan is complete.

    Args:
        output: The judge's output text.

    Returns:
        (is_complete, notes) where notes is the raw output for refinement.
    """
    output_upper = output.upper()
    if "**VERDICT: COMPLETE**" in output_upper or "VERDICT: COMPLETE" in output_upper:
        return True, output
    return False, output


# --------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------

def handle_plan(args) -> dict:
    """Generate an iteratively refined implementation plan from spec file(s).

    Args:
        args.specs: List of spec file paths.
        args.output: Override output path.
        args.max_iterations: Max plan loops.
        args.pi_skill: pi skill to use (pi harness only; no-op for claude/codex).
        args.harness: LLM harness to use ("pi", "claude", "codex").

    Returns:
        Result dict with iteration count and status.
    """
    spec_paths = [Path(p) for p in args.specs]
    for p in spec_paths:
        if not p.exists():
            raise RuntimeError(f"Spec file not found: {p}")

    # Determine output path
    if getattr(args, "output", None):
        output_path = Path(args.output)
    else:
        # Default: next to the first spec
        output_path = spec_paths[0].parent / "IMPLEMENTATION_PLAN.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Config
    max_iterations = getattr(args, "max_iterations", None) or DEFAULT_MAX_ITERATIONS
    pi_skill = getattr(args, "pi_skill", None) or DEFAULT_PI_SKILL
    harness = getattr(args, "harness", None) or DEFAULT_HARNESS

    if harness not in VALID_HARNESSES:
        raise ValueError(f"Invalid --harness value: {harness!r}. Valid: {VALID_HARNESSES}")

    # AC6: --pi-skill is only meaningful for pi harness
    if harness != "pi" and getattr(args, "pi_skill", None):
        warnings.warn(
            f"--pi-skill is only used when --harness pi. "
            f"Current harness is {harness}. Ignoring --pi-skill.",
            UserWarning,
        )

    # Read spec contents
    spec_names = [p.name for p in spec_paths]
    spec_contents = [p.read_text() for p in spec_paths]

    print(f"Planning from: {', '.join(spec_names)}")
    print(f"  Output: {output_path}")
    print(f"  Harness: {harness}")
    print(f"  Max iterations: {max_iterations}")
    if harness == "pi":
        print(f"  pi skill: {pi_skill}")
    else:
        print(f"  pi skill: (not used with {harness} harness)")
    print()

    # State for two completion criteria
    previous_hash: str | None = None
    current_hash: str | None = None
    previous_plan: str | None = None
    last_plan_content: str | None = None
    consecutive_hash_match = 0
    iteration = 0

    # Track all plans for reporting
    all_plans: list[dict] = []

    while iteration < max_iterations:
        iteration += 1

        # ----- Phase 1: Generate or refine plan -----
        mode = "generate" if iteration == 1 else "refine"

        if mode == "generate":
            print(f"[{iteration}/{max_iterations}] Generating initial plan...")
        else:
            print(f"[{iteration}/{max_iterations}] Refining plan (try {iteration - 1})...")

        try:
            # Build prompt
            prompt = _build_plan_prompt(
                spec_contents,
                spec_names,
                mode,
                previous_plan=last_plan_content,
                judge_notes=None if mode == "generate" else None,
            )

            # Use the selected harness; skill arg only meaningful for pi
            raw_output = _run_harness(harness, prompt, pi_skill if harness == "pi" else None)
            plan_content = _strip_markdown_fence(raw_output)

            if not plan_content:
                print(f"  ! {harness} returned empty output, retrying...")
                last_plan_content = None
                continue

            # Reject non-plan outputs (commentary, JSON, etc.)
            if not _is_valid_plan(plan_content):
                snippet = plan_content[:100].replace("\n", " ")
                print(f"  ! {harness} returned non-plan output, retrying...")
                print(f"    Got: {snippet}...")
                last_plan_content = None
                continue

            last_plan_content = plan_content
            current_hash = _compute_hash(plan_content)

            print(f"  Plan hash: {current_hash}")

            # Check hash stability (completion criterion 2)
            if previous_hash is not None and current_hash == previous_hash:
                consecutive_hash_match += 1
                print(f"  Hash match #{consecutive_hash_match}/2")
            else:
                consecutive_hash_match = 0
                print(f"  Hash changed, reset stability counter")

            previous_hash = current_hash

            # Write intermediate plan
            output_path.write_text(plan_content)

        except subprocess.TimeoutExpired:
            print(f"  ! {harness} timed out (300s)")
            continue
        except RuntimeError as e:
            print(f"  ! {harness} error: {e}")
            continue

        # ----- Phase 2: Judge the plan -----
        print(f"  Evaluating plan completeness...")

        try:
            judge_prompt = _build_judge_prompt(spec_contents, spec_names, plan_content)
            judge_output = _run_harness(harness, judge_prompt, pi_skill if harness == "pi" else None)

            is_complete, judge_notes = _is_complete_verdict(judge_output)

            # Truncate judge output for display
            judge_snippet = judge_output.strip()[:300]
            if len(judge_output) > 300:
                judge_snippet += "..."

            print(f"  Judge: {judge_snippet.replace(chr(10), ' ')}")

            # Record this iteration
            all_plans.append({
                "iteration": iteration,
                "hash": current_hash,
                "complete": is_complete,
                "consecutive_hash_match": consecutive_hash_match,
                "plan_snippet": plan_content[:200] + "..." if len(plan_content) > 200 else plan_content,
            })

            if is_complete and consecutive_hash_match >= 2:
                # Both criteria met
                print(f"")
                print(f"✓ Plan complete after {iteration} iteration(s)")
                print(f"  Reason: LLM judge says complete + hash stable ({current_hash})")
                print(f"  → {output_path}")
                return {
                    "command": "plan",
                    "status": "success",
                    "iterations": iteration,
                    "final_hash": current_hash,
                    "output_path": str(output_path),
                    "complete": True,
                    "hash_stable": True,
                    "harness": harness,
                    "all_plans": all_plans,
                }
            elif is_complete:
                print(f"  Judge says complete, but hash not yet stable ({consecutive_hash_match}/2)")
                print(f"  → Running one more iteration to confirm stability...")
                previous_plan = plan_content
                continue
            else:
                # Judge found gaps — refine
                print(f"  Judge found gaps, refining...")
                previous_plan = plan_content
                # Build refinement prompt with judge feedback
                refine_prompt = _build_plan_prompt(
                    spec_contents,
                    spec_names,
                    "refine",
                    previous_plan=plan_content,
                    judge_notes=judge_notes,
                )
                # Run refinement in next loop iteration
                continue

        except subprocess.TimeoutExpired:
            print(f"  ! Judge evaluation timed out")
            previous_plan = plan_content
            continue
        except RuntimeError as e:
            print(f"  ! Judge error: {e}")
            previous_plan = plan_content
            continue

    # Max iterations reached
    print(f"")
    print(f"✗ Max iterations ({max_iterations}) reached.")

    # If we have a plan, consider it partial success
    if last_plan_content:
        print(f"  Last plan written to {output_path}")
        # Check if the last hash matched the previous (partial stability)
        return {
            "command": "plan",
            "status": "max_iterations",
            "iterations": iteration,
            "final_hash": current_hash,
            "output_path": str(output_path),
            "complete": False,
            "hash_stable": consecutive_hash_match >= 2,
            "harness": harness,
            "all_plans": all_plans,
        }

    return {
        "command": "plan",
        "status": "error",
        "iterations": iteration,
        "output_path": str(output_path),
        "harness": harness,
    }


def format_plan_human(result: dict) -> str:
    """Format plan result for human display."""
    status = result["status"]
    harness = result.get("harness", "unknown")

    if status == "success":
        lines = [
            f"✓ Plan generated in {result['iterations']} iteration(s) using {harness}",
            f"  Output: {result['output_path']}",
            f"  Hash: {result['final_hash']}",
            f"  LLM judge: COMPLETE",
            f"  Hash stable: YES (2 consecutive matches)",
        ]
        if result.get("all_plans"):
            lines.append("")
            lines.append("Plan evolution:")
            for p in result["all_plans"]:
                complete_mark = "✓" if p["complete"] else "○"
                lines.append(f"  iter {p['iteration']}: {complete_mark} hash={p['hash']} match={p['consecutive_hash_match']}")
        return "\n".join(lines)

    elif status == "max_iterations":
        lines = [
            f"✗ Max iterations reached ({result['iterations']}) using {harness}",
            f"  Output: {result['output_path']}",
            f"  Final hash: {result.get('final_hash', 'unknown')}",
        ]
        if result.get("all_plans"):
            lines.append("")
            lines.append("Plan evolution:")
            for p in result["all_plans"]:
                complete_mark = "✓" if p["complete"] else "○"
                lines.append(f"  iter {p['iteration']}: {complete_mark} hash={p['hash']} match={p['consecutive_hash_match']}")
        return "\n".join(lines)

    else:
        return f"? Unknown status: {status}"

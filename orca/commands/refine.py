"""orch refine - Iteratively refine a raw spec into valid spec.ir.json.

Uses pi + custom skill to generate the IR, then validates it. If invalid,
feeds validation errors back to pi and tries again. Stops on: valid output,
stable hash (2 consecutive same), or max iterations reached.

Logs refinement events to .orch/logs/ for debugging and audit trail.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from ..utils.validator import SpecIRValidator, strip_markdown_json
from ..utils.logging import (
    log_refine_start,
    log_refine_complete,
    log_refine_error,
    log_inference,
)


# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

DEFAULT_MAX_ITERATIONS = 5
DEFAULT_PI_SKILL = "ir-spec-generator"


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
        skill_name: Name of the skill (e.g., "ir" or "skill:ir")

    Returns:
        Resolved path to the skill directory, or None if not found.
    """

    # Strip "skill:" prefix if present (e.g., "skill:ir" -> "ir")
    name = skill_name
    if name.startswith("skill:"):
        name = name[6:]

    # Search paths (in order of precedence)
    search_paths = [
        Path.cwd() / ".pi" / "skills" / name,  # ./pi/skills/ir
        Path.cwd() / ".pi" / "skills" / name / "SKILL.md",  # ./pi/skills/ir/SKILL.md
        Path.cwd() / ".agents" / "skills" / name,
        Path.home() / ".pi" / "agent" / "skills" / name,
        Path.home() / ".agents" / "skills" / name,
    ]

    for path in search_paths:
        if path.exists():
            return str(path.parent if path.name == "SKILL.md" else path)

    return None


def _run_pi(prompt: str, skill: str | None = None) -> str:
    """Run pi with a prompt, optionally loading a skill.

    Args:
        prompt: The prompt to send to pi.
        skill: Optional skill name to load (e.g., "ir" or "skill:ir").

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
            # Skill not found locally, try passing as-is (might be in pi's default locations)
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


def _compute_hash(content: str) -> str:
    """Compute md5 hash of content."""
    return hashlib.md5(content.encode()).hexdigest()


def _build_refine_prompt(
    spec_content: str,
    skill: str | None,
    previous_ir: str | None = None,
    errors: list | None = None,
) -> str:
    """Build the prompt for pi to generate/refine spec.ir.json.

    Args:
        spec_content: The raw spec content.
        skill: Skill name to load.
        previous_ir: Previous IR content (if refining after errors).
        errors: List of validation errors (if refining).

    Returns:
        The prompt string for pi.
    """
    parts = []

    # Intro
    if previous_ir is None:
        parts.append("You are generating a structured IR from a raw spec.")
    else:
        parts.append("You are refining a structured IR to fix validation errors.")

    parts.append("")

    # Load IR skill instruction
    if skill:
        parts.append(
            f"Load the `{skill}` skill first. It defines the IR format and rules."
        )

    parts.append("")

    # Schema path for reference
    schema_path = Path(__file__).parent.parent / "data" / "spec-schema-v2.json"
    if schema_path.exists():
        parts.append(f"Schema reference: {schema_path}")
    else:
        parts.append("Schema: Use spec-schema-v2.json from your skill.")

    parts.append("")

    # ANTI-DRIFT REMINDER (critical - even with skill, reinforce this)
    parts.append("### CRITICAL: PRESERVE ALL SOURCE CONTENT ###")
    parts.append("Every section from the source spec MUST appear in the output.")
    parts.append(
        "The schema fields are a semantic skeleton for task decomposition, NOT a content filter."
    )
    parts.append("Content that doesn't fit a specific field MUST go into:")
    parts.append("  - Feature descriptions (for prose, details, architecture)")
    parts.append("  - Edge cases (for discrete items: errors, tasks, flags)")
    parts.append("  - Technical constraints (for file structure, dependencies)")
    parts.append("DO NOT: summarize, truncate, drop, or omit any source content.")
    parts.append("")

    # Previous IR and errors (if refining)
    if previous_ir is not None:
        parts.append("## Current IR (fix the issues below)")
        parts.append(previous_ir)
        parts.append("")

    if errors:
        parts.append("## Validation Errors (must be fixed)")
        for e in errors:
            field = getattr(e, "field", "unknown")
            msg = getattr(e, "message", str(e))
            parts.append(f"- {field}: {msg}")
        parts.append("")
        parts.append("Fix these errors and produce a new valid spec.ir.json.")
    else:
        # Fresh generation
        parts.append("## Raw Spec")
        parts.append(spec_content)
        parts.append("")
        parts.append(
            "Generate a COMPLETE spec.ir.json that preserves ALL content from the source."
        )
        parts.append(
            "Each numbered section in the source must have corresponding representation."
        )

    parts.append("")
    parts.append("Output ONLY the JSON (no markdown, no explanation).")

    return "\n".join(parts)


# --------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------


def handle_refine(args) -> dict:
    """Refine a raw spec into valid spec.ir.json.

    Args:
        args.spec: Path to raw spec file.
        args.output: Override output path.
        args.max_iterations: Max refine loops.
        args.pi_skill: pi skill to use.

    Returns:
        Result dict with iteration count and status.
    """
    spec_path = Path(args.spec)
    if not spec_path.exists():
        raise RuntimeError(f"Spec file not found: {spec_path}")

    # Determine output path
    if getattr(args, "output", None):
        output_path = Path(args.output)
        # Create parent directories if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_path = spec_path.parent / "spec.ir.json"

    # Config
    max_iterations = getattr(args, "max_iterations", None) or DEFAULT_MAX_ITERATIONS
    pi_skill = getattr(args, "pi_skill", None) or DEFAULT_PI_SKILL

    # Read raw spec
    spec_content = spec_path.read_text()

    # Validator
    validator = SpecIRValidator()

    # State
    previous_hash = None  # Previous valid hash (for display)
    first_valid_hash = None  # First successful valid hash (stability baseline)
    current_hash = None
    iteration = 0
    last_errors: list | None = None
    last_ir_content: str | None = None

    print(f"Refining {spec_path.name} → {output_path.name}")
    print(f"  Max iterations: {max_iterations}")
    print(f"  pi skill: {pi_skill}")
    print()

    # Log refinement start
    log_refine_start(str(spec_path), max_iterations)

    while iteration < max_iterations:
        iteration += 1

        print(f"[{iteration}/{max_iterations}] Calling pi...")

        try:
            # Build prompt
            if iteration == 1:
                prompt = _build_refine_prompt(spec_content, pi_skill, None, None)
            else:
                prompt = _build_refine_prompt(
                    spec_content, pi_skill, last_ir_content, last_errors
                )

            # Run pi with timing
            infer_start = time.time()
            raw_output = _run_pi(prompt, pi_skill)
            infer_duration_ms = int((time.time() - infer_start) * 1000)

            # Log inference
            log_inference(
                prompt=prompt,
                response=raw_output,
                duration_ms=infer_duration_ms,
                success=True,
            )

            # Strip markdown code blocks if present
            ir_content = strip_markdown_json(raw_output)

            # Compute hash (for stability tracking, only on valid JSON)
            current_hash = _compute_hash(ir_content)

            # Validate
            try:
                ir_data = json.loads(ir_content)
            except json.JSONDecodeError as e:
                print(f"  ✗ Invalid JSON: {e}")
                last_errors = [{"field": "root", "message": f"Invalid JSON: {e}"}]
                last_ir_content = ir_content[:500]  # Truncate for prompt
                # Don't update previous_hash on invalid output - stability should only track valid outputs
                continue

            valid, errors = validator.validate(ir_data)

            if valid:
                print("  ✓ Valid spec.ir.json")

                # First valid output - establish baseline
                if first_valid_hash is None:
                    first_valid_hash = current_hash
                    previous_hash = current_hash
                    print(f"  Hash: {current_hash[:12]}... (baseline set)")
                    print(f"  first_valid_hash={first_valid_hash[:12]}...")
                    # Write output, but continue to confirm stability
                    output_path.write_text(ir_content)
                    print(f"  → Written to {output_path}")
                    print("  → Awaiting confirmation in next iteration...")
                    continue

                # Subsequent valid output - check stability against first valid
                print(f"  Hash: {current_hash[:12]}...")
                print(f"  Comparing to baseline: {first_valid_hash[:12]}...")
                if current_hash == first_valid_hash:
                    print("  → Output stable (hash unchanged)")
                    print(f"  → Written to {output_path}")

                    # Log successful completion
                    log_refine_complete(
                        spec_path=str(spec_path),
                        iterations=iteration,
                        final_hash=current_hash,
                        stable=True,
                        output_path=str(output_path),
                    )

                    return {
                        "command": "refine",
                        "status": "success",
                        "iterations": iteration,
                        "final_hash": current_hash,
                        "output_path": str(output_path),
                        "stable": True,
                    }
                else:
                    print("  → Hash changed! Resetting baseline.")
                    previous_hash = current_hash
                    first_valid_hash = current_hash  # Reset baseline
                    output_path.write_text(ir_content)
                    print(f"  → Written to {output_path}")
                    print("  → Awaiting confirmation in next iteration...")
                    continue
            else:
                print(f"  ✗ {len(errors)} validation error(s)")
                for err in errors[:5]:
                    print(f"     - {err.field}: {err.message}")
                if len(errors) > 5:
                    print(f"     ... and {len(errors) - 5} more")

                last_errors = errors
                last_ir_content = ir_content[:2000]  # Truncate for prompt

        except subprocess.TimeoutExpired:
            print("  ✗ pi timed out (300s)")
            last_errors = [{"field": "pi", "message": "pi timed out after 300 seconds"}]
            log_inference(
                prompt=prompt,
                response="",
                duration_ms=300000,
                success=False,
                error="pi timed out after 300 seconds",
            )
            continue

        except RuntimeError as e:
            log_refine_error(str(spec_path), str(e))
            raise RuntimeError(f"pi error: {e}")

    # Max iterations reached
    print(f"\n✗ Max iterations ({max_iterations}) reached.")
    print(f"  Final output not written to {output_path}")

    # Log max iterations reached
    log_refine_complete(
        spec_path=str(spec_path),
        iterations=iteration,
        final_hash=current_hash or "unknown",
        stable=False,
        output_path=None,
    )

    # Try to write last known content anyway
    if last_ir_content:
        print(f"  (Last attempt written to {output_path}.remove if needed)")
        # Don't overwrite - leave it for manual review

    return {
        "command": "refine",
        "status": "max_iterations",
        "iterations": iteration,
        "final_hash": current_hash,
        "output_path": str(output_path),
        "stable": previous_hash is not None and current_hash == previous_hash,
        "errors": [
            {"field": err.field, "message": err.message} for err in (last_errors or [])
        ],
    }


def format_refine_human(result: dict) -> str:
    status = result["status"]

    if status == "success":
        return (
            f"✓ Refined spec in {result['iterations']} iteration(s)\n"
            f"  Output: {result['output_path']}\n"
            f"  Hash: {result['final_hash'][:12]}..."
        )

    elif status == "max_iterations":
        lines = [
            f"✗ Max iterations reached ({result['iterations']})",
            f"  Final hash: {result.get('final_hash', 'unknown')[:12]}...",
        ]
        if result.get("stable"):
            lines.append("  Note: Output was stable (hash unchanged)")
        lines.append("")
        if result.get("errors"):
            lines.append("Remaining validation errors:")
            for e in result["errors"][:10]:
                lines.append(f"  - {e['field']}: {e['message']}")
        lines.append("")
        lines.append("Manual review needed. Check the last attempt at:")
        lines.append(f"  {result['output_path']}")
        return "\n".join(lines)

    else:
        return f"? Unknown status: {status}"

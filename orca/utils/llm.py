"""Shared LLM helpers for Orca commands.

Provides utilities for running pi with prompts, skill resolution, and
common LLM interaction patterns.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


# --------------------------------------------------------------------
# Skill resolution
# --------------------------------------------------------------------


def resolve_skill_path(skill_name: str) -> str | None:
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


# --------------------------------------------------------------------
# LLM execution
# --------------------------------------------------------------------


class LLMError(RuntimeError):
    """Raised when LLM execution fails."""

    pass


def run_pi(
    prompt: str,
    skill: str | None = None,
    timeout: int = 180,
) -> str:
    """Run pi with a prompt, optionally loading a skill.

    Args:
        prompt: The prompt to send to pi.
        skill: Optional skill name to load (e.g., "ir" or "skill:ir").
        timeout: Timeout in seconds (default: 180). Reduced from 300s
                 to avoid long waits when model is stuck.

    Returns:
        The raw output from pi.

    Raises:
        LLMError: If pi is not found or fails.
    """
    # Append mandatory constraints to prevent file creation
    constraints = """

    ## MANDATORY SAFETY CONSTRAINTS
    - Do NOT create, write, or modify any files
    - Do NOT run any commands or scripts
    - Do NOT generate example code or helper scripts
    - Your ONLY output should be text responses
    """
    constrained_prompt = prompt + constraints

    pi_cmd = shutil.which("pi")
    if pi_cmd is None:
        raise LLMError(
            "pi CLI not found in PATH. Install it first:\n"
            "  npm install -g @badlogic/pi-coding-agent\n"
            "  # or follow instructions at https://github.com/badlogic/pi-mono"
        )

    cmd = [pi_cmd, "-p", constrained_prompt]
    if skill:
        skill_path = resolve_skill_path(skill)
        if skill_path:
            cmd.extend(["--skill", skill_path])
        else:
            # Skill not found locally, try passing as-is
            cmd.extend(["--skill", skill])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise LLMError(f"pi timed out after {timeout} seconds")

    if result.returncode != 0:
        raise LLMError(f"pi exited with code {result.returncode}: {result.stderr[:500]}")

    return result.stdout


def run_pi_compact(
    prompt: str,
    skill: str | None = None,
    timeout: int = 180,
) -> str:
    """Run pi with a compact prompt variant for large JSON outputs.

    This variant adds extra instructions for compact/minified JSON output
    to avoid truncation when generating large specs.

    Args:
        prompt: The prompt to send to pi.
        skill: Optional skill name to load.
        timeout: Timeout in seconds (default: 180).

    Returns:
        The raw output from pi.

    Raises:
        LLMError: If pi is not found or fails.
    """
    # Compact output suffix - ask for minified JSON
    compact_suffix = """

    ## COMPACT OUTPUT REQUIREMENT
    Use MINIMAL whitespace in JSON output:
    - No indentation between array/object elements
    - No extra spaces or line breaks unless required
    - Use separators: (",", ":")
    This prevents truncation of large JSON outputs.
    """
    compact_prompt = prompt + compact_suffix
    return run_pi(compact_prompt, skill, timeout)


# --------------------------------------------------------------------
# Inference logging (if needed by commands)
# --------------------------------------------------------------------


def log_inference(
    prompt: str,
    response: str,
    duration_ms: int,
    success: bool,
    error: str | None = None,
) -> None:
    """Log an LLM inference call.

    This is a placeholder for commands that want to log inference events.
    The actual logging is typically done by individual commands that have
    access to their own logging setup.

    Args:
        prompt: The prompt sent to the LLM.
        response: The raw response from the LLM.
        duration_ms: Duration of the inference in milliseconds.
        success: Whether the inference succeeded.
        error: Optional error message if success is False.
    """
    # Placeholder - actual logging is command-specific
    pass

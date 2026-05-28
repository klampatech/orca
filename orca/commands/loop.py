"""Spawn Ralph loops — inline in current terminal or in new windows.

Logs loop events, task operations, and terminal output to .orch/logs/ for debugging.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import json
import shutil
import subprocess
import threading

from ..utils.logging import (
    log_loop_start,
    log_loop_end,
    log_loop_error,
    log_task_claim,
    log_task_complete,
    log_task_fail,
    log_inference,
    log_terminal_output,
)
from ..utils.spinner import WhaleSpinner


ORCA_CMD: list[str] = [shutil.which("orca") or "orca"]
PI_CMD: str | None = shutil.which("pi")

# Default model for pi invocations
DEFAULT_MODEL: str = "minimax/MiniMax-M2.7"


def _debug(verbose: bool, *args) -> None:
    """Print debug message with timestamp if verbose mode is enabled."""
    if verbose:
        from ..utils.time import utcnow
        ts = utcnow()[11:19]  # Get HH:MM:SS from ISO timestamp
        parts = " ".join(str(a) for a in args)
        print(f"[loop:{ts}] {parts}")


def _format_work_result(result_text: str, max_lines: int = 20) -> str:
    """Format pi's work result into a clean bulleted summary.

    Extracts key bullet points from markdown-formatted output.
    Falls back to first 500 chars if parsing fails.
    """
    if not result_text:
        return "(no output)"

    lines = result_text.strip().split("\n")

    # Extract bullet points, short paragraphs, and headers
    summary_lines: list[str] = []
    in_bullet_section = False

    for line in lines:
        stripped = line.strip()

        # Skip very long lines (probably code blocks)
        if len(stripped) > 120:
            continue

        # Capture bullet points
        if stripped.startswith(("- ", "• ", "* ")):
            text = stripped[2:].strip()
            if text and not text.startswith("```"):
                summary_lines.append(f"  • {text}")
                in_bullet_section = True

        # Capture numbered lists
        elif stripped and stripped[0].isdigit() and ". " in stripped[:5]:
            summary_lines.append(f"  {stripped}")

        # Capture short headers (but not the main title)
        elif stripped.startswith("### "):
            # Skip subsection headers, they're noise
            continue

        # Capture short non-bullet paragraphs (one-liners)
        elif stripped and not stripped.startswith("#") and not stripped.startswith("```") and len(stripped) > 15 and len(stripped) < 100:
            if in_bullet_section or len(summary_lines) == 0:
                summary_lines.append(f"  • {stripped}")
                in_bullet_section = True
            else:
                # Separate sections with a dash
                if summary_lines and not summary_lines[-1].startswith("  ---"):
                    summary_lines.append("  ---")
                summary_lines.append(f"  • {stripped}")

        else:
            in_bullet_section = False

    # Deduplicate consecutive bullets with same content
    cleaned: list[str] = []
    for line in summary_lines:
        if not cleaned or line != cleaned[-1]:
            cleaned.append(line)

    # Limit to max_lines
    if len(cleaned) > max_lines:
        cleaned = cleaned[:max_lines] + [f"  ... (+{len(cleaned) - max_lines} more lines)"]

    if not cleaned:
        # Fallback: just show first 500 chars
        return result_text.strip()[:500]

    return "\n".join(cleaned)


def _claim_task() -> str | None:
    """Claim a task via the orca CLI. Returns task_id or None."""
    result = subprocess.run(
        ORCA_CMD + ["--json", "claim"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        task_id = data.get("task_id")
        if task_id and task_id != "null":
            return task_id
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _get_task_info(task_id: str) -> dict | None:
    """Get full task info via orca info."""
    result = subprocess.run(
        ORCA_CMD + ["--json", "info", task_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def _run_pi(prompt: str, timeout: int | None = None, verbose: bool = False, model: str | None = None) -> str:
    """Pipe a prompt to pi -p, return the result text.

    Also forks the inference for debugging.

    Args:
        prompt: The prompt to send to pi.
        timeout: Maximum seconds to wait (None = unlimited).
        verbose: If True, print extra debugging info.
        model: Model to use (default: minimax/MiniMax-M2.7).
    """
    if PI_CMD is None:
        raise RuntimeError("pi CLI not found in PATH")

    cmd: list[str] = [PI_CMD]
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["-p", prompt])

    _debug(verbose, "pi command:", " ".join(cmd[:5]), "...")
    _debug(verbose, "prompt chars:", len(prompt))

    start_time = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    duration_ms = int((time.time() - start_time) * 1000)

    # Log terminal output
    log_terminal_output(
        source="pi",
        command=" ".join(cmd),
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
        duration_ms=duration_ms,
    )

    if result.returncode != 0:
        # Always log inference on failure so logs capture the context
        log_inference(
            prompt=prompt,
            response=f"FAILED: {result.stderr[:1000]}",
            duration_ms=duration_ms,
            success=False,
        )
        _debug(verbose, "pi FAILED exit_code=", result.returncode)
        _debug(verbose, "pi stderr:", result.stderr[:500])
        _debug(verbose, "pi stdout:", result.stdout[:500])
        raise RuntimeError(
            f"pi exited with code {result.returncode}: {result.stderr[:500]}"
        )

    return result.stdout.strip()


def _run_tests(timeout: int = 120) -> tuple[bool, str]:
    """Run project tests and return (success, output).

    Detects project type and runs appropriate test command:
    - Node.js (package.json): npm test
    - Python (pytest, pyproject.toml, setup.py): python -m pytest
    - Go (go.mod): go test
    - Ruby (Gemfile): bundle exec rspec

    Also logs the test output.

    Args:
        timeout: Maximum seconds to wait for tests (default: 120).
    """
    cwd = Path.cwd()
    start_time = time.time()

    # Detect Node.js project
    if (cwd / "package.json").exists():
        result = subprocess.run(
            ["npm", "test"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        success = result.returncode == 0
        output = result.stdout[:3000] if result.stdout else result.stderr[:3000]

        log_terminal_output(
            source="npm",
            command="npm test",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            duration_ms=duration_ms,
        )

        return success, output

    # Detect Python project
    has_pyproject = (cwd / "pyproject.toml").exists()
    has_setup = (cwd / "setup.py").exists()
    has_requirements = (cwd / "requirements.txt").exists()

    if has_pyproject or has_setup or has_requirements:
        python_cmd = shutil.which("python3") or shutil.which("python") or "python"
        python_cmd_list: list[str] = [python_cmd]
        result = subprocess.run(
            python_cmd_list + ["-m", "pytest", "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        success = result.returncode == 0
        output = result.stdout[:2000] if result.stdout else result.stderr[:2000]

        log_terminal_output(
            source="pytest",
            command=f"{' '.join(python_cmd_list)} -m pytest -v --tb=short",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            duration_ms=duration_ms,
        )

        return success, output

    # Detect Go project
    if (cwd / "go.mod").exists():
        result = subprocess.run(
            ["go", "test", "./..."],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        success = result.returncode == 0
        output = result.stdout[:2000] if result.stdout else result.stderr[:2000]

        log_terminal_output(
            source="go",
            command="go test ./...",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            duration_ms=duration_ms,
        )

        return success, output

    # Detect Ruby project (Rails or RSpec)
    if (cwd / "Gemfile").exists():
        result = subprocess.run(
            ["bundle", "exec", "rspec"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        success = result.returncode == 0
        output = result.stdout[:2000] if result.stdout else result.stderr[:2000]

        log_terminal_output(
            source="rspec",
            command="bundle exec rspec",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            duration_ms=duration_ms,
        )

        return success, output

    # No known project type detected
    return (
        False,
        "No test runner detected (no package.json, pyproject.toml, go.mod, or Gemfile found)",
    )


def _send_heartbeat(task_id: str, loop_id: str, stop_event: threading.Event) -> None:
    """Send heartbeats for a task run until stop_event is set."""
    while not stop_event.wait(30):
        result = subprocess.run(
            ORCA_CMD + ["heartbeat", task_id],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            break


def _do_work(
    task_id: str,
    description: str,
    spec_path: str | None,
    loop_id: str,
    pi_timeout: int | None = None,
    verbose: bool = False,
    ir_snippet: str | None = None,
    parent_id: str | None = None,
    test_timeout: int = 120,
    no_verify: bool = False,
) -> str:
    """Run pi to implement the given task, validate with tests. Returns result summary.

    Logs the inference for debugging.

    Args:
        task_id: The task ID being worked on (claimed).
        description: Task description.
        spec_path: Optional path to spec file.
        loop_id: The loop ID.
        pi_timeout: Timeout for pi in seconds (None = unlimited).
        verbose: If True, print extra debug info.
        ir_snippet: Optional JSON IR context for IR-based tasks.
        parent_id: Optional parent task ID for hierarchy context.
        test_timeout: Timeout for tests in seconds (default: 120).
        no_verify: If True, skip test verification entirely.
    """
    start_time = time.time()

    # Build a FOCUSED prompt for the claimed task — no plan reading, no "choose what to do"
    # The human/decomposer already decided what this task is. This loop implements ONLY this task.
    prompt_parts = [
        "You are Orca — an autonomous AI coding agent.\n",
        "Work in the current directory.\n",
    ]

    # CLAIMED TASK — this is the only work to do
    prompt_parts.extend([
        "## Claimed Task",
        f"Task ID: {task_id}",
        f"Description: {description}",
        "",
    ])

    # IR context if available (contains rich feature/AC/edge-case details)
    if ir_snippet:
        prompt_parts.extend([
            "## Task Context (from decomposition)",
            ir_snippet,
            "",
        ])

    # Spec reference
    if spec_path:
        prompt_parts.extend([
            "## Spec Reference",
            f"This task is derived from: {spec_path}",
            "",
        ])

    # Parent context if this is a sub-task
    if parent_id:
        prompt_parts.extend([
            "## Parent Task Context",
            f"This task has parent: {parent_id}",
            "",
        ])

    # Focused instructions — implement THIS task only
    prompt_parts.extend([
        "## Instructions",
        "",
        "1. IMPLEMENT ONLY THIS TASK. Do not work on other tasks or items in the plan.",
        "2. Search the codebase to understand existing structure before implementing.",
        "3. Use parallel subagents for searches/reads (up to 500 Sonnet), only 1 Sonnet for build/tests.",
        "4. Use Opus for complex reasoning (debugging, architectural decisions).",
        "5. When implemented, run the relevant tests.",
        "6. If you discover prerequisite work that blocks this task, note it and do minimal work to unblock — but DO NOT wander into other tasks.",
        "7. When tests pass, `git add -A` then `git commit` with a message describing the changes. After the commit, `git push`.",
        "8. If you discover issues, document them — but focus on completing THIS task.",
        "",
        "## Important Rules",
        "- You own this task. Others may claim adjacent work. Stay focused on your task ID.",
        "- Do NOT read IMPLEMENTATION_PLAN.md to decide what to work on — that decision is already made (this is your assigned task).",
        "- If you notice bugs unrelated to this task, document them but don't fix them unless they block your work.",
        "",
    ])

    prompt_parts.append(
        "Return a brief summary of what you did, including test results."
    )

    test_first_prompt = "\n".join(prompt_parts)

    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_send_heartbeat, args=(task_id, loop_id, stop_heartbeat), daemon=True
    )
    heartbeat_thread.start()

    print("[loop] Starting pi...")

    result_text = ""
    # Log inference start
    infer_start = time.time()
    try:
        with WhaleSpinner("Orca is coding", interval=0.12):
            result_text = _run_pi(test_first_prompt, timeout=pi_timeout, verbose=verbose, model=DEFAULT_MODEL)
        infer_duration_ms = int((time.time() - infer_start) * 1000)

        # Log inference completion
        log_inference(
            prompt=test_first_prompt,
            response=result_text,
            duration_ms=infer_duration_ms,
            success=True,
        )

        print("[loop] Work summary:")
        summary = _format_work_result(result_text)
        for line in summary.split("\n"):
            print(f"  {line}")

        # Run validation tests (unless skipped)
        if no_verify:
            print("[loop] Tests: SKIPPED (--no-verify)")
        else:
            print(f"[loop] Running validation tests (timeout: {test_timeout}s)...")
            try:
                tests_passed, test_output = _run_tests(timeout=test_timeout)
                print(f"[loop] Tests: {'PASSED' if tests_passed else 'FAILED'}")
                if not tests_passed:
                    raise RuntimeError(f"Tests failed:\n{test_output}")
            except subprocess.TimeoutExpired:
                print(f"[loop] Tests: TIMEOUT after {test_timeout}s")
                raise RuntimeError(f"Tests timed out after {test_timeout}s")
    except KeyboardInterrupt:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=5)
        print("\n[loop] Interrupted by user — exiting gracefully")
        raise
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=5)

    work_duration = time.time() - start_time

    # Log task completion
    log_task_complete(
        task_id=task_id,
        loop_id=loop_id,
        duration_seconds=work_duration,
        exit_status=0,
    )

    return result_text


def _complete_task(task_id: str, result_text: str = "Done") -> None:
    """Mark a task as completed."""
    cmd = ORCA_CMD + ["--json", "complete", task_id, "--result", result_text]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[loop] ERROR: complete failed (exit {result.returncode}): {result.stderr[:200]}"
        )
    else:
        print(f"[loop] Completed {task_id}")


def _fail_task(task_id: str, error_text: str = "Unknown error") -> None:
    """Mark a task as failed."""
    cmd = ORCA_CMD + ["--json", "fail", task_id, "--error", error_text[:500]]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[loop] ERROR: fail failed (exit {result.returncode}): {result.stderr[:200]}"
        )
    else:
        print(f"[loop] Failed {task_id}: {error_text[:100]}")


def handle_loop(args) -> dict:
    """Run a Ralph loop inline in the current terminal.

    Blocks forever until Ctrl+C. Each invocation uses a fresh UUID as loop ID.
    A --claim-only flag claims one task, completes it, and exits immediately.

    Logs loop events to .orch/logs/.
    """
    loop_id = str(uuid.uuid4())
    start_time = time.time()
    tasks_processed = 0

    print(f"[loop] Starting Ralph loop with ID: {loop_id}")

    # Log loop start
    log_loop_start(loop_id)

    claim_only: bool = getattr(args, "claim_only", False)
    pi_timeout: int | None = getattr(args, "pi_timeout", None)
    verbose: bool = getattr(args, "verbose", False)
    test_timeout: int = getattr(args, "test_timeout", 120)
    no_verify: bool = getattr(args, "no_verify", False)
    task_id = _claim_task()

    if task_id is None:
        if claim_only:
            print("[loop] No tasks available — exiting (claim-only mode)")
            return {
                "command": "loop",
                "status": "success",
                "count": 1,
                "claimed": False,
            }
        print("[loop] No tasks available, will retry in 30s...")

    if claim_only:
        if task_id:
            print(f"[loop] Claimed {task_id} — doing work...")
            info = _get_task_info(task_id)
            description = info.get("description", "") if info else ""
            spec_path = info.get("spec_path") if info else None
            priority = info.get("priority", 0) if info else 0
            ir_snippet = info.get("ir_snippet") if info else None
            parent_id = info.get("parent_id") if info else None

            # Log task claim
            log_task_claim(task_id, loop_id, priority)

            try:
                result_text = _do_work(task_id, description, spec_path, loop_id, pi_timeout, verbose, ir_snippet, parent_id, test_timeout, no_verify)
                print("[loop] Work summary:")
                summary = _format_work_result(result_text)
                for line in summary.split("\n"):
                    print(f"  {line}")
                _complete_task(task_id, result_text[:500])
            except Exception as e:
                print(f"[loop] Work failed: {e}")
                log_task_fail(task_id, loop_id, str(e))
                _fail_task(task_id, str(e))

            tasks_processed = 1
        else:
            print("[loop] No tasks available — exiting (claim-only mode)")

        duration = time.time() - start_time
        log_loop_end(loop_id, duration, tasks_processed)

        return {"command": "loop", "status": "success", "count": 1, "claimed": task_id}

    # Continuous loop — runs until KeyboardInterrupt
    try:
        while True:
            if task_id is not None:
                print(f"[loop] Claimed {task_id}")

                # Get full task info for description + spec
                info = _get_task_info(task_id)
                description = info.get("description", "") if info else ""
                spec_path = info.get("spec_path") if info else None
                priority = info.get("priority", 0) if info else 0
                ir_snippet = info.get("ir_snippet") if info else None
                parent_id = info.get("parent_id") if info else None

                # Log task claim
                log_task_claim(task_id, loop_id, priority)

                try:
                    result_text = _do_work(task_id, description, spec_path, loop_id, pi_timeout, verbose, ir_snippet, parent_id, test_timeout, no_verify)
                    print("[loop] Work summary:")
                    summary = _format_work_result(result_text)
                    for line in summary.split("\n"):
                        print(f"  {line}")
                    _complete_task(task_id, result_text[:500])
                    tasks_processed += 1
                except KeyboardInterrupt:
                    duration = time.time() - start_time
                    print("\n[loop] Interrupted by user — exiting gracefully")
                    log_loop_end(loop_id, duration, tasks_processed)
                    return {"command": "loop", "status": "interrupted", "count": tasks_processed}
                except Exception as e:
                    print(f"[loop] Work failed: {e}")
                    log_task_fail(task_id, loop_id, str(e))
                    _fail_task(task_id, str(e))

            task_id = None
            while task_id is None:
                print("[loop] Waiting 30s before retrying...")
                try:
                    time.sleep(30)
                except KeyboardInterrupt:
                    duration = time.time() - start_time
                    print("\n[loop] Interrupted by user — exiting gracefully")
                    log_loop_end(loop_id, duration, tasks_processed)
                    return {"command": "loop", "status": "interrupted", "count": tasks_processed}

                task_id = _claim_task()
                if task_id is None:
                    print("[loop] Still no tasks available...")

    except KeyboardInterrupt:
        duration = time.time() - start_time
        print("\n[loop] Interrupted by user — exiting gracefully")
        log_loop_end(loop_id, duration, tasks_processed)
        return {"command": "loop", "status": "interrupted", "count": tasks_processed}
    except Exception as e:
        log_loop_error(loop_id, str(e))
        raise


def handle_loops(args) -> dict:
    """Spawn N Ralph loops, each in a new terminal window (not yet implemented)."""
    raise NotImplementedError(
        "orca loops is not yet implemented — use multiple terminal windows with orca loop"
    )


def format_loop_human(result: dict) -> str:
    claimed = result.get("claimed")
    if claimed is False:
        return "✓ No tasks available"
    if claimed:
        return f"✓ Claimed task {claimed}"
    return "✓ Ralph loop running — Ctrl+C to exit"


def format_loops_human(result: dict) -> str:
    return f"✓ Spawned {result['count']} Ralph loops in new terminal windows"

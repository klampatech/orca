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


ORCA_CMD: list[str] = [shutil.which("orca") or "orca"]
PI_CMD: str | None = shutil.which("pi")


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


def _run_pi(prompt: str, timeout: int | None = None, verbose: bool = False) -> str:
    """Pipe a prompt to pi -p, return the result text.

    Also forks the inference for debugging.

    Args:
        prompt: The prompt to send to pi.
        timeout: Maximum seconds to wait (None = unlimited).
        verbose: If True, print extra debugging info.
    """
    if PI_CMD is None:
        raise RuntimeError("pi CLI not found in PATH")

    cmd: list[str] = [PI_CMD, "-p", prompt]

    if verbose:
        print(f"[loop:debug] pi command: {' '.join(cmd[:3])} ...")
        print(f"[loop:debug] prompt chars: {len(prompt)}")

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
        if verbose:
            print(f"[loop:debug] pi FAILED exit_code={result.returncode}")
            print(f"[loop:debug] pi stderr: {result.stderr[:500]}")
            print(f"[loop:debug] pi stdout: {result.stdout[:500]}")
        raise RuntimeError(
            f"pi exited with code {result.returncode}: {result.stderr[:500]}"
        )

    return result.stdout.strip()


def _run_tests() -> tuple[bool, str]:
    """Run project tests and return (success, output).

    Detects project type and runs appropriate test command:
    - Node.js (package.json): npm test
    - Python (pytest, pyproject.toml, setup.py): python -m pytest
    - Go (go.mod): go test
    - Ruby (Gemfile): bundle exec rspec

    Also logs the test output.
    """
    cwd = Path.cwd()
    start_time = time.time()

    # Detect Node.js project
    if (cwd / "package.json").exists():
        result = subprocess.run(
            ["npm", "test"],
            capture_output=True,
            text=True,
            timeout=120,
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
            timeout=120,
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
            timeout=120,
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
            timeout=120,
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
) -> str:
    """Run pi to implement the given task, validate with tests. Returns result summary.

    Logs the inference for debugging.


    Args:
        task_id: The task ID being worked on.
        description: Task description.
        spec_path: Optional path to spec file.
        loop_id: The loop ID.
        pi_timeout: Timeout for pi in seconds (None = unlimited).
    """
    start_time = time.time()

    # Build the prompt for Otto — follows IMPLEMENTATION_PLAN.md generated by orca plan
    prompt_parts = [
        "You are Otto — an autonomous AI coding agent.\n",
        "Implement functionality following @IMPLEMENTATION_PLAN.md. Work in the current directory.\n",
    ]

    # Updated build iteration instructions
    prompt_parts.extend(
        [
            "## Scenario",
            description,
            "",
            "## Instructions (follow in order)",
            "",
            "**Study Phase**",
            "0a. Study `specs/*` with up to 500 parallel Sonnet subagents to learn the application specifications.",
            "0b. Study @IMPLEMENTATION_PLAN.md.",
            "0c. For reference, the application source code is in `src/*`.",
            "",
            "**Implementation Phase**",
            "1. Your task is to implement functionality per the specifications using parallel subagents. Follow @IMPLEMENTATION_PLAN.md and choose the most important item to address. Before making changes, search the codebase (don't assume not implemented) using Sonnet subagents. You may use up to 500 parallel Sonnet subagents for searches/reads and only 1 Sonnet subagent for build/tests. Use Opus subagents when complex reasoning is needed (debugging, architectural decisions).",
            "2. After implementing functionality or resolving problems, run the tests for that unit of code that was improved. If functionality is missing then it's your job to add it as per the application specifications. Ultrathink.",
            "3. When you discover issues, immediately update @IMPLEMENTATION_PLAN.md with your findings using a subagent. When resolved, update and remove the item.",
            "4. When the tests pass, update @IMPLEMENTATION_PLAN.md, then `git add -A` then `git commit` with a message describing the changes. After the commit, `git push`.",
            "",
            "**Maintenance Phase**",
            "99999. Important: When authoring documentation, capture the why — tests and implementation importance.",
            "999999. Important: Single sources of truth, no migrations/adapters. If tests unrelated to your work fail, resolve them as part of the increment.",
            "9999999. As soon as there are no build or test errors create a git tag. If there are no git tags start at 0.0.0 and increment patch by 1 for example 0.0.1  if 0.0.0 does not exist.",
            "99999999. You may add extra logging if required to debug issues.",
            "999999999. Keep @IMPLEMENTATION_PLAN.md current with learnings using a subagent — future work depends on this to avoid duplicating efforts. Update especially after finishing your turn.",
            "9999999999. When you learn something new about how to run the application, update @AGENTS.md using a subagent but keep it brief. For example if you run commands multiple times before learning the correct command then that file should be updated.",
            "99999999999. For any bugs you notice, resolve them or document them in @IMPLEMENTATION_PLAN.md using a subagent even if it is unrelated to the current piece of work.",
            "999999999999. Implement functionality completely. Placeholders and stubs waste efforts and time redoing the same work.",
            "9999999999999. When @IMPLEMENTATION_PLAN.md becomes large periodically clean out the items that are completed from the file using a subagent.",
            "99999999999999. If you find inconsistencies in the specs/* then use an Opus 4.6 subagent with 'ultrathink' requested to update the specs.",
            "999999999999999. IMPORTANT: Keep @AGENTS.md operational only – status updates and progress notes belong in `IMPLEMENTATION_PLAN.md`. A bloated AGENTS.md pollutes every future loop's context.",
            "",
        ]
    )

    if spec_path:
        prompt_parts.append(f"Spec file: {spec_path}")

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

    # Log inference start
    infer_start = time.time()
    try:
        result_text = _run_pi(test_first_prompt, timeout=pi_timeout, verbose=verbose)
        infer_duration_ms = int((time.time() - infer_start) * 1000)

        # Log inference completion
        log_inference(
            prompt=test_first_prompt,
            response=result_text,
            duration_ms=infer_duration_ms,
            success=True,
        )

        print(f"[loop] pi done: {result_text[:100]}")

        # Run validation tests
        print("[loop] Running validation tests...")
        tests_passed, test_output = _run_tests()
        print(f"[loop] Tests: {'PASSED' if tests_passed else 'FAILED'}")
        if not tests_passed:
            raise RuntimeError(f"Tests failed:\n{test_output}")
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
        print("[loop] No tasks available, sleeping 30s...")

    if claim_only:
        if task_id:
            print(f"[loop] Claimed {task_id} — doing work...")
            info = _get_task_info(task_id)
            description = info.get("description", "") if info else ""
            spec_path = info.get("spec_path") if info else None
            priority = info.get("priority", 0) if info else 0

            # Log task claim
            log_task_claim(task_id, loop_id, priority)

            try:
                result_text = _do_work(task_id, description, spec_path, loop_id, pi_timeout, verbose)
                print(f"[loop] pi done: {result_text[:100]}")
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

                # Log task claim
                log_task_claim(task_id, loop_id, priority)

                try:
                    result_text = _do_work(task_id, description, spec_path, loop_id, pi_timeout, verbose)
                    print(f"[loop] pi done: {result_text[:100]}")
                    _complete_task(task_id, result_text[:500])
                    tasks_processed += 1
                except Exception as e:
                    print(f"[loop] Work failed: {e}")
                    log_task_fail(task_id, loop_id, str(e))
                    _fail_task(task_id, str(e))

            task_id = None
            while task_id is None:
                print("[loop] No tasks available, sleeping 30s...")
                try:
                    time.sleep(30)
                except KeyboardInterrupt:
                    print("\n[loop] Interrupted — exiting.")
                    duration = time.time() - start_time
                    log_loop_end(loop_id, duration, tasks_processed)
                    return {"command": "loop", "status": "success", "count": 1}

                task_id = _claim_task()
                if task_id is None:
                    print("[loop] No tasks available, retrying...")

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

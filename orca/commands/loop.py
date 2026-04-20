"""Spawn Ralph loops — inline in current terminal or in new windows."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import uuid


ORCA_CMD = [shutil.which("orca")]
PI_CMD = shutil.which("pi")


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


def _run_pi(prompt: str) -> str:
    """Pipe a prompt to pi -p, return the result text."""
    if PI_CMD is None:
        raise RuntimeError("pi CLI not found in PATH")

    result = subprocess.run(
        [PI_CMD, "-p", prompt],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pi exited with code {result.returncode}: {result.stderr[:500]}")

    return result.stdout.strip()[:1000]


def _run_tests() -> tuple[bool, str]:
    """Run pytest and return (success, output)."""
    python_cmd = shutil.which("python3") or shutil.which("python")
    result = subprocess.run(
        [python_cmd, "-m", "pytest", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    success = result.returncode == 0
    output = result.stdout[:2000] if result.stdout else result.stderr[:2000]
    return success, output


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


def _do_work(task_id: str, description: str, spec_path: str | None, loop_id: str) -> str:
    """Run pi to implement the given task, validate with tests. Returns result summary."""
    # Test-first prompting: ask pi to write tests BEFORE implementation
    test_first_prompt = f"""You are Otto — an autonomous AI coding agent.

Implement the following task using TDD (Test-Driven Development). Work in the current directory.

## Scenario
{description}

## Instructions (follow in order)
1. If a spec file exists at "{spec_path}", read it first to understand requirements
2. Write failing tests FIRST (red phase)
3. Implement the feature to make tests pass (green phase)
4. Run tests to verify correctness
5. Commit and push

IMPORTANT: You MUST write tests before implementing. Do not skip the test-writing phase.

Return a brief summary of what you did, including test results."""
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(target=_send_heartbeat, args=(task_id, loop_id, stop_heartbeat), daemon=True)
    heartbeat_thread.start()

    print("[loop] Starting pi (test-first)...")
    try:
        result_text = _run_pi(test_first_prompt)
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
        print(f"[loop] ERROR: complete failed (exit {result.returncode}): {result.stderr[:200]}")
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
        print(f"[loop] ERROR: fail failed (exit {result.returncode}): {result.stderr[:200]}")
    else:
        print(f"[loop] Failed {task_id}: {error_text[:100]}")


def handle_loop(args) -> dict:
    """Run a Ralph loop inline in the current terminal.

    Blocks forever until Ctrl+C. Each invocation uses a fresh UUID as loop ID.
    A --claim-only flag claims one task, completes it, and exits immediately.
    """
    loop_id = str(uuid.uuid4())
    print(f"[loop] Starting Ralph loop with ID: {loop_id}")

    claim_only: bool = getattr(args, "claim_only", False)
    task_id = _claim_task()

    if task_id is None:
        if claim_only:
            print("[loop] No tasks available — exiting (claim-only mode)")
            return {"command": "loop", "status": "success", "count": 1, "claimed": False}
        print("[loop] No tasks available, sleeping 30s...")

    if claim_only:
        if task_id:
            print(f"[loop] Claimed {task_id} — doing work...")
            info = _get_task_info(task_id)
            description = info.get("description", "") if info else ""
            spec_path = info.get("spec_path") if info else None
            try:
                result_text = _do_work(task_id, description, spec_path, loop_id)
                print(f"[loop] pi done: {result_text[:100]}")
                _complete_task(task_id, result_text[:500])
            except Exception as e:
                print(f"[loop] Work failed: {e}")
                _fail_task(task_id, str(e))
        else:
            print("[loop] No tasks available — exiting (claim-only mode)")
        return {"command": "loop", "status": "success", "count": 1, "claimed": task_id}

    # Continuous loop — runs until KeyboardInterrupt
    while True:
        if task_id is not None:
            print(f"[loop] Claimed {task_id}")

            # Get full task info for description + spec
            info = _get_task_info(task_id)
            description = info.get("description", "") if info else ""
            spec_path = info.get("spec_path") if info else None

            try:
                result_text = _do_work(task_id, description, spec_path, loop_id)
                print(f"[loop] pi done: {result_text[:100]}")
                _complete_task(task_id, result_text[:500])
            except Exception as e:
                print(f"[loop] Work failed: {e}")
                _fail_task(task_id, str(e))

        task_id = None
        while task_id is None:
            print("[loop] No tasks available, sleeping 30s...")
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                print("\n[loop] Interrupted — exiting.")
                return {"command": "loop", "status": "success", "count": 1}

            task_id = _claim_task()
            if task_id is None:
                print("[loop] No tasks available, retrying...")


def handle_loops(args) -> dict:
    """Spawn N Ralph loops, each in a new terminal window (not yet implemented)."""
    raise NotImplementedError("orca loops is not yet implemented — use multiple terminal windows with orca loop")


def format_loop_human(result: dict) -> str:
    claimed = result.get("claimed")
    if claimed is False:
        return "✓ No tasks available"
    if claimed:
        return f"✓ Claimed task {claimed}"
    return "✓ Ralph loop running — Ctrl+C to exit"


def format_loops_human(result: dict) -> str:
    return f"✓ Spawned {result['count']} Ralph loops in new terminal windows"

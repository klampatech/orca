"""orch cleanup — Clean up zombie processes and stuck tasks."""

import subprocess
import time
import os
import signal


# Process names that indicate zombie/test hangs
ZOMBIE_PROCESS_PATTERNS = [
    "npm test",
    "npm run test",
    "jest",
    "vitest",
    "pytest",
    "python -m pytest",
    "rspec",
    "go test",
]

# How old a process must be to be considered a zombie (seconds)
ZOMBIE_MIN_AGE_SECONDS = 60


def _cleanup_zombies() -> dict:
    """Kill zombie test processes that have been running too long."""
    killed = 0
    now = time.time()

    try:
        # Use ps to find matching processes (macOS compatible: use 'command' not 'cmd')
        result = subprocess.run(
            ["ps", "-eo", "pid,etime,command"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"command": "cleanup", "status": "error", "zombies_killed": 0, "error": "ps command failed"}

        for line in result.stdout.splitlines()[1:]:  # Skip header
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue

            pid_str, etime, cmd = parts
            pid = int(pid_str)

            # Skip our own process and init
            if pid == os.getpid() or pid == 1:
                continue

            # Check if command matches zombie patterns
            if not any(pattern in cmd for pattern in ZOMBIE_PROCESS_PATTERNS):
                continue

            # Parse elapsed time
            try:
                if '-' in etime:
                    age_seconds = ZOMBIE_MIN_AGE_SECONDS + 1
                elif ':' in etime:
                    time_parts = etime.split(':')
                    if len(time_parts) == 3:
                        age_seconds = int(time_parts[0])*3600 + int(time_parts[1])*60 + int(time_parts[2])
                    elif len(time_parts) == 2:
                        age_seconds = int(time_parts[0])*60 + int(time_parts[1])
                    else:
                        age_seconds = 0
                else:
                    age_seconds = int(etime) * 60 if etime.isdigit() else 0
            except (ValueError, IndexError):
                continue

            if age_seconds >= ZOMBIE_MIN_AGE_SECONDS:
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                    print(f"Killed zombie process {pid}: {cmd[:60]} (age: {etime})")
                except (OSError, ProcessLookupError):
                    pass

    except subprocess.TimeoutExpired:
        return {"command": "cleanup", "status": "error", "zombies_killed": killed, "error": "ps timed out"}
    except Exception as e:
        return {"command": "cleanup", "status": "error", "zombies_killed": killed, "error": str(e)}

    return {"command": "cleanup", "status": "success", "zombies_killed": killed}


def _cleanup_stuck_tasks() -> dict:
    """Reset tasks with expired heartbeats (reclaim stuck tasks)."""
    from ..models.task_run import reclaim_stale_task_runs
    from ..db.connection import get_connection

    conn = get_connection()
    reclaimed = reclaim_stale_task_runs(conn)
    conn.commit()

    return {"command": "cleanup", "status": "success", "stuck_tasks_reclaimed": reclaimed}


def handle_cleanup(args) -> dict:
    """Clean up zombie processes and/or stuck tasks.

    Args:
        args.zombies: If True, kill zombie test processes.
        args.stuck: If True, reclaim tasks with expired heartbeats.
        args.all: If True, run all cleanup operations.

    Returns:
        A result dict with cleanup results.
    """
    zombies = getattr(args, 'zombies', False)
    stuck = getattr(args, 'stuck', False)
    all_cleanup = getattr(args, 'all', False)

    # Default to --all if nothing specified
    if all_cleanup or (not zombies and not stuck):
        zombies = True
        stuck = True

    results = {}

    if zombies or all_cleanup:
        zombie_result = _cleanup_zombies()
        results['zombies'] = zombie_result
        if zombie_result['status'] == 'error':
            results['status'] = 'error'
            results['error'] = zombie_result.get('error')

    if stuck or all_cleanup:
        stuck_result = _cleanup_stuck_tasks()
        results['stuck_tasks'] = stuck_result

    if 'status' not in results:
        results['status'] = 'success'

    return results


def format_cleanup_human(result: dict) -> str:
    parts = []

    if 'zombies' in result:
        z = result['zombies']
        if z['status'] == 'success':
            parts.append(f"Zombie processes killed: {z['zombies_killed']}")
        else:
            parts.append(f"Zombie cleanup error: {z.get('error', 'unknown')}")

    if 'stuck_tasks' in result:
        s = result['stuck_tasks']
        parts.append(f"Stuck tasks reclaimed: {s.get('stuck_tasks_reclaimed', 0)}")

    return " | ".join(parts) if parts else "No cleanup performed"

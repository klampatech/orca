"""Orchestrator logging for debugging and audit trail.

Logs are written to .orch/logs/orca-YYYY-MM-DD.log as JSON lines.
This provides a searchable, machine-parseable record of all orchestrator
operations for debugging and performance analysis.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ParamSpec
from uuid import uuid4

if TYPE_CHECKING:
    P = ParamSpec("P")

# Type alias for file opener functions
_FileOpener = Callable[[str, str], Any]


# --------------------------------------------------------------------
# Global state
# --------------------------------------------------------------------

_log_dir: Path | None = None
_log_file: Path | None = None
_log_fd: int | None = None
_session_id: str = str(uuid4())[:8]


def reset_logging_state() -> None:
    """Reset all cached logging state.

    Useful for tests that change the working directory, as the log
    directory is resolved relative to CWD.
    """
    global _log_dir, _log_file, _log_fd

    if _log_fd is not None:
        try:
            os.close(_log_fd)
        except OSError:
            pass

    _log_dir = None
    _log_file = None
    _log_fd = None


def _get_log_dir() -> Path:
    """Get or create the logs directory.

    Resolved dynamically based on current working directory.
    """
    global _log_dir

    # Always resolve dynamically - don't cache across CWD changes
    from ..db.connection import get_orch_dir

    _log_dir = get_orch_dir() / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    return _log_dir


def _get_log_file() -> Path:
    """Get the current log file (rotated daily).

    Always resolves fresh based on current CWD.
    """
    global _log_file

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = _get_log_dir()  # This always resolves fresh

    new_path = log_dir / f"orca-{today}.log"
    if _log_file != new_path:
        # File path changed (e.g., date rolled over or CWD changed)
        # Close old fd and invalidate cache
        global _log_fd
        if _log_fd is not None:
            try:
                os.close(_log_fd)
            except OSError:
                pass
            _log_fd = None
        _log_file = new_path

    return _log_file


def _open_log() -> int:
    """Open (or reopen) the log file for appending."""
    global _log_fd

    log_file = _get_log_file()

    # Reopen if path changed or fd is closed
    if _log_fd is None:
        _log_fd = os.open(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

    return _log_fd


def _close_log() -> None:
    """Close the log file descriptor."""
    global _log_fd
    if _log_fd is not None:
        try:
            os.close(_log_fd)
        except OSError:
            pass
        _log_fd = None


def _write_entry(entry: dict) -> None:
    """Write a JSON log entry to the current log file."""
    try:
        fd = _open_log()
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        os.write(fd, line.encode("utf-8"))
    except Exception as e:
        # Don't let logging failures crash the orchestrator
        print(f"WARNING: Failed to write log entry: {e}", file=sys.stderr)


# --------------------------------------------------------------------
# Log entry helpers
# --------------------------------------------------------------------


def _timestamp() -> str:
    """Return UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _make_entry(event: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a log entry with standard fields."""
    entry: dict[str, Any] = {
        "timestamp": _timestamp(),
        "session": _session_id,
        "event": event,
    }
    if data:
        entry["data"] = data
    return entry


# --------------------------------------------------------------------
# Public logging functions
# --------------------------------------------------------------------


def log_refine_start(spec_path: str, max_iterations: int = 5) -> None:
    """Log start of spec refinement."""
    _write_entry(
        _make_entry(
            "refine_start",
            {
                "spec_path": spec_path,
                "max_iterations": max_iterations,
            },
        )
    )


def log_refine_complete(
    spec_path: str,
    iterations: int,
    final_hash: str,
    stable: bool,
    output_path: str | None = None,
) -> None:
    """Log completion of spec refinement."""
    _write_entry(
        _make_entry(
            "refine_complete",
            {
                "spec_path": spec_path,
                "iterations": iterations,
                "final_hash": final_hash,
                "stable": stable,
                "output_path": output_path,
            },
        )
    )


def log_refine_error(spec_path: str, error: str) -> None:
    """Log refinement error."""
    _write_entry(
        _make_entry(
            "refine_error",
            {
                "spec_path": spec_path,
                "error": error,
            },
        )
    )


def log_decompose_start(spec_path: str, mode: str) -> None:
    """Log start of spec decomposition."""
    _write_entry(
        _make_entry(
            "decompose_start",
            {
                "spec_path": spec_path,
                "mode": mode,
            },
        )
    )


def log_decompose_complete(
    spec_path: str,
    total_tasks: int,
    feature_ids: list[str],
    spec_root_id: str,
) -> None:
    """Log completion of spec decomposition."""
    _write_entry(
        _make_entry(
            "decompose_complete",
            {
                "spec_path": spec_path,
                "total_tasks": total_tasks,
                "feature_ids": feature_ids,
                "spec_root_id": spec_root_id,
            },
        )
    )


def log_loop_start(loop_id: str, spec_path: str | None = None) -> None:
    """Log start of a Ralph loop."""
    _write_entry(
        _make_entry(
            "loop_start",
            {
                "loop_id": loop_id,
                "spec_path": spec_path,
            },
        )
    )


def log_loop_end(
    loop_id: str, duration_seconds: float, tasks_processed: int = 0
) -> None:
    """Log end of a Ralph loop."""
    _write_entry(
        _make_entry(
            "loop_end",
            {
                "loop_id": loop_id,
                "duration_seconds": round(duration_seconds, 2),
                "tasks_processed": tasks_processed,
            },
        )
    )


def log_loop_error(loop_id: str, error: str) -> None:
    """Log loop error."""
    _write_entry(
        _make_entry(
            "loop_error",
            {
                "loop_id": loop_id,
                "error": error,
            },
        )
    )


def log_task_claim(task_id: str, loop_id: str, priority: int) -> None:
    """Log task claim event."""
    _write_entry(
        _make_entry(
            "task_claim",
            {
                "task_id": task_id,
                "loop_id": loop_id,
                "priority": priority,
            },
        )
    )


def log_task_complete(
    task_id: str,
    loop_id: str,
    duration_seconds: float,
    exit_status: int,
) -> None:
    """Log task completion event."""
    _write_entry(
        _make_entry(
            "task_complete",
            {
                "task_id": task_id,
                "loop_id": loop_id,
                "duration_seconds": round(duration_seconds, 2),
                "exit_status": exit_status,
            },
        )
    )


def log_task_fail(task_id: str, loop_id: str, error: str) -> None:
    """Log task failure event."""
    _write_entry(
        _make_entry(
            "task_fail",
            {
                "task_id": task_id,
                "loop_id": loop_id,
                "error": error,
            },
        )
    )


def log_inference(
    prompt: str,
    response: str,
    model: str | None = None,
    duration_ms: int | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Log a pi CLI inference (prompt + response).

    This captures the raw inputs/outputs for debugging drift issues
    or understanding model behavior.
    """
    # Truncate very long prompts/responses to avoid huge log files
    # but keep enough for debugging
    MAX_PROMPT_LEN = 50000
    MAX_RESPONSE_LEN = 50000

    prompt_truncated = (
        prompt[:MAX_PROMPT_LEN] if len(prompt) > MAX_PROMPT_LEN else prompt
    )
    response_truncated = (
        response[:MAX_RESPONSE_LEN] if len(response) > MAX_RESPONSE_LEN else response
    )

    _write_entry(
        _make_entry(
            "inference",
            {
                "model": model,
                "prompt_length": len(prompt),
                "response_length": len(response),
                "prompt_preview": prompt_truncated[:500]
                + ("..." if len(prompt_truncated) > 500 else ""),
                "response_preview": response_truncated[:500]
                + ("..." if len(response_truncated) > 500 else ""),
                "duration_ms": duration_ms,
                "success": success,
                "error": error,
            },
        )
    )


def log_validation_start(feature_id: str) -> None:
    """Log start of hidden scenario validation."""
    _write_entry(
        _make_entry(
            "validation_start",
            {
                "feature_id": feature_id,
            },
        )
    )


def log_validation_complete(
    feature_id: str,
    scenarios_found: int,
    scenarios_passed: int,
    scenarios_failed: int,
    scenarios_errored: int,
    duration_ms: int,
) -> None:
    """Log completion of hidden scenario validation."""
    _write_entry(
        _make_entry(
            "validation_complete",
            {
                "feature_id": feature_id,
                "scenarios_found": scenarios_found,
                "scenarios_passed": scenarios_passed,
                "scenarios_failed": scenarios_failed,
                "scenarios_errored": scenarios_errored,
                "duration_ms": duration_ms,
            },
        )
    )


def log_validation_error(feature_id: str, error: str) -> None:
    """Log validation error."""
    _write_entry(
        _make_entry(
            "validation_error",
            {
                "feature_id": feature_id,
                "error": error,
            },
        )
    )


def log_terminal_output(
    source: str,
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    duration_ms: int | None = None,
) -> None:
    """Log captured terminal output from pi or test runners."""
    # Truncate to avoid huge logs
    MAX_OUTPUT_LEN = 10000

    _write_entry(
        _make_entry(
            "terminal_output",
            {
                "source": source,  # "pi", "pytest", "npm", etc.
                "command": command,
                "stdout_preview": stdout[:MAX_OUTPUT_LEN]
                + ("..." if len(stdout) > MAX_OUTPUT_LEN else ""),
                "stderr_preview": stderr[:MAX_OUTPUT_LEN]
                + ("..." if len(stderr) > MAX_OUTPUT_LEN else ""),
                "exit_code": exit_code,
                "stdout_length": len(stdout),
                "stderr_length": len(stderr),
                "duration_ms": duration_ms,
            },
        )
    )


def log_command(command: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    """Log a CLI command execution."""
    _write_entry(
        _make_entry(
            "command",
            {
                "command": command,
                "args": args,
                "status": result.get("status", "unknown"),
            },
        )
    )


# --------------------------------------------------------------------
# Utility: Query logs
# --------------------------------------------------------------------


def query_logs(
    event_filter: str | None = None,
    session_filter: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query recent log entries.

    Args:
        event_filter: Only return entries matching this event type.
        session_filter: Only return entries from this session ID.
        since: Only return entries after this timestamp.
        limit: Maximum number of entries to return.

    Returns:
        List of log entry dicts.
    """
    log_dir = _get_log_dir()
    entries = []

    # Read all log files (newest first)
    log_files = sorted(log_dir.glob("orca-*.log"), reverse=True)

    for log_file in log_files:
        opener: _FileOpener
        if log_file.suffix == ".gz":
            opener = gzip.open
        else:
            opener = open

        try:
            with opener(log_file, "rt") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Apply filters
                    if event_filter and entry.get("event") != event_filter:
                        continue
                    if session_filter and entry.get("session") != session_filter:
                        continue
                    if since and entry.get("timestamp", "") < since.isoformat():
                        continue

                    entries.append(entry)

                    if len(entries) >= limit:
                        return entries
        except Exception:
            continue

    return entries


# --------------------------------------------------------------------
# Utility: Get recent events for a loop/task
# --------------------------------------------------------------------


def get_loop_events(loop_id: str, limit: int = 50) -> list[dict]:
    """Get recent log entries for a specific loop."""
    log_dir = _get_log_dir()
    entries = []

    log_files = sorted(log_dir.glob("orca-*.log"), reverse=True)

    for log_file in log_files:
        opener: _FileOpener
        if log_file.suffix == ".gz":
            opener = gzip.open
        else:
            opener = open

        try:
            with opener(log_file, "rt") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    data = entry.get("data", {})
                    if data.get("loop_id") == loop_id:
                        entries.append(entry)

                    if len(entries) >= limit:
                        return entries
        except Exception:
            continue

    return entries


def get_task_events(task_id: str, limit: int = 50) -> list[dict]:
    """Get recent log entries for a specific task."""
    log_dir = _get_log_dir()
    entries = []

    log_files = sorted(log_dir.glob("orca-*.log"), reverse=True)

    for log_file in log_files:
        opener: _FileOpener
        if log_file.suffix == ".gz":
            opener = gzip.open
        else:
            opener = open

        try:
            with opener(log_file, "rt") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    data = entry.get("data", {})
                    if data.get("task_id") == task_id:
                        entries.append(entry)

                    if len(entries) >= limit:
                        return entries
        except Exception:
            continue

    return entries

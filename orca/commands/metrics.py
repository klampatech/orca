"""orch metrics — Show throughput and duration metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def handle_metrics(args) -> dict[str, Any]:
    """Display throughput and duration metrics.

    Shows task counts by status, duration stats, and loop activity.
    Optionally filters to a specific spec.
    """
    spec_path: Path | None = getattr(args, "spec", None)
    if spec_path:
        spec_path = Path(spec_path)

    from ..db.connection import get_connection

    conn = get_connection()

    # Build WHERE clause for spec filtering
    spec_filter = "root_spec_path = ?" if spec_path else None
    spec_params: tuple = (str(spec_path),) if spec_path else ()

    where = "WHERE " + spec_filter if spec_filter else ""

    # Overall task counts
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM tasks {where}",
        spec_params,
    ).fetchone()
    total = total_row[0] if total_row else 0

    by_status_rows = conn.execute(
        f"SELECT status, COUNT(*) FROM tasks {where} GROUP BY status",
        spec_params,
    ).fetchall()
    by_status = dict(by_status_rows)

    # Duration stats for completed tasks
    duration_row = conn.execute("""
        SELECT
            AVG(julianday(completed_at) - julianday(claimed_at)) * 86400 as avg_seconds,
            MIN(julianday(completed_at) - julianday(claimed_at)) * 86400 as min_seconds,
            MAX(julianday(completed_at) - julianday(claimed_at)) * 86400 as max_seconds
        FROM tasks t
        WHERE status = 'completed'
          AND completed_at IS NOT NULL
          AND claimed_at IS NOT NULL
          AND (? = '' OR t.root_spec_path = ?)
    """, (str(spec_path) if spec_path else "", str(spec_path) if spec_path else "")).fetchone()

    # Loop activity
    active_loops_row = conn.execute("""
        SELECT COUNT(*) FROM loops
        WHERE datetime(last_heartbeat_at, '+60 seconds') > datetime(utcnow())
    """).fetchone()
    active_loops = active_loops_row[0] if active_loops_row else 0

    # Hidden scenario run summary
    hsr_row = conn.execute("""
        SELECT COUNT(*) as total_runs,
               SUM(scenarios_found) as total_found,
               SUM(scenarios_passed) as total_passed,
               SUM(scenarios_failed) as total_failed,
               SUM(scenarios_errored) as total_errored
        FROM hidden_scenario_runs
    """).fetchone()

    by_status_verbose: dict[str, Any] = {}
    for status, count in by_status.items():
        pct = (count / total * 100) if total > 0 else 0
        by_status_verbose[status] = {"count": count, "percent": round(pct, 1)}

    return {
        "command": "metrics",
        "total_tasks": total,
        "by_status": by_status_verbose,
        "duration_seconds": {
            "avg": round(duration_row[0], 1) if duration_row and duration_row[0] else None,
            "min": round(duration_row[1], 1) if duration_row and duration_row[1] else None,
            "max": round(duration_row[2], 1) if duration_row and duration_row[2] else None,
        },
        "active_loops": active_loops,
        "throughput_tasks_per_second": (
            round(total / duration_row[0], 2) if duration_row and duration_row[0] and duration_row[0] > 0 else None
        ),
        "hidden_scenario_runs": {
            "total_runs": hsr_row[0] or 0,
            "total_scenarios": hsr_row[1] or 0,
            "passed": hsr_row[2] or 0,
            "failed": hsr_row[3] or 0,
            "errored": hsr_row[4] or 0,
        } if hsr_row else None,
    }


def format_metrics_human(result: dict) -> str:
    """Format metrics for human display."""
    lines = ["Metrics"]

    # Task counts
    total = result.get("total_tasks", 0)
    lines.append(f"  Total tasks: {total}")

    by_status = result.get("by_status", {})
    if by_status:
        lines.append("  By status:")
        for status, info in sorted(by_status.items()):
            count = info.get("count", 0)
            pct = info.get("percent", 0)
            lines.append(f"    {status}: {count} ({pct}%)")

    # Duration stats
    duration = result.get("duration_seconds", {})
    if duration.get("avg"):
        lines.append(
            f"  Avg duration: {duration['avg']}s "
            f"(min: {duration['min']}s, max: {duration['max']}s)"
        )

    # Active loops
    active = result.get("active_loops", 0)
    lines.append(f"  Active loops: {active}")

    # Throughput
    throughput = result.get("throughput_tasks_per_second")
    if throughput:
        lines.append(f"  Throughput: {throughput} tasks/second")

    # Hidden scenario runs
    hsr = result.get("hidden_scenario_runs")
    if hsr and hsr.get("total_runs", 0) > 0:
        lines.append("")
        lines.append("  Hidden Scenario Validation:")
        lines.append(f"    Total runs: {hsr['total_runs']}")
        lines.append(
            f"    Scenarios: {hsr['total_passed']} passed, "
            f"{hsr['total_failed']} failed, {hsr['total_errored']} errored"
        )

    return "\n".join(lines)

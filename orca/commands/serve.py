"""orch serve — HTTP API server for remote monitoring and control.

Requires: pip install flask
"""

from __future__ import annotations

import threading
from typing import Any

try:
    from flask import Flask, jsonify, request
except ImportError:
    Flask = None

from ..db.connection import get_connection


def handle_serve(args) -> dict[str, Any]:
    """Start HTTP API server for remote monitoring and control.

    Args:
        args.port: HTTP port (default: 8080)
        args.host: HTTP host (default: 0.0.0.0)

    Returns:
        A result dict confirming server startup.
    """
    if Flask is None:
        raise RuntimeError(
            "Flask is required for orca serve. Install it with: pip install flask"
        )

    host: str = getattr(args, "host", "0.0.0.0")
    port: int = getattr(args, "port", 8080)

    app = Flask("orca-serve")

    def _build_spec_args(spec: str | None) -> Any:
        """Build args object for command handlers."""
        class Args:
            spec = spec
        return Args()

    @app.route("/health")
    def health():
        """Health check endpoint."""
        return jsonify({"status": "ok"})

    @app.route("/api/status", methods=["GET"])
    def api_status():
        """Task status overview."""
        spec = request.args.get("spec")
        from .status import handle_status
        result = handle_status(_build_spec_args(spec))
        return jsonify(result)

    @app.route("/api/metrics", methods=["GET"])
    def api_metrics():
        """Throughput and duration metrics."""
        spec = request.args.get("spec")
        from .metrics import handle_metrics
        result = handle_metrics(_build_spec_args(spec))
        return jsonify(result)

    @app.route("/api/tasks", methods=["GET"])
    def api_tasks():
        """List all tasks, optionally filtered by status."""
        status = request.args.get("status")
        spec = request.args.get("spec")

        where_clauses = []
        params = []
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        if spec:
            where_clauses.append("root_spec_path = ?")
            params.append(spec)

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        conn = get_connection()
        rows = conn.execute(
            f"""
            SELECT id, description, status, priority, claimed_at, completed_at,
                   result_summary, parent_id
            FROM tasks
            {where}
            ORDER BY priority DESC, created_at ASC
            LIMIT 100
            """,
            params,
        ).fetchall()

        return jsonify({
            "tasks": [
                {
                    "id": r[0],
                    "description": r[1],
                    "status": r[2],
                    "priority": r[3],
                    "claimed_at": r[4],
                    "completed_at": r[5],
                    "result_summary": r[6],
                    "parent_id": r[7],
                }
                for r in rows
            ],
            "count": len(rows),
        })

    @app.route("/api/tasks/<task_id>", methods=["GET"])
    def api_task(task_id: str):
        """Single task with all runs."""
        conn = get_connection()

        task_row = conn.execute(
            """
            SELECT id, spec_path, description, status, priority, created_at,
                   claimed_at, completed_at, result_summary, parent_id,
                   root_spec_path, ir_snippet
            FROM tasks WHERE id = ?
            """,
            (task_id,),
        ).fetchone()

        if not task_row:
            return jsonify({"error": "Task not found"}), 404

        runs = conn.execute(
            """
            SELECT id, loop_id, claimed_at, heartbeat_at, completed_at,
                   exit_status, result_summary
            FROM task_runs WHERE task_id = ?
            ORDER BY claimed_at ASC
            """,
            (task_id,),
        ).fetchall()

        return jsonify({
            "task": {
                "id": task_row[0],
                "spec_path": task_row[1],
                "description": task_row[2],
                "status": task_row[3],
                "priority": task_row[4],
                "created_at": task_row[5],
                "claimed_at": task_row[6],
                "completed_at": task_row[7],
                "result_summary": task_row[8],
                "parent_id": task_row[9],
                "root_spec_path": task_row[10],
                "ir_snippet": task_row[11],
            },
            "runs": [
                {
                    "id": r[0],
                    "loop_id": r[1],
                    "claimed_at": r[2],
                    "heartbeat_at": r[3],
                    "completed_at": r[4],
                    "exit_status": r[5],
                    "result_summary": r[6],
                }
                for r in runs
            ],
        })

    @app.route("/api/reclaim", methods=["POST"])
    def api_reclaim():
        """Reclaim stale tasks."""
        from .reclaim import handle_reclaim
        result = handle_reclaim(None)
        return jsonify(result)

    @app.route("/api/loops", methods=["GET"])
    def api_loops():
        """List active loops."""
        conn = get_connection()
        rows = conn.execute("""
            SELECT id, name, started_at, last_heartbeat_at, current_task_id
            FROM loops
            ORDER BY started_at DESC
            LIMIT 50
        """).fetchall()

        return jsonify({
            "loops": [
                {
                    "id": r[0],
                    "name": r[1],
                    "started_at": r[2],
                    "last_heartbeat_at": r[3],
                    "current_task_id": r[4],
                }
                for r in rows
            ],
            "count": len(rows),
        })

    @app.route("/api/hidden-scenarios", methods=["GET"])
    def api_hidden_scenarios():
        """List hidden scenario runs."""
        feature_id = request.args.get("feature_id")

        where = "WHERE feature_id = ?" if feature_id else ""
        params = (feature_id,) if feature_id else ()

        conn = get_connection()
        rows = conn.execute(f"""
            SELECT id, feature_id, loop_id, generated_at,
                   scenarios_found, scenarios_passed, scenarios_failed,
                   scenarios_errored, duration_ms, output_snippet
            FROM hidden_scenario_runs
            {where}
            ORDER BY generated_at DESC
            LIMIT 50
        """, params).fetchall()

        return jsonify({
            "runs": [
                {
                    "id": r[0],
                    "feature_id": r[1],
                    "loop_id": r[2],
                    "generated_at": r[3],
                    "scenarios_found": r[4],
                    "scenarios_passed": r[5],
                    "scenarios_failed": r[6],
                    "scenarios_errored": r[7],
                    "duration_ms": r[8],
                    "output_snippet": r[9],
                }
                for r in rows
            ],
            "count": len(rows),
        })

    # Run in background thread
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port),
        daemon=True,
    )
    thread.start()

    return {
        "command": "serve",
        "status": "started",
        "url": f"http://{host}:{port}",
        "endpoints": [
            "GET  /health",
            "GET  /api/status",
            "GET  /api/metrics",
            "GET  /api/tasks",
            "GET  /api/tasks/<id>",
            "POST /api/reclaim",
            "GET  /api/loops",
            "GET  /api/hidden-scenarios",
        ],
    }


def format_serve_human(result: dict) -> str:
    """Format serve result for human display."""
    lines = [
        f"✓ Orca API server started at {result['url']}",
        "",
        "Endpoints:",
    ]
    for endpoint in result.get("endpoints", []):
        lines.append(f"  {endpoint}")
    return "\n".join(lines)

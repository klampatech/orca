"""orch migrate — Apply pending database migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def handle_migrate(args) -> dict[str, Any]:
    """Apply pending database migrations.

    Reads migration files from orca/db/migrations/, tracks applied
    migrations in a schema_migrations table, and applies pending
    migrations in order.

    Migration files are named: <N>_name_up.sql
    Only files ending in _up.sql are applied.
    """
    from ..db.connection import get_connection
    from ..utils.time import utcnow

    conn = get_connection()

    # Ensure migrations tracking table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
    """)

    migrations_dir = Path(__file__).parent.parent / "db" / "migrations"
    applied = {row[0] for row in conn.execute(
        "SELECT name FROM schema_migrations"
    ).fetchall()}

    results = []
    pending = sorted(migrations_dir.glob("*_up.sql"))

    for f in pending:
        if f.name in applied:
            continue

        sql = f.read_text()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (f.name, utcnow()),
            )
            conn.commit()
            results.append({"name": f.name, "status": "applied"})
        except Exception as e:
            conn.rollback()
            results.append({"name": f.name, "status": "failed", "error": str(e)})
            break

    applied_count = sum(1 for r in results if r["status"] == "applied")
    failed_count = sum(1 for r in results if r["status"] == "failed")

    return {
        "command": "migrate",
        "applied": applied_count,
        "failed": failed_count,
        "total": len(pending),
        "already_applied": len(pending) - applied_count - failed_count,
        "results": results,
    }


def format_migrate_human(result: dict) -> str:
    lines = [f"Database migrations ({result['applied']} applied)"]

    for r in result.get("results", []):
        if r["status"] == "applied":
            lines.append(f"  ✓ {r['name']}")
        elif r["status"] == "failed":
            lines.append(f"  ✗ {r['name']}: {r['error']}")

    if result["failed"] == 0 and result["applied"] == 0:
        lines.append("  No pending migrations")

    return "\n".join(lines)

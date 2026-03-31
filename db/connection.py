"""SQLite connection management with WAL mode for the Ralph Loop Orchestrator."""

import sqlite3
from pathlib import Path
from typing import Optional


def get_orch_dir() -> Path:
    """Return the .orch directory path (resolved from current working directory)."""
    return Path.cwd() / ".orch"


def get_db_path() -> Path:
    """Return the path to the orch database."""
    return get_orch_dir() / "orch.db"


def is_initialized() -> bool:
    """Check whether the orchestrator has been initialized in this directory."""
    return get_db_path().exists()


def get_connection() -> sqlite3.Connection:
    """Return a WAL-mode SQLite connection to the orch database.

    Raises:
        RuntimeError: if the database has not been initialized (run `orch init` first).
    """
    db_path = get_db_path()
    if not db_path.exists():
        raise RuntimeError(
            f"Orchestrator not initialized. Run `orch init` in {db_path.parent} first."
        )

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database(db_path: Optional[Path] = None) -> Path:
    """Initialize the orchestrator database.

    Creates the .orch directory and the orch.db file with the full schema.

    Returns:
        The path to the created database file.
    """
    from .schema import INIT_SQL

    if db_path is None:
        db_path = get_db_path()

    orch_dir = db_path.parent
    orch_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(INIT_SQL)
    conn.close()

    return db_path

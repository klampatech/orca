"""orch init — Initialize the orchestrator in the current directory."""

from db.connection import get_orch_dir, init_database
from utils.identity import ensure_loop_id


def handle_init(args=None) -> dict:
    """Initialize the orchestrator.

    Creates the .orch/ directory, the SQLite database, and ensures
    the default loop identity exists.

    Returns:
        A result dict with 'command', 'status', 'orch_dir', 'db_path'.
    """
    orch_dir = get_orch_dir()
    db_path = init_database()

    try:
        ensure_loop_id()
    except OSError:
        pass

    return {
        "command": "init",
        "status": "success",
        "orch_dir": str(orch_dir),
        "db_path": str(db_path),
    }


def format_init_human(result: dict) -> str:
    return (
        f"Ralph Loop Orchestrator initialized at {result['orch_dir']}\n"
        f"Database: {result['db_path']} (WAL mode)\n"
        "Ready to coordinate Ralph loops."
    )

"""Loop identity resolution for the Ralph Loop Orchestrator.

Loop ID resolution order:
1. --loop-id command-line argument
2. ORCH_LOOP_ID environment variable
3. ~/.orch/loop_id file (generated on first use)
"""

import os
import uuid
from pathlib import Path


def get_default_loop_id_path() -> Path:
    """Return the path where the default loop ID is stored."""
    home = Path.home()
    return home / ".orch" / "loop_id"


def ensure_loop_id(path: Path | None = None) -> str:
    """Ensure a loop ID exists, creating one if necessary.

    Returns:
        The loop ID string.
    """
    if path is None:
        path = get_default_loop_id_path()

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        loop_id = str(uuid.uuid4())
        path.write_text(loop_id + "\n")

    return path.read_text().strip()


def resolve_loop_id(loop_id_arg: str | None) -> str:
    """Resolve a loop ID using the priority: arg -> env -> default file.

    Args:
        loop_id_arg: Value passed via --loop-id CLI argument.

    Returns:
        The resolved loop ID string.

    Raises:
        RuntimeError: if no loop ID can be resolved.
    """
    if loop_id_arg:
        return loop_id_arg

    env_id = os.environ.get("ORCH_LOOP_ID")
    if env_id:
        return env_id

    try:
        return ensure_loop_id()
    except OSError:
        pass

    raise RuntimeError(
        "No loop ID found. Set --loop-id, ORCH_LOOP_ID env var, or "
        "ensure ~/.orch/loop_id exists. Run `orch init` first."
    )

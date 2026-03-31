"""orch reclaim — Reclaim tasks with expired heartbeats."""


def handle_reclaim(args) -> dict:
    """Reclaim stale task runs whose heartbeat has expired.

    Returns:
        A result dict with count of reclaimed tasks.
    """
    from models.task_run import reclaim_stale

    reclaimed = reclaim_stale()

    return {
        "command": "reclaim",
        "status": "success",
        "reclaimed_count": reclaimed,
    }


def format_reclaim_human(result: dict) -> str:
    count = result["reclaimed_count"]
    if count == 0:
        return "No stale tasks to reclaim."
    return f"Reclaimed {count} stale task(s)."

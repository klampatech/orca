"""UTC timestamp utilities for the Ralph Loop Orchestrator."""

from datetime import datetime, timezone


def utcnow() -> str:
    """Return the current UTC time as an ISO8601 string with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

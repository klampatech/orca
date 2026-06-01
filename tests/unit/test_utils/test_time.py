"""Tests for the time utility module."""

from __future__ import annotations

from datetime import datetime, timezone

from orca.utils.time import utcnow


class TestUtcnow:
    """Tests for the utcnow() function."""

    def test_returns_string(self):
        """Should return a string."""
        result = utcnow()
        assert isinstance(result, str)

    def test_ends_with_z(self):
        """Should end with 'Z' suffix for UTC."""
        result = utcnow()
        assert result.endswith("Z")

    def test_iso_format(self):
        """Should be parseable as ISO8601."""
        result = utcnow()
        # Replace Z with +00:00 for parsing
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert isinstance(parsed, datetime)

    def test_is_utc(self):
        """Should represent UTC timezone."""
        result = utcnow()
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.tzinfo == timezone.utc

    def test_recent_timestamp(self):
        """Should be close to current time (within 5 seconds)."""
        result = utcnow()
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        # Allow 5 second tolerance for test execution time
        diff = abs((now - parsed).total_seconds())
        assert diff < 5

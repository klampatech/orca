"""Tests for the identity utility module."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from orca.utils.identity import (
    ensure_loop_id,
    get_default_loop_id_path,
    resolve_loop_id,
)


class TestGetDefaultLoopIdPath:
    """Tests for get_default_loop_id_path()."""

    def test_returns_path(self):
        """Should return a Path object."""
        result = get_default_loop_id_path()
        assert isinstance(result, Path)

    def test_points_to_home_orch(self):
        """Path should be in user's home directory under .orch."""
        result = get_default_loop_id_path()
        assert result.parts[-2:] == (".orch", "loop_id")

    def test_filename_is_loop_id(self):
        """Filename should be 'loop_id'."""
        result = get_default_loop_id_path()
        assert result.name == "loop_id"


class TestEnsureLoopId:
    """Tests for ensure_loop_id()."""

    def test_creates_file_if_not_exists(self, temp_dir):
        """Should create the loop_id file if it doesn't exist."""
        path = temp_dir / "loop_id"
        result = ensure_loop_id(path)

        assert path.exists()
        assert isinstance(result, str)

    def test_returns_uuid_format(self, temp_dir):
        """Should return a UUID-formatted string."""
        path = temp_dir / "loop_id"
        result = ensure_loop_id(path)

        # Should be valid UUID
        uuid_obj = uuid.UUID(result)
        assert str(uuid_obj) == result

    def test_returns_existing_if_exists(self, temp_dir):
        """Should return existing ID if file already exists."""
        path = temp_dir / "loop_id"
        existing_id = str(uuid.uuid4())
        path.write_text(existing_id + "\n")

        result = ensure_loop_id(path)

        assert result == existing_id

    def test_multiple_calls_same_id(self, temp_dir):
        """Multiple calls should return the same ID."""
        path = temp_dir / "loop_id"

        id1 = ensure_loop_id(path)
        id2 = ensure_loop_id(path)

        assert id1 == id2


class TestResolveLoopId:
    """Tests for resolve_loop_id()."""

    def test_returns_arg_if_provided(self):
        """Should return the argument if provided."""
        arg = "test-loop-id-123"
        result = resolve_loop_id(arg)

        assert result == arg

    def test_returns_env_var_if_arg_none(self, monkeypatch):
        """Should return ORCH_LOOP_ID env var if arg is None."""
        test_id = "env-loop-id-456"
        monkeypatch.setenv("ORCH_LOOP_ID", test_id)

        result = resolve_loop_id(None)

        assert result == test_id

    def test_prefers_arg_over_env(self, monkeypatch):
        """CLI argument should take precedence over env var."""
        monkeypatch.setenv("ORCH_LOOP_ID", "env-id")
        result = resolve_loop_id("arg-id")

        assert result == "arg-id"

    def test_raises_if_no_id_available(self, monkeypatch):
        """Should raise RuntimeError if no ID can be resolved."""
        # Ensure env var is not set
        monkeypatch.delenv("ORCH_LOOP_ID", raising=False)

        # Mock ensure_loop_id to raise OSError (simulating no file access)
        import orca.utils.identity

        original_ensure = orca.utils.identity.ensure_loop_id

        def mock_ensure(path=None):
            raise OSError("Simulated file access error")

        monkeypatch.setattr(orca.utils.identity, "ensure_loop_id", mock_ensure)

        with pytest.raises(RuntimeError, match="No loop ID found"):
            resolve_loop_id(None)

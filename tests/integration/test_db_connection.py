"""Integration tests for the database connection module."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest


class TestGetOrchDir:
    """Tests for get_orch_dir()."""

    def test_returns_path_in_cwd(self, monkeypatch, tmp_path):
        """Should return .orch directory in current working directory."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import get_orch_dir

        result = get_orch_dir()

        assert isinstance(result, Path)
        assert result.parts[-1] == ".orch"

    def test_resolves_from_cwd(self, monkeypatch, tmp_path):
        """Path should resolve from current working directory."""
        subdir = tmp_path / "project"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        from orca.db.connection import get_orch_dir

        result = get_orch_dir()

        assert result.parent == subdir


class TestGetDbPath:
    """Tests for get_db_path()."""

    def test_returns_orch_db_path(self, monkeypatch, tmp_path):
        """Should return path to orch.db in .orch directory."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import get_db_path

        result = get_db_path()

        assert result.name == "orch.db"
        assert result.parent.name == ".orch"


class TestIsInitialized:
    """Tests for is_initialized()."""

    def test_returns_false_when_not_initialized(self, monkeypatch, tmp_path):
        """Should return False if orch.db doesn't exist."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import is_initialized

        assert is_initialized() is False

    def test_returns_true_when_initialized(self, monkeypatch, tmp_path):
        """Should return True if orch.db exists."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import init_database, is_initialized

        init_database()
        assert is_initialized() is True


class TestInitDatabase:
    """Tests for init_database()."""

    def test_creates_orch_dir(self, tmp_path):
        """Should create .orch directory if it doesn't exist."""
        from orca.db.connection import init_database

        db_path = tmp_path / ".orch" / "orch.db"
        result = init_database(db_path)

        assert result.exists()
        assert result.parent.exists()

    def test_creates_database_file(self, tmp_path):
        """Should create the database file."""
        from orca.db.connection import init_database

        db_path = tmp_path / ".orch" / "orch.db"
        init_database(db_path)

        assert db_path.exists()

    def test_creates_tables(self, tmp_path):
        """Should create all required tables."""
        from orca.db.connection import init_database

        db_path = tmp_path / ".orch" / "orch.db"
        init_database(db_path)

        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()

        table_names = [t[0] for t in tables]
        assert "tasks" in table_names
        assert "task_runs" in table_names
        assert "loops" in table_names
        assert "hidden_scenario_runs" in table_names

    def test_creates_indexes(self, tmp_path):
        """Should create required indexes."""
        from orca.db.connection import init_database

        db_path = tmp_path / ".orch" / "orch.db"
        init_database(db_path)

        conn = sqlite3.connect(str(db_path))
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        conn.close()

        index_names = [i[0] for i in indexes]
        assert len(index_names) > 0

    def test_sets_wal_mode(self, tmp_path):
        """Database should use WAL journal mode."""
        from orca.db.connection import init_database

        db_path = tmp_path / ".orch" / "orch.db"
        init_database(db_path)

        conn = sqlite3.connect(str(db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()

        assert mode.upper() == "WAL"

    def test_returns_db_path(self, tmp_path):
        """Should return the path to the created database."""
        from orca.db.connection import init_database

        db_path = tmp_path / ".orch" / "orch.db"
        result = init_database(db_path)

        assert result == db_path


class TestGetConnection:
    """Tests for get_connection()."""

    def test_raises_when_not_initialized(self, monkeypatch, tmp_path):
        """Should raise RuntimeError if database doesn't exist."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import get_connection

        with pytest.raises(RuntimeError, match="not initialized"):
            get_connection()

    def test_returns_connection_when_initialized(self, monkeypatch, tmp_path):
        """Should return a valid SQLite connection."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import get_connection, init_database

        init_database()
        conn = get_connection()

        assert isinstance(conn, sqlite3.Connection)

    def test_connection_uses_wal_mode(self, monkeypatch, tmp_path):
        """Connection should have WAL mode enabled."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import get_connection, init_database

        init_database()
        conn = get_connection()

        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.upper() == "WAL"

    def test_connection_enables_foreign_keys(self, monkeypatch, tmp_path):
        """Connection should have foreign_keys enabled."""
        monkeypatch.chdir(tmp_path)

        from orca.db.connection import get_connection, init_database

        init_database()
        conn = get_connection()

        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

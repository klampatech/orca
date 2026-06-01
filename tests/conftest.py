"""Pytest configuration and shared fixtures for Orca Orchestrator tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Provide a temporary directory that auto-cleans up."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def db_path(temp_dir):
    """Provide a temporary database path for tests (as Path object).
    
    Uses 'orch.db' to match the production database filename.
    """
    return temp_dir / ".orch" / "orch.db"


@pytest.fixture
def initialized_db(db_path, temp_dir, monkeypatch):
    """Provide an initialized database.
    
    Changes to temp_dir and creates the database.
    """
    # Change to temp_dir so orca uses it as CWD
    monkeypatch.chdir(temp_dir)
    
    from orca.db.connection import init_database
    
    init_database(db_path)
    return db_path


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def sample_spec():
    """Provide a sample spec for testing."""
    return {
        "name": "Test Feature",
        "description": "A test feature",
        "priority": "mustHave",
        "children": [],
    }


@pytest.fixture
def sample_ir_data():
    """Provide sample spec.ir.json data."""
    return {
        "version": "1.0",
        "name": "Test Feature",
        "description": "A test feature for validation",
        "priority": "mustHave",
        "criteria": [
            {"id": "ac1", "description": "First acceptance criterion", "status": "pending"},
        ],
        "children": [],
    }

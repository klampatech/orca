"""Tests for the orca logging utility."""

import json
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging state before each test.

    The logging module caches state based on CWD. Since tests use
    temp directories that change, we need to reset the cache.
    """
    from orca.utils.logging import reset_logging_state

    reset_logging_state()
    yield
    reset_logging_state()  # Also reset after test


class TestLogging:
    """Test the logging module."""

    def test_make_entry(self, temp_dir, initialized_db):
        """Test entry creation with standard fields."""
        from orca.utils.logging import _make_entry, _session_id

        entry = _make_entry("test_event", {"key": "value"})

        assert "timestamp" in entry
        assert "session" in entry
        assert entry["session"] == _session_id
        assert entry["event"] == "test_event"
        assert entry["data"]["key"] == "value"

    def test_log_refine_start(self, temp_dir, initialized_db):
        """Test refine_start logging."""
        from orca.utils.logging import log_refine_start, query_logs

        log_refine_start("/path/to/spec.md", max_iterations=5)

        entries = query_logs(event_filter="refine_start", limit=1)
        assert len(entries) == 1
        assert entries[0]["data"]["spec_path"] == "/path/to/spec.md"
        assert entries[0]["data"]["max_iterations"] == 5

    def test_log_decompose(self, temp_dir, initialized_db):
        """Test decompose logging."""
        from orca.utils.logging import (
            log_decompose_start,
            log_decompose_complete,
            query_logs,
        )

        log_decompose_start("/path/to/spec.json", "ir")
        log_decompose_complete(
            spec_path="/path/to/spec.json",
            total_tasks=10,
            feature_ids=["FEAT-001", "FEAT-002"],
            spec_root_id="root-123",
        )

        entries = query_logs(limit=5)
        start_entries = [e for e in entries if e["event"] == "decompose_start"]
        complete_entries = [e for e in entries if e["event"] == "decompose_complete"]

        assert len(start_entries) == 1
        assert start_entries[0]["data"]["mode"] == "ir"

        assert len(complete_entries) == 1
        assert complete_entries[0]["data"]["total_tasks"] == 10

    def test_log_loop_events(self, temp_dir, initialized_db):
        """Test loop lifecycle logging."""
        from orca.utils.logging import (
            log_loop_start,
            log_loop_end,
            get_loop_events,
        )

        loop_id = "test-loop-123"
        log_loop_start(loop_id)
        log_loop_end(loop_id, duration_seconds=60.5, tasks_processed=5)

        events = get_loop_events(loop_id)
        assert len(events) == 2

        start_event = [e for e in events if e["event"] == "loop_start"][0]
        assert start_event["data"]["loop_id"] == loop_id

        end_event = [e for e in events if e["event"] == "loop_end"][0]
        assert end_event["data"]["duration_seconds"] == 60.5
        assert end_event["data"]["tasks_processed"] == 5

    def test_log_task_events(self, temp_dir, initialized_db):
        """Test task claim/complete/fail logging."""
        from orca.utils.logging import (
            log_task_claim,
            log_task_complete,
            log_task_fail,
            get_task_events,
        )

        task_id = "task-456"
        loop_id = "loop-789"

        log_task_claim(task_id, loop_id, priority=10)
        log_task_complete(task_id, loop_id, duration_seconds=30.0, exit_status=0)
        log_task_fail(task_id, loop_id, "Test error")

        events = get_task_events(task_id)
        assert len(events) == 3

        assert events[0]["event"] == "task_claim"
        assert events[1]["event"] == "task_complete"
        assert events[2]["event"] == "task_fail"

    def test_log_inference(self, temp_dir, initialized_db):
        """Test inference logging with prompt/response."""
        from orca.utils.logging import log_inference, query_logs

        log_inference(
            prompt="Test prompt",
            response="Test response",
            duration_ms=1500,
            success=True,
        )

        entries = query_logs(event_filter="inference", limit=1)
        assert len(entries) == 1
        assert entries[0]["data"]["prompt_preview"] == "Test prompt"
        assert entries[0]["data"]["response_preview"] == "Test response"
        assert entries[0]["data"]["duration_ms"] == 1500
        assert entries[0]["data"]["success"] is True

    def test_log_inference_truncation(self, temp_dir, initialized_db):
        """Test that long prompts/responses are truncated."""
        from orca.utils.logging import log_inference, query_logs

        long_prompt = "x" * 60000  # 60k chars
        long_response = "y" * 60000

        log_inference(
            prompt=long_prompt,
            response=long_response,
            duration_ms=100,
            success=True,
        )

        entries = query_logs(event_filter="inference", limit=1)
        assert len(entries) == 1

        # Check truncation to 500 chars + "..."
        data = entries[0]["data"]
        assert len(data["prompt_preview"]) == 503  # 500 + "..."
        assert data["prompt_preview"].endswith("...")

    def test_log_validation(self, temp_dir, initialized_db):
        """Test validation logging."""
        from orca.utils.logging import (
            log_validation_start,
            log_validation_complete,
            log_validation_error,
        )

        log_validation_start("FEAT-001")
        log_validation_complete(
            feature_id="FEAT-001",
            scenarios_found=10,
            scenarios_passed=8,
            scenarios_failed=1,
            scenarios_errored=1,
            duration_ms=2500,
        )
        log_validation_error("FEAT-002", "Code not found")

    def test_log_terminal_output(self, temp_dir, initialized_db):
        """Test terminal output logging."""
        from orca.utils.logging import log_terminal_output, query_logs

        log_terminal_output(
            source="pi",
            command="pi -p test",
            stdout="Some output",
            stderr="Some error",
            exit_code=1,
            duration_ms=500,
        )

        entries = query_logs(event_filter="terminal_output", limit=1)
        assert len(entries) == 1
        assert entries[0]["data"]["source"] == "pi"
        assert entries[0]["data"]["exit_code"] == 1

    def test_log_terminal_output_truncation(self, temp_dir, initialized_db):
        """Test terminal output truncation."""
        from orca.utils.logging import log_terminal_output, query_logs

        long_output = "z" * 15000

        log_terminal_output(
            source="pytest",
            command="pytest tests/",
            stdout=long_output,
            stderr=long_output,
            exit_code=0,
            duration_ms=1000,
        )

        entries = query_logs(event_filter="terminal_output", limit=1)
        data = entries[0]["data"]

        # Check truncation to 10000 chars + "..."
        assert len(data["stdout_preview"]) == 10003  # 10000 + "..."
        assert data["stdout_preview"].endswith("...")

    def test_query_logs_with_filters(self, temp_dir, initialized_db):
        """Test querying logs with various filters."""
        from orca.utils.logging import (
            log_refine_start,
            log_loop_start,
            query_logs,
        )

        # Log multiple event types
        log_refine_start("spec1.md", 5)
        log_loop_start("loop-1")

        # Query all
        all_entries = query_logs(limit=10)
        assert len(all_entries) >= 2

        # Query by event
        refine_entries = query_logs(event_filter="refine_start", limit=10)
        assert all(e["event"] == "refine_start" for e in refine_entries)

    def test_log_file_rotation(self, temp_dir, initialized_db):
        """Test that logs are written to correct date-based file."""
        from orca.utils.logging import _get_log_file

        log_file = _get_log_file()
        assert "orca-2026-" in str(log_file)
        assert str(log_file).endswith(".log")

    def test_session_id_consistency(self, temp_dir, initialized_db):
        """Test that session IDs are consistent within a session."""
        from orca.utils.logging import _session_id, _make_entry

        # All entries in same session should have same ID
        entry1 = _make_entry("event1", {})
        entry2 = _make_entry("event2", {})

        assert entry1["session"] == entry2["session"]
        assert entry1["session"] == _session_id
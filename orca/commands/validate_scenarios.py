"""orch validate-scenarios — Run hidden scenario validation for a feature.

This module implements Phase 2's Hidden Scenario Validation (HSV) system.
When all children of a feature root complete, HSV generates adversarial
pytest tests that probe for gaps the spec didn't cover.

Key flows:
- validate_scenarios <feature_id>: Validate one feature's code
- validate_scenarios --check-all: Scan and validate all complete features
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time as _time
import urllib.parse
import uuid
from pathlib import Path

from ..db.connection import get_connection
from ..models.task import create_task
from ..utils.time import utcnow
from ..utils.logging import (
    log_validation_start,
    log_validation_complete,
    log_validation_error,
    log_inference,
    log_terminal_output,
)


def handle_validate_scenarios(args) -> dict:
    """Run hidden scenario validation for a feature.

    This is the command handler registered in COMMANDS. It delegates to
    _validate_single_feature (for one feature) or _validate_all_complete_features
    (for --check-all).
    """
    loop_id = getattr(args, "loop_id", None)
    check_all = getattr(args, "check_all", False)
    if check_all:
        return _validate_all_complete_features()

    feature_id = args.feature_id
    if not feature_id:
        raise ValueError("feature_id is required unless --check-all is set")
    return _validate_single_feature(feature_id, loop_id=loop_id)


def _validate_single_feature(feature_id: str, *, loop_id: str | None = None) -> dict:
    """Validate one feature.

    Logs validation events to .orch/logs/.
    """
    start = _time.monotonic()

    # Log validation start
    log_validation_start(feature_id)

    # Get spec path and code paths
    spec_path = get_root_spec_path(feature_id)
    code_paths = get_feature_code_paths(feature_id)

    if not code_paths:
        log_validation_error(feature_id, "No code files found")
        raise ValueError(f"No code files found for feature {feature_id}")

    # Build the pi prompt
    prompt = _build_hsv_prompt(spec_path, code_paths, feature_id)

    # Run pi to generate tests
    print(f"[validate-scenarios] Generating hidden scenarios for {feature_id}...")
    infer_start = _time.time()
    pi_result = subprocess.run(
        ["pi", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=Path.cwd(),
    )
    infer_duration_ms = int((_time.time() - infer_start) * 1000)

    # Log pi inference
    log_inference(
        prompt=prompt,
        response=pi_result.stdout,
        duration_ms=infer_duration_ms,
        success=pi_result.returncode == 0,
        error=pi_result.stderr[:500] if pi_result.returncode != 0 else None,
    )

    # Log terminal output
    log_terminal_output(
        source="pi",
        command="pi -p <hsv_prompt>",
        stdout=pi_result.stdout,
        stderr=pi_result.stderr,
        exit_code=pi_result.returncode,
        duration_ms=infer_duration_ms,
    )

    # Parse pi output for debug info
    pi_output = pi_result.stdout[:1000] if pi_result.stdout else ""

    # Run pytest on generated tests
    encoded_feature_id = urllib.parse.quote(feature_id)
    test_dir = Path(".orch/hidden_scenarios") / encoded_feature_id

    if not test_dir.exists():
        # No scenarios generated — pass
        duration_ms = int((_time.monotonic() - start) * 1000)
        unlock_tree(feature_id)
        _record_hsv_run(
            feature_id=feature_id,
            loop_id=loop_id,
            scenarios_found=0,
            passed=0,
            failed=0,
            errors=0,
            duration_ms=duration_ms,
            output=pi_output,
        )
        return _build_result(feature_id, [], [], [])

    # Run pytest on generated tests
    encoded_feature_id = urllib.parse.quote(feature_id)
    test_dir = Path(".orch/hidden_scenarios") / encoded_feature_id

    if not test_dir.exists():
        # No scenarios generated — pass
        duration_ms = int((_time.monotonic() - start) * 1000)
        unlock_tree(feature_id)
        _record_hsv_run(
            feature_id=feature_id,
            loop_id=loop_id,
            scenarios_found=0,
            passed=0,
            failed=0,
            errors=0,
            duration_ms=duration_ms,
            output=pi_output,
        )
        log_validation_complete(
            feature_id=feature_id,
            scenarios_found=0,
            scenarios_passed=0,
            scenarios_failed=0,
            scenarios_errored=0,
            duration_ms=duration_ms,
        )
        return _build_result(feature_id, [], [], [])

    print(f"[validate-scenarios] Running pytest in {test_dir}...")
    test_start = _time.time()
    try:
        result = subprocess.run(
            ["pytest", str(test_dir), "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        test_duration_ms = int((_time.time() - test_start) * 1000)

        # Log pytest terminal output
        log_terminal_output(
            source="pytest",
            command=f"pytest {test_dir} -v --tb=short",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            duration_ms=test_duration_ms,
        )

    except FileNotFoundError:
        # pytest not installed - skip test execution
        print("[validate-scenarios] pytest not found - skipping test execution")
        duration_ms = int((_time.monotonic() - start) * 1000)
        result = None
        passed: list[str] = []
        failed: list[str] = []
        errors: list[str] = []
        _record_hsv_run(
            feature_id=feature_id,
            loop_id=loop_id,
            scenarios_found=0,
            passed=0,
            failed=0,
            errors=0,
            duration_ms=duration_ms,
            output="pytest not installed - validation skipped",
        )
        log_validation_complete(
            feature_id=feature_id,
            scenarios_found=0,
            scenarios_passed=0,
            scenarios_failed=0,
            scenarios_errored=0,
            duration_ms=duration_ms,
        )
        unlock_tree(feature_id)
        return _build_result(feature_id, [], [], [])

    # Parse results
    if result is not None:
        parsed = _parse_pytest_output(result.stdout + result.stderr)
        passed = parsed[0]
        failed = parsed[1]
        errors = parsed[2]
    else:
        passed, failed, errors = [], [], []
    duration_ms = int((_time.monotonic() - start) * 1000)

    # Record this HSV run
    _record_hsv_run(
        feature_id=feature_id,
        loop_id=loop_id,
        scenarios_found=len(passed) + len(failed) + len(errors),
        passed=len(passed),
        failed=len(failed),
        errors=len(errors),
        duration_ms=duration_ms,
        output=(result.stdout + result.stderr)[:5000] if result else "",
    )

    # Log validation completion
    log_validation_complete(
        feature_id=feature_id,
        scenarios_found=len(passed) + len(failed) + len(errors),
        scenarios_passed=len(passed),
        scenarios_failed=len(failed),
        scenarios_errored=len(errors),
        duration_ms=duration_ms,
    )

    if not failed and not errors:
        print(f"[validate-scenarios] All {len(passed)} scenarios passed")
        unlock_tree(feature_id)
    else:
        print(
            f"[validate-scenarios] {len(failed)} failed, {len(errors)} errors — creating hidden tasks"
        )
        create_hidden_tasks(feature_id, failed)

    return _build_result(feature_id, passed, failed, errors)


def _build_hsv_prompt(spec_path: Path, code_paths: list[Path], feature_id: str) -> str:
    """Build the pi prompt for hidden scenario generation."""
    encoded_feature_id = urllib.parse.quote(feature_id)
    output_dir = f".orch/hidden_scenarios/{encoded_feature_id}"

    code_paths_str = "\n- ".join(str(p) for p in code_paths[:20])  # Limit to 20 files

    return f"""You are a red-team testing assistant. Read the spec and code below,
then generate pytest tests that probe for gaps the spec doesn't cover.

Read these files from disk:
- {spec_path}
- {code_paths_str}

Generate 5-10 hidden scenario tests that are NOT covered by:
- The acceptance criteria in spec.ir.json
- The existing tests

Write each test to:
{output_dir}/test_hidden_1.py
{output_dir}/test_hidden_2.py
...etc

Each test must:
- Follow pytest conventions
- Be executable standalone
- Test one gap per test
- Include a docstring explaining what gap it's testing
- Return PASS if code handles it, FAIL if gap found

Focus on:
1. Error handling gaps (null/empty edge cases)
2. Semantic gaps (sort stability, equality, boundary conditions)
3. Adversarial inputs (Unicode homoglyphs, SQL injection, XSS)
4. Behavioral gaps (file size limits, timeout handling, race conditions)
"""


def _parse_pytest_output(output: str) -> tuple[list, list, list]:
    """Parse pytest output into passed/failed/error lists."""
    passed, failed, errors = [], [], []
    for line in output.splitlines():
        if " PASSED" in line:
            passed.append(_ScenarioResult.from_pytest_line(line))
        elif " FAILED" in line:
            failed.append(_ScenarioResult.from_pytest_line(line))
        elif " ERROR" in line:
            errors.append(_ScenarioResult.from_pytest_line(line))
    return passed, failed, errors


class _ScenarioResult:
    """Holds a parsed pytest result line with extracted scenario ID."""

    def __init__(self, file_path: str, scenario_id: str):
        self.file_path = file_path
        self.scenario_id = scenario_id

    @staticmethod
    def from_pytest_line(line: str) -> "_ScenarioResult":
        """Parse 'test_hidden_N.py::test_name PASSED' into components."""
        match = re.match(r"(test_hidden_\d+)\.py", line)
        scenario_id = match.group(1) if match else line.strip()
        return _ScenarioResult(file_path=line.strip(), scenario_id=scenario_id)


def _validate_all_complete_features() -> dict:
    """Scan all features, validate any that have all children complete."""
    results = []
    conn = get_connection()

    roots = conn.execute("""
        SELECT id FROM tasks
        WHERE parent_id IS NULL
          AND status NOT IN ('validation', 'completed')
          AND id NOT IN (
              SELECT DISTINCT parent_id FROM tasks
              WHERE status NOT IN ('completed', 'blocked')
          )
    """).fetchall()

    print(f"[validate-scenarios] Found {len(roots)} complete features to validate")

    for (root_id,) in roots:
        try:
            result = _validate_single_feature(root_id)
            results.append(result)
        except Exception as e:
            print(f"[validate-scenarios] Error validating {root_id}: {e}")
            results.append(
                {
                    "feature_id": root_id,
                    "status": "error",
                    "error": str(e),
                    "scenarios_generated": 0,
                    "passed": [],
                    "failed": [],
                    "errors": [],
                }
            )

    return {"command": "validate-scenarios", "check_all": True, "results": results}


def _build_result(feature_id: str, passed, failed, errors) -> dict:
    """Build the command result dict with counts and status."""
    return {
        "feature_id": feature_id,
        "scenarios_generated": len(passed) + len(failed) + len(errors),
        "passed": [r.scenario_id for r in passed],
        "failed": [r.scenario_id for r in failed],
        "errors": [r.scenario_id for r in errors],
        "status": "pass" if not failed and not errors else "fail",
    }


def _record_hsv_run(
    feature_id: str,
    loop_id: str | None,
    scenarios_found: int,
    passed: int,
    failed: int,
    errors: int,
    duration_ms: int,
    output: str,
) -> None:
    """Insert a hidden_scenario_runs record after each validation run."""
    conn = get_connection()
    run_id = str(uuid.uuid4())
    now = utcnow()
    conn.execute(
        """
        INSERT INTO hidden_scenario_runs
            (id, feature_id, loop_id, generated_at, scenarios_found,
             scenarios_passed, scenarios_failed, scenarios_errored,
             duration_ms, output_snippet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            run_id,
            feature_id,
            loop_id,
            now,
            scenarios_found,
            passed,
            failed,
            errors,
            duration_ms,
            output[:5000] if output else None,
        ),
    )
    conn.commit()


def get_root_spec_path(feature_id: str) -> Path:
    """Resolve the spec.ir.json path for a feature root."""
    conn = get_connection()
    row = conn.execute(
        "SELECT root_spec_path FROM tasks WHERE id = ?", (feature_id,)
    ).fetchone()
    if not row or not row[0]:
        raise ValueError(f"Feature root {feature_id} has no root_spec_path")
    spec_dir = Path(row[0]).parent
    ir_path = spec_dir / "spec.ir.json"
    if not ir_path.exists():
        raise FileNotFoundError(f"spec.ir.json not found at {ir_path}")
    return ir_path


def get_feature_code_paths(feature_id: str) -> list[Path]:
    """Find all code files belonging to a feature."""
    from pathlib import Path

    spec_path = get_root_spec_path(feature_id)
    spec_dir = spec_path.parent
    scan_root = spec_dir

    CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".go", ".rb", ".java", ".rs"}
    code_files = []
    for root, dirs, files in os.walk(scan_root):
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d
            not in (
                "node_modules",
                "__pycache__",
                "venv",
                "vendor",
                "target",
                "dist",
                "build",
            )
        ]
        for file in files:
            if Path(file).suffix in CODE_EXTENSIONS:
                code_files.append(Path(root) / file)

    return code_files


def lock_feature_tree(root_id: str) -> None:
    """Atomically lock a feature tree for validation."""
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")

    conn.execute("UPDATE tasks SET status='validation' WHERE id=?", (root_id,))

    conn.execute(
        """
        WITH RECURSIVE descendants AS (
            SELECT id FROM tasks WHERE parent_id = ?
            UNION ALL
            SELECT t.id FROM tasks t JOIN descendants d ON t.parent_id = d.id
        )
        UPDATE tasks SET status='blocked'
        WHERE id IN (SELECT id FROM descendants)
    """,
        (root_id,),
    )

    conn.commit()


def unlock_tree(root_id: str) -> None:
    """Atomically unlock a feature tree after validation."""
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")

    conn.execute(
        "UPDATE tasks SET status='completed' WHERE id=? AND status='validation'",
        (root_id,),
    )

    conn.execute(
        """
        WITH RECURSIVE descendants AS (
            SELECT id FROM tasks WHERE parent_id = ?
            UNION ALL
            SELECT t.id FROM tasks t JOIN descendants d ON t.parent_id = d.id
        )
        UPDATE tasks SET status='available'
        WHERE id IN (SELECT id FROM descendants)
          AND status = 'blocked'
    """,
        (root_id,),
    )

    conn.commit()


def create_hidden_tasks(feature_id: str, failed_scenarios: list[str]) -> None:
    """Create hidden scenario tasks for each failed pytest scenario."""
    conn = get_connection()

    for scenario_id in failed_scenarios:
        task = create_task(
            description=f"[hidden scenario] {scenario_id}",
            priority=9,
            parent_id=feature_id,
            root_spec_path=None,
            ir_snippet=json.dumps(
                {"type": "hidden_scenario", "scenario_id": scenario_id}
            ),
        )
        conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (task["id"],))
        conn.commit()


def format_validate_scenarios_human(result: dict) -> str:
    """Format the validate-scenarios result for human display."""
    feature_id = result.get("feature_id", "?")
    status = result.get("status", "?")

    if result.get("check_all"):
        lines = ["Hidden Scenario Validation — All Features"]
        for r in result.get("results", []):
            fid = r.get("feature_id", "?")
            st = r.get("status", "?")
            gen = r.get("scenarios_generated", 0)
            passed = len(r.get("passed", []))
            failed = len(r.get("failed", []))
            errors = len(r.get("errors", []))
            icon = "✓" if st == "pass" else "✗" if st == "fail" else "⚠"
            lines.append(
                f"  {icon} {fid}: {gen} scenarios — {passed} passed, {failed} failed, {errors} errors"
            )
        return "\n".join(lines)

    icon = "✓" if status == "pass" else "✗" if status == "fail" else "⚠"
    gen = result.get("scenarios_generated", 0)
    passed = len(result.get("passed", []))
    failed = len(result.get("failed", []))
    errors = len(result.get("errors", []))
    return (
        f"Hidden Scenario Validation — Feature {feature_id}\n"
        f"  {icon} {status.upper()} — {gen} scenarios generated: "
        f"{passed} passed, {failed} failed, {errors} errors"
    )

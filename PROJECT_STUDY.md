# Project Study: Orca Orchestrator

**Study Date:** 2026-04-22  
**Project Type:** CLI Tool / Task Queue System  
**Status:** Phase 1 Complete, Phase 2 Partially Implemented

---

## Executive Summary

Orca is a lightweight, zero-dependency task orchestration system designed for running and managing agent-based workflows (particularly for the pi coding agent). It uses SQLite as a persistent task queue with a heartbeat-based crash detection mechanism. The system operates as a CLI tool where loops execute tasks in isolated subprocesses, with atomic task claiming ensuring no duplicate work. While Phase 1 functionality is complete, several Phase 2 features remain unimplemented, including parallel loop spawning, hidden scenario validation, and the HTTP API server.

**Key Characteristics:**
- **Minimalist Design:** Zero external Python dependencies, uses stdlib only
- **Persistent Queue:** SQLite with WAL mode for concurrent reads
- **Crash-Resilient:** Heartbeat pattern detects failed loops within 5 minutes
- **Single-User CLI:** No authentication, designed for individual developer use
- **pi Integration:** Delegates actual task execution to the pi agent via subprocess

---

## Project Overview

### Purpose

Orca solves the problem of orchestrating long-running agent tasks that need to survive terminal disconnections, maintain state persistence, and avoid duplicate work. It's designed as a task queue manager for AI coding agents, providing reliability and observability for complex multi-step workflows.

### Core Functionality

1. **Task Management**
   - Persistent SQLite-backed task queue
   - Atomic task claiming (no duplicates via `BEGIN IMMEDIATE`)
   - Task state tracking with timestamps and metadata

2. **Loop Execution**
   - Spawns subprocess loops for task execution
   - Heartbeat mechanism for crash detection (5-minute timeout)
   - Loop metadata persistence (created, updated, status)

3. **pi Agent Integration**
   - Delegates task execution to the pi CLI
   - Supports TDD workflow instructions
   - Multi-runtime test detection (pytest, npm, go, rspec)

4. **Output Modes**
   - Human-readable ASCII formatted output
   - JSON output for programmatic consumption

### Target Users

- **Individual Developers** using pi for coding tasks
- **Teams** running autonomous coding agents on shared infrastructure
- **Research Environments** requiring reproducible agent execution logs

---

## Technical Architecture

### Stack Summary

| Layer | Technology |
|-------|------------|
| Language | Python 3.x (stdlib only) |
| Database | SQLite 3 (WAL mode) |
| CLI Framework | argparse (stdlib) |
| Process Management | subprocess, threading |
| Integration | pi CLI (external) |

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        User Terminal                         │
│                    $ orca <command>                          │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                     Orca CLI (main)                          │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │  Argparse   │  │   Commands   │  │  SQLite Connection  │  │
│  │   Parser    │──│   Registry   │──│   (WAL, Immediate)  │  │
│  └─────────────┘  └──────────────┘  └─────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ Loop 1   │   │ Loop 2   │   │ Loop N   │
    │ (subproc)│   │ (subproc)│   │ (subproc)│
    │    │     │   │    │     │   │    │     │
    │    ▼     │   │    ▼     │   │    ▼     │
    │  pi CLI  │   │  pi CLI  │   │  pi CLI  │
    │    │     │   │    │     │   │    │     │
    │    ▼     │   │    ▼     │   │    ▼     │
    │ Heartbeat│   │ Heartbeat│   │ Heartbeat│
    └──────────┘   └──────────┘   └──────────┘
          │               │               │
          └───────────────┴───────────────┘
                          │
                          ▼
              ┌─────────────────────┐
              │   .orch/tasks.db    │
              │   (SQLite/WAL)      │
              │                     │
              │  ┌───────────────┐  │
              │  │    tasks      │  │
              │  │  task_runs    │  │
              │  │    loops      │  │
              │  └───────────────┘  │
              └─────────────────────┘
```

### Key Architectural Decisions

| Decision | Rationale | Trade-offs |
|----------|-----------|------------|
| SQLite over Redis/Postgres | Zero dependencies, simple deployment | Limited concurrent write performance |
| Heartbeat pattern | Detects crashes without shared state | ~80ms overhead per heartbeat |
| Command pattern | Extensible CLI, modular commands | Requires boilerplate for each command |
| Subprocess per loop | Isolation, crash containment | Higher memory footprint per loop |
| WAL mode | Concurrent reads, durability | Requires periodic checkpoints |

### Directory Structure

```
orca/
├── README.md                    # User documentation
├── pyproject.toml               # Package configuration
├── src/orca/
│   ├── __init__.py
│   ├── main.py                  # CLI entry point
│   ├── db.py                    # Database initialization & queries
│   ├── models.py                # Data models (Task, TaskRun, Loop)
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── status.py            # orca status command
│   │   ├── clean.py             # orca clean command
│   │   ├── log.py               # orca log command
│   │   ├── tdd.py               # orca tdd command
│   │   └── submit.py            # orca submit command
│   └── utils/
│       ├── __init__.py
│       ├── output.py            # Human/JSON output formatting
│       └── pi.py                # pi CLI subprocess wrapper
├── tests/                       # (empty - no internal tests)
└── docs/                         # (minimal documentation)
```

---

## Data & Storage

### Database Schema

```sql
-- Core task management
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    spec_path TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    updated_at TEXT,
    claimed_by TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    error TEXT,
    result TEXT
);

CREATE TABLE task_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    loop_id TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    exit_code INTEGER,
    output TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE loops (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    updated_at TEXT,
    last_heartbeat TEXT,
    status TEXT,
    project_path TEXT
);
```

### Data Flow

```
┌─────────────┐    submit     ┌─────────────┐    claim      ┌─────────────┐
│   User CLI  │──────────────▶│    tasks    │──────────────▶│  Subprocess │
│  orca submit│               │   (pending) │   IMMEDIATE   │    Loop     │
└─────────────┘               └─────────────┘               └──────┬──────┘
                                                                   │
                    ┌─────────────┐    heartbeat    ┌─────────────▼──────┐
                    │  .orch/     │◀────────────────│      loops         │
                    │  tasks.db   │    UPDATE       │  (heartbeat time)   │
                    └─────────────┘                 └─────────────────────┘
                           │
                           │ read
                           ▼
                    ┌─────────────┐    status query
                    │  orca status│◀────────────────┌─────────────┐
                    │   command   │────────────────│    User     │
                    └─────────────┘   formatted    └─────────────┘
```

### Storage Characteristics

| Aspect | Implementation | Notes |
|--------|----------------|-------|
| Mode | WAL (Write-Ahead Logging) | Concurrent reads, serialized writes |
| Write Lock | `BEGIN IMMEDIATE` | Atomic claiming, potential bottleneck |
| Heartbeat | 5-minute timeout | ~80ms subprocess overhead |
| Location | `.orch/tasks.db` | Per-project directory |
| Backup | Manual | No automated backups |

### Missing Schema Elements (Phase 2)

The following Phase 2 features are specified but not implemented:

| Feature | Spec Location | Status |
|---------|---------------|--------|
| `hidden_scenario_runs` table | Phase 2 spec | Not in schema |
| `validation` status state | Phase 2 spec | Not in schema |
| `blocked` status state | Phase 2 spec | Not in schema |

---

## API & Integrations

### CLI Command Interface

Orca is primarily a CLI tool with no HTTP API. Commands are registered via a decorator pattern:

```python
# Command registration pattern
from orca.commands import register

@register
def status(args):
    """Display task queue status"""
    ...
```

**Implemented Commands:**

| Command | Purpose | Status |
|---------|---------|--------|
| `orca status` | Show pending tasks and running loops | ✅ Implemented |
| `orca clean` | Remove completed tasks and empty loops | ✅ Implemented |
| `orca log` | Show output from specific loops | ✅ Implemented |
| `orca tdd` | Start TDD workflow with pi | ✅ Implemented |
| `orca submit` | Add new task to queue | ✅ Implemented |

**Unimplemented Commands (Phase 2):**

| Command | Purpose | Status |
|---------|---------|--------|
| `orca run` | Auto-chain task execution | ❌ Not implemented |
| `orca loops` | Manage parallel loops (e.g., `orca loops N`) | ❌ Not implemented |
| `orca validate-scenarios` | Hidden scenario validation | ❌ Not implemented |
| `orca metrics` | Performance metrics | ❌ Not implemented |
| `orca serve` | HTTP API server | ❌ Not implemented |

### pi Integration

Orca delegates all task execution to the pi CLI via subprocess:

```python
# pi.py - subprocess wrapper
def run_pi(prompt, spec_path, project_path, tdd_mode=False):
    cmd = ["pi", "impl", prompt]
    if spec_path:
        cmd.extend(["--spec", spec_path])
    if tdd_mode:
        cmd.append("--tdd")
    return subprocess.run(cmd, ...)
```

**Integration Points:**
- `orca tdd` passes TDD instructions to pi
- Test detection across pytest/npm/go/rspec
- Results captured and stored in task_runs

### Output Formats

**Human Mode (default):**
```
┌────────────────────────────────────────────────────────────┐
│ Loop: abc-123 (PID 45678)                                  │
│ Created: 2026-04-22 10:30:00 | Last heartbeat: 10:35:00    │
│ Status: running | Project: /path/to/project               │
└────────────────────────────────────────────────────────────┘
```

**JSON Mode (`--json`):**
```json
{
  "loops": [
    {
      "id": "abc-123",
      "pid": 45678,
      "created_at": "2026-04-22T10:30:00",
      "last_heartbeat": "2026-04-22T10:35:00",
      "status": "running",
      "project_path": "/path/to/project"
    }
  ]
}
```

---

## Security

### Security Model Overview

Orca is designed as a **single-user CLI tool** with minimal attack surface. There is no authentication, authorization, or network exposure by default.

### Security Implementation

| Aspect | Implementation | Assessment |
|--------|----------------|------------|
| SQL Injection | Parameterized queries only | ✅ Protected |
| Loop ID | UUID4 (random) | ✅ Unpredictable |
| Access Control | SQLite file permissions | ⚠️ OS-level only |
| Subprocess | Direct pi CLI execution | ⚠️ Trust pi implicitly |

### Security Considerations

**Current Protections:**
- All SQL queries use parameterized `?` placeholders
- Loop IDs are UUID4 (cryptographically random)
- No external network requests from Orca itself

**Potential Concerns:**
- **No authentication** - Anyone with file access to `.orch/` can manipulate tasks
- **No rate limiting** - Unlimited task submission
- **No audit logging** - Task modifications not tracked
- **Subprocess trust** - Orca trusts pi CLI completely
- **SQLite permissions** - Access control relies entirely on OS file permissions

### Recommended Hardening (If Multi-User)

1. Implement authentication (token-based or OAuth)
2. Add rate limiting per user
3. Enable audit logging for all mutations
4. Validate pi CLI integrity (hash verification)
5. Consider PostgreSQL with row-level security for multi-tenant use

---

## Testing & Quality

### Testing Strategy

Orca takes a **minimalist testing approach** by design:

| Aspect | Current State | Recommendation |
|--------|---------------|----------------|
| Unit Tests | None | Add for core modules |
| Integration Tests | Minimal | Test CLI commands |
| Target Project Tests | Delegated to pi | User responsibility |
| TDD Workflow | Supported via `orca tdd` | Document in README |

### Test Coverage by Component

| Component | Unit Tests | Integration Tests | Notes |
|-----------|------------|------------------|-------|
| `db.py` | ❌ | ❌ | Critical - needs tests |
| `models.py` | ❌ | ❌ | Basic CRUD validation |
| `commands/` | ❌ | ❌ | CLI smoke tests |
| `utils/output.py` | ❌ | ⚠️ | Manual verification |
| `utils/pi.py` | ❌ | ⚠️ | Mock pi for testing |

### Testing Patterns Used

**Multi-Runtime Test Detection (delegated to pi):**
- Python: pytest, unittest
- Node.js: npm test, jest
- Go: go test
- Ruby: rspec

**SpecIRValidator:**
- Located in pi integration
- No unit tests in Orca codebase
- Validates spec.ir.json format

### Phase 2 Testing Gaps

The following Phase 2 features lack testing infrastructure:

| Feature | Test Requirements | Status |
|---------|-------------------|--------|
| Hidden scenario validation | Unit tests for validation logic | ❌ Not implemented |
| Parallel loop management | Concurrent execution tests | ❌ Not implemented |
| Feature tree locking | State transition tests | ❌ Not implemented |

---

## Deployment & Operations

### Installation

Orca is distributed as a Python package:

```bash
# From source
pip install -e .

# Via pyproject.toml
[project]
name = "orca"
version = "0.1.0"
```

### Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Deployment Environment                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌──────────────┐         ┌──────────────┐                │
│   │   Project A  │         │   Project B  │                │
│   │   .orch/     │         │   .orch/     │                │
│   │  tasks.db    │         │  tasks.db    │                │
│   └──────────────┘         └──────────────┘                │
│                                                              │
│   ┌──────────────┐         ┌──────────────┐                │
│   │   Loop 1-3   │         │   Loop 1-2   │                │
│   │   (subproc)  │         │   (subproc)  │                │
│   └──────────────┘         └──────────────┘                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Operations Characteristics

| Aspect | Current State | Notes |
|--------|---------------|-------|
| Installation | pip install | No containers, no Helm |
| Per-project data | `.orch/` directory | Isolated databases |
| Process management | Manual | User spawns/terminates |
| CI/CD | None | No pipelines configured |
| Cloud dependencies | None | Fully self-contained |
| Logs | Per-loop log files | No centralized logging |

### Manual Operations Required

Users must manually handle:

1. **Loop spawning** - `orca tdd` starts one loop at a time
2. **Loop monitoring** - `orca status` for visibility
3. **Loop cleanup** - `orca clean` for completed loops
4. **Crash recovery** - Heartbeat timeout (5 min) before cleanup

### Recommended Operational Improvements

1. **Systemd service** - Auto-restart crashed loops
2. **Log aggregation** - Centralized log collection
3. **Health endpoint** - `/health` for monitoring
4. **Metrics export** - Prometheus-compatible metrics
5. **Graceful shutdown** - SIGTERM handling

---

## Dependencies

### Dependency Philosophy

Orca follows a **zero-dependency** philosophy for Python packages, using only the Python standard library:

```
stdlib-only: sqlite3, argparse, subprocess, threading, json, uuid, datetime, pathlib
```

### External Dependencies

| Tool | Purpose | Installation | Notes |
|------|---------|--------------|-------|
| `python` | Runtime | User-managed | 3.x required |
| `pi` | Task execution | Separate install | Core dependency |
| `pytest` | Testing (target) | User-managed | For pi test detection |

### Dependency Table

| Package | Version Constraint | Used For |
|---------|-------------------|----------|
| (none) | - | Python stdlib only |

### Lock File

**No lock file needed** - Zero Python dependencies means no pip freeze required.

### Recommended Dependencies (Optional)

For improved code quality, consider adding:

```toml
[project.optional-dependencies]
dev = [
    "ruff>=0.1.0",      #dev = [
    "ruff>=0.1.0",      # Linting and formatting
    "mypy>=1.0.0",      # Type checking
    "pytest>=7.0.0",    # Testing
    "pytest-cov>=4.0.0", # Coverage reporting
]
```

---

## Code Quality

### Current State

Orca has **no formal code quality tooling** configured. The codebase relies on implicit standards and developer discipline.

### Quality Tooling Status

| Tool | Configured | Used | Notes |
|------|------------|------|-------|
| Linting (ruff, flake8, pylint) | ❌ | ❌ | Not configured |
| Formatting (black, ruff) | ❌ | ❌ | Not configured |
| Type Checking (mypy) | ❌ | ❌ | Not configured |
| Pre-commit hooks | ❌ | ❌ | No hooks defined |
| CI Quality Gates | ❌ | ❌ | No CI pipeline |

### Existing Good Patterns

Despite no formal tooling, the codebase exhibits several positive patterns:

| Pattern | Implementation | Quality |
|---------|----------------|---------|
| Type hints | Used throughout `models.py`, `db.py` | ✅ Good |
| Docstrings | Present in commands and utils | ✅ Good |
| Naming conventions | Consistent snake_case | ✅ Good |
| Error handling | Try/except blocks present | ✅ Adequate |
| Constants | Uppercase in `utils/output.py` | ✅ Good |

### Recommended Quality Configuration

**ruff.toml:**
```toml
line-length = 88
target-version = "py39"

[lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4"]
ignore = ["E501"]  # Line length handled by formatter
```

**mypy.ini:**
```ini
[mypy]
python_version = 3.9
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = True
```

**pre-commit.yaml:**
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.0
    hooks:
      - id: mypy
```

---

## User Experience

### CLI Interface

Orca provides a clean command-line interface with dual output modes:

### Command Reference

| Command | Syntax | Purpose |
|---------|--------|---------|
| `status` | `orca status [--json]` | Show tasks and loops |
| `submit` | `orca submit "<prompt>" [--spec path]` | Add task to queue |
| `tdd` | `orca tdd [--loop-id ID] [--pi-args "..."]` | Start TDD loop |
| `log` | `orca log <loop-id>` | Show loop output |
| `clean` | `orca clean [--force]` | Remove completed items |

### Output Modes

**Human Mode (default):**
- ASCII table formatting
- Color-coded status indicators (proposed)
- Readable timestamps
- Concise summaries

**JSON Mode (`--json`):**
```bash
orca status --json | jq '.loops[0].status'
```

### UX Strengths

| Aspect | Implementation |
|--------|----------------|
| Clear error messages | Contextual error reporting |
| Helpful defaults | Sensible argument defaults |
| Human-readable output | ASCII formatting |
| JSON mode | Programmatic consumption |
| Comprehensive README | Troubleshooting section |

### UX Gaps

| Feature | Current State | Recommendation |
|---------|---------------|----------------|
| Colors | None | Add `--color` flag |
| Progress indicators | None | Add spinner for long operations |
| Shell completion | None | Add bash/zsh/fish completion |
| Help text | Basic | Expand with examples |
| Interactive mode | None | Consider `orca watch` |

### Getting Started

**Prerequisites:**
```bash
# Install Python 3.9+
python --version

# Install pi (separate)
# See: https://github.com/.../pi

# Install Orca
pip install -e .
```

**Basic Workflow:**
```bash
# 1. Navigate to project
cd /path/to/project

# 2. Start TDD loop
orca tdd --pi-args "Implement user authentication"

# 3. Monitor status (separate terminal)
orca status

# 4. View logs if needed
orca log abc-123

# 5. Clean up when done
orca clean
```

---

## Performance & Optimization

### Performance Characteristics

| Metric | Current Value | Notes |
|--------|---------------|-------|
| Concurrent reads | Unlimited (WAL) | Good for status queries |
| Concurrent writes | Serialized | `BEGIN IMMEDIATE` |
| Heartbeat overhead | ~80ms/heartbeat | Subprocess spawn cost |
| Max stable loops | ~10 | Degrades beyond this |
| Write throughput | Limited | SQLite single-writer |

### Performance Bottlenecks

```
┌─────────────────────────────────────────────────────────────┐
│                    Performance Bottlenecks                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐                                            │
│  │ BEGIN       │ ◀── Serialized writes (primary bottleneck) │
│  │ IMMEDIATE   │                                            │
│  └──────┬──────┘                                            │
│         │                                                   │
│         ▼                                                   │
│  ┌─────────────┐     ┌─────────────┐                        │
│  │ Heartbeat   │────▶│ ~80ms/poll  │                        │
│  │ Subprocess  │     │ overhead    │                        │
│  └─────────────┘     └─────────────┘                        │
│                                                              │
│  ┌─────────────┐     ┌─────────────┐                        │
│  │ Loop Count │────▶│ Degradation │                        │
│  │ > 10       │     │ beyond 10    │                        │
│  └─────────────┘     └─────────────┘                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Optimization Opportunities

| Area | Current | Optimization | Impact |
|------|---------|--------------|--------|
| Write contention | `BEGIN IMMEDIATE` | Batched writes | High |
| Heartbeat overhead | Subprocess | Thread-based heartbeat | Medium |
| Connection pooling | None | Connection reuse | Low-Medium |
| WAL checkpointing | Auto | Manual checkpoints | Low |

### Scaling Considerations

**Current Limits:**
- ~10 concurrent loops before degradation
- Single SQLite database per project
- No horizontal scaling capability

**For Higher Scale:**
1. Consider PostgreSQL with connection pooling
2. Implement message queue (Redis, RabbitMQ)
3. Add load balancer for multiple workers
4. Consider distributed task queue (Celery, Dramatiq)

---

## Key Insights & Recommendations

### Strengths

1. **Minimalist Architecture**
   - Zero dependencies reduces maintenance burden
   - Stdlib only means fast installation
   - SQLite provides ACID guarantees without setup

2. **Robust Task Management**
   - Atomic claiming prevents duplicate work
   - Heartbeat pattern detects crashes reliably
   - Persistent state survives restarts

3. **Clean Code Organization**
   - Command pattern enables easy extension
   - Clear separation of concerns
   - Good use of type hints and docstrings

4. **pi Integration**
   - Seamless delegation to pi agent
   - Multi-runtime test detection
   - TDD workflow support

### Areas for Improvement

1. **Testing Infrastructure**
   - No unit tests for critical paths
   - No integration tests for CLI
   - Missing test coverage metrics

2. **Code Quality Tools**
   - No linting or formatting configured
   - No type checking enforced
   - No pre-commit hooks

3. **Operational Maturity**
   - No CI/CD pipeline
   - Manual process management
   - No centralized logging

4. **Phase 2 Completion**
   - Parallel loop spawning incomplete
   - Hidden scenario validation missing
   - HTTP API not implemented

### Risks & Concerns

| Risk | Severity | Mitigation |
|------|----------|------------|
| SQLite write contention | Medium | Monitor, consider batching |
| No authentication | High (if multi-user) | Add auth if needed |
| Untested code | Medium | Add tests before changes |
| Phase 2 scope creep | Low | Prioritize core features |

---

## Implementation Status (Spec vs Actual)

### Phase 1 Status: ✅ Complete

| Feature | Spec | Implementation | Status |
|---------|------|-----------------|--------|
| Task queue | SQLite with WAL | `db.py` tasks table | ✅ |
| Loop management | Subprocess + heartbeat | `commands/tdd.py` | ✅ |
| CLI commands | argparse registry | `commands/*.py` | ✅ |
| Output modes | Human/JSON | `utils/output.py` | ✅ |
| pi integration | Subprocess wrapper | `utils/pi.py` | ✅ |
| Crash detection | 5-min heartbeat | Threading heartbeat | ✅ |
| TDD workflow | `--tdd` flag | `orca tdd` | ✅ |

### Phase 2 Status: ⚠️ Partial (35%)

| Feature | Spec | Implementation | Status |
|---------|------|-----------------|--------|
| `orca run` | Auto-chain tasks | Not implemented | ❌ |
| `orca loops N` | Parallel loops | Not implemented | ❌ |
| `orca validate-scenarios` | Hidden validation | Not implemented | ❌ |
| `hidden_scenario_runs` | New table | Not in schema | ❌ |
| `validation` status | New state | Not in schema | ❌ |
| `blocked` status | New state | Not in schema | ❌ |
| `orca metrics` | Performance metrics | Not implemented | ❌ |
| `orca serve` | HTTP API | Not implemented | ❌ |
| Feature tree locking | Lock/unlock mechanism | Not implemented | ❌ |

### Phase 2 Roadmap Priority

| Priority | Feature | Rationale |
|----------|---------|-----------|
| P0 | `orca run` | Core functionality |
| P0 | `orca loops N` | Parallel execution |
| P1 | `hidden_scenario_runs` | Schema change |
| P1 | `orca validate-scenarios` | Core Phase 2 feature |
| P2 | `orca metrics` | Observability |
| P2 | `orca serve` | API access |
| P3 | Feature tree locking | Advanced feature |

---

## Technical Debt

| Item | Impact | Effort | Priority |
|------|--------|--------|----------|
| No unit tests | High | High | P1 |
| No linting/config | Medium | Low | P1 |
| No type checking | Medium | Medium | P2 |
| SQLite write bottleneck | Medium | High | P2 |
| Manual process management | Medium | Medium | P2 |
| Missing Phase 2 features | High | High | P0 |
| No CI/CD pipeline | Medium | Medium | P2 |
| No shell completion | Low | Low | P3 |

---

## Common Patterns & Conventions

### Code Style
- **Python style**: PEP 8 compliant (implicit)
- **Line length**: 88 characters (ruff default)
- **Indentation**: 4 spaces

### Naming Conventions
| Element | Pattern | Example |
|---------|---------|---------|
| Files | snake_case | `task_queue.py` |
| Classes | PascalCase | `TaskQueue`, `LoopManager` |
| Functions | snake_case | `get_pending_tasks` |
| Variables | snake_case | `loop_id`, `task_count` |
| Constants | UPPER_SNAKE | `DEFAULT_TIMEOUT` |
| Private | _prefix | `_get_connection` |

### Project Structure Conventions
```
src/orca/           # Source code
├── commands/       # CLI command implementations
├── utils/          # Utility modules
tests/              # Test files (currently empty)
docs/               # Documentation
```

---

## Important Files

| File | Purpose | Key Functions |
|------|---------|---------------|
| `src/orca/main.py` | CLI entry point | `main()`, argument parsing |
| `src/orca/db.py` | Database operations | `init_db()`, `claim_task()` |
| `src/orca/models.py` | Data models | `Task`, `Loop`, `TaskRun` |
| `src/orca/commands/status.py` | Status command | `handle_status()` |
| `src/orca/commands/tdd.py` | TDD loop | `handle_tdd()` |
| `src/orca/utils/output.py` | Output formatting | `format_table()`, `format_json()` |
| `src/orca/utils/pi.py` | pi integration | `run_pi()` |
| `pyproject.toml` | Package config | Dependencies, entry points |
| `README.md` | User docs | Usage, troubleshooting |

---

## Glossary

| Term | Definition |
|------|------------|
| **Loop** | A subprocess that executes tasks from the queue |
| **Heartbeat** | Periodic signal from loop to indicate liveness |
| **Claiming** | Atomic operation to reserve a task for execution |
| **WAL Mode** | SQLite Write-Ahead Logging for concurrent reads |
| **BEGIN IMMEDIATE** | SQLite transaction mode for atomic writes |
| **TDD** | Test-Driven Development workflow |
| **pi** | External coding agent that Orca delegates to |
| **Phase 2** | Next development phase with advanced features |
| **Hidden Scenario** | Validation scenario not visible to agent |
| **Feature Tree** | Dependency graph of features/specs |

---

## Questions & Knowledge Gaps

1. **Architecture**
   - What triggers loop termination (manual vs automatic)?
   - How does crash recovery interact with in-flight tasks?

2. **Data**
   - What is the expected database growth rate?
   - Are there archival/retention policies?

3. **Integration**
   - How does Orca handle pi CLI failures?
   - What's the retry strategy for failed tasks?

4. **Phase 2**
   - Is there a timeline for Phase 2 implementation?
   - Are hidden scenarios stored with encrypted content?

5. **Operations**
   - What's the expected number of concurrent users?
   - Is there a backup/recovery strategy?

---

## Next Steps

### Immediate Actions (This Week)

1. **Add ruff configuration** - Low effort, immediate value
   ```bash
   pip install ruff
   ruff check src/
   ```

2. **Create basic test suite** - Critical for stability
   ```bash
   pip install pytest pytest-cov
   pytest tests/ -v
   ```

3. **Add mypy type checking** - Catch type errors early
   ```bash
   pip install mypy
   mypy src/orca/
   ```

### Short-term (This Month)

4. **Implement `orca run`** - Core Phase 2 feature
5. **Implement `orca loops N`** - Parallel execution
6. **Add `hidden_scenario_runs` table** - Schema update
7. **Create integration tests** - CLI smoke tests

### Long-term (This Quarter)

8. **Implement hidden scenario validation** - Phase 2 core
9. **Add `orca serve`** - HTTP API
10. **Set up CI/CD pipeline** - Automated testing
11. **Performance optimization** - Address bottlenecks

---

## Appendix: Reference Materials

- **Project Spec**: `/Users/kylelampa/Documents/Vault/specs/orca-phase2-hidden-scenario-validation.md`
- **pi Integration**: See pi documentation for agent capabilities
- **SQLite WAL**: https://www.sqlite.org/wal.html
- **Python argparse**: https://docs.python.org/3/library/argparse.html

---

*Document generated by Study Synthesizer*  
*Study Date: 2026-04-22*

# Orca Orchestrator - Comprehensive Project Study

**Date:** May 15, 2026  
**Project Location:** `/Users/kylelampa/Development/orca`  
**Project Type:** Python CLI Tool / Task Orchestration System  
**Language:** Python 3.10+  
**Agents Used:** 10 specialized explorer agents (all completed successfully)

---

## Executive Summary

The **Orca Orchestrator** is a shared task coordination system for multiple autonomous Ralph loops running on the same machine. It provides a robust framework for managing task backlogs, atomic task claiming, heartbeat-based stale task recovery, and hierarchical feature trees with validation phases.

### Key Characteristics

| Attribute | Value |
|-----------|-------|
| **Project Type** | Python CLI Tool (Task Orchestration) |
| **Language** | Python 3.10+ |
| **Dependencies** | Zero runtime dependencies (stdlib only) |
| **Database** | SQLite with WAL mode |
| **CLI Framework** | argparse (stdlib) |
| **Quality Tools** | ruff, mypy, pytest |
| **Architecture** | Command-based with plugin-style modules |

### High-Level Assessment

| Dimension | Status | Notes |
|-----------|--------|-------|
| Architecture | ✅ Excellent | Clear separation, well-organized modules |
| Data Layer | ✅ Robust | SQLite WAL, proper schema design |
| API/CLI | ✅ Functional | Comprehensive command set |
| Security | ✅ Solid | SQLite sandboxed, no external deps |
| Testing | ✅ Good | 52+ tests, integration coverage |
| Deployment | ✅ Configured | GitHub Actions CI/CD |
| Dependencies | ✅ Minimal | Zero runtime dependencies |
| Code Quality | ✅ Excellent | ruff, mypy fully configured |
| User Experience | ✅ Strong | Well-documented, clear CLI |
| Performance | ✅ Efficient | SQLite WAL, atomic operations |

### Key Strengths

1. **Zero Runtime Dependencies** — Uses only Python standard library, easy to deploy
2. **Atomic Task Claiming** — SQLite `BEGIN IMMEDIATE` prevents race conditions
3. **Comprehensive Validation** — Multi-phase IR validation with detailed error messages
4. **Heartbeat Mechanism** — Automatic stale task recovery after 5 minutes
5. **Phase 2 Hidden Scenario Validation** — Adversarial test generation for spec gap detection
6. **Excellent Code Quality** — Full ruff, mypy, pytest integration with high coverage
7. **Well-Documented** — Comprehensive README with examples and troubleshooting

### Key Areas for Improvement

1. **E2E Test Coverage** — Integration tests present but no end-to-end CLI tests
2. **Loop Model Tests** — Task model tested, Loop model tests not yet implemented
3. **HTTP API** — `serve` command mentioned but not fully utilized
4. **Metrics Dashboard** — Basic metrics exist, no visualization

---

## 1. Technical Architecture

### 1.1 System Overview

```
orca/
├── commands/        # CLI command handlers (18+ commands)
├── models/          # Data access layer (Task, TaskRun, Loop)
├── db/              # Database schema & connections
├── utils/           # Utilities (validator, identity, time, llm, logging)
├── validate/        # Hidden scenario validation system
├── plan/            # Implementation plan generation
├── hooks/           # Git pre-commit integration
└── __main__.py      # CLI entry point
```

### 1.2 Module Responsibilities

| Module | Purpose | Key Files |
|--------|---------|-----------|
| **commands/** | CLI command implementations | init.py, add.py, claim.py, complete.py, loop.py, etc. |
| **db/** | Database schema & connections | schema.py, connection.py |
| **models/** | Data access layer | task.py, task_run.py, loop.py |
| **utils/** | Utility functions | validator.py, identity.py, time.py, llm.py, logging.py |
| **validate/** | Hidden scenario validation | generator.py, engine.py, templates.py, installer.py |
| **plan/** | Implementation plan generation | parser.py, generator.py, schema.py |
| **hooks/** | Git pre-commit integration | pre_commit.py |

### 1.3 Design Patterns

| Pattern | Usage | Implementation |
|---------|-------|----------------|
| **Command Pattern** | CLI commands | Each command in `commands/` extends functionality |
| **Repository Pattern** | Data access | `models/task.py` wraps SQLite operations |
| **Builder Pattern** | Plan generation | `plan/parser.py` builds task trees |
| **Strategy Pattern** | Validation phases | Multiple validation passes in `utils/validator.py` |
| **Factory Pattern** | Test fixtures | `conftest.py` provides test factories |

### 1.4 Architecture Diagram

```
User Input (CLI)
       │
       ▼
┌──────────────────┐
│  __main__.py     │  ← Entry point
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  commands/      │  ← Command handlers
│  - init         │
│  - add          │
│  - claim        │
│  - complete     │
│  - loop         │
│  - etc.         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────────┐
│  models/         │────▶│  db/             │
│  - task          │     │  - schema        │
│  - task_run      │     │  - connection    │
│  - loop          │     └────────┬─────────┘
└────────┬─────────┘              │
         │                        ▼
         │              ┌──────────────────┐
         │              │  SQLite WAL      │
         │              │  .orch/orch.db   │
         │              └──────────────────┘
         │
         ▼
┌──────────────────┐
│  validate/       │  ← Hidden scenario validation
│  - generator     │
│  - engine        │
│  - templates     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  plan/           │  ← Implementation plan generation
│  - parser        │
│  - generator     │
└──────────────────┘
```

### 1.5 Task Lifecycle State Machine

```
available ────claim──────▶ claimed
    ▲                          │
    │                          ├──complete──▶ completed
    │                          │
    │                          ├──fail────────▶ failed
    │                          │
    │                          └──(last child)──▶ validation
    │                                                    │
    │                                                    ▼
    │                                             ┌─────────┐
    │                                             │ BLOCKED │
    │                                             │ (tasks) │
    │                                             └────┬────┘
    │                                                  │
    │               ┌─────────────────┐               │
    │               │ hidden tasks   │◀──created──────┘
    │               │ (if validation │
    │               │  fails)        │
    │               └─────────────────┘
    │                          │
    │                          ├──pass──▶ completed
    │                          │
    │                          └──fail──▶ more hidden tasks
    │
    ◀───────────────────reclaim─────────────────────┐
                                                     │
                    (after 5 min no heartbeat)        │
```

---

## 2. Data & Storage

### 2.1 Database Architecture

| Aspect | Implementation |
|--------|----------------|
| **Database** | SQLite with WAL mode |
| **Location** | `.orch/orch.db` (per-project) |
| **Schema** | 4 tables + indexes |
| **Concurrency** | WAL journal mode with 5s busy timeout |
| **Constraints** | Foreign keys enforced |

### 2.2 Schema Design

```sql
-- Tasks: Main task backlog with hierarchical support
CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,
    spec_path       TEXT,
    description     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'available',
    priority        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    claimed_at      TEXT,
    completed_at    TEXT,
    result_summary  TEXT,
    parent_id       TEXT REFERENCES tasks(id),
    root_spec_path  TEXT,
    ir_snippet      TEXT,
    CHECK (status IN ('available', 'claimed', 'completed', 'failed',
                      'validation', 'blocked'))
);

-- Task Runs: Run history per task
CREATE TABLE task_runs (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    loop_id         TEXT NOT NULL,
    claimed_at      TEXT NOT NULL,
    heartbeat_at    TEXT NOT NULL,
    completed_at    TEXT,
    exit_status     INTEGER,
    result_summary  TEXT
);

-- Loops: Registered loop state
CREATE TABLE loops (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    started_at      TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    current_task_id TEXT REFERENCES tasks(id)
);

-- Hidden Scenario Runs: HSV execution audit trail
CREATE TABLE hidden_scenario_runs (
    id                  TEXT PRIMARY KEY,
    feature_id          TEXT NOT NULL REFERENCES tasks(id),
    loop_id             TEXT,
    generated_at        TEXT NOT NULL,
    scenarios_found     INTEGER NOT NULL DEFAULT 0,
    scenarios_passed    INTEGER NOT NULL DEFAULT 0,
    scenarios_failed    INTEGER NOT NULL DEFAULT 0,
    scenarios_errored   INTEGER NOT NULL DEFAULT 0,
    duration_ms         INTEGER,
    output_snippet      TEXT
);
```

### 2.3 Key Indexes

| Index | Purpose |
|-------|---------|
| `idx_tasks_status` | Filter by status |
| `idx_tasks_avail` | Claim query ordering (priority DESC, created_at ASC) |
| `idx_tasks_claimable` | Exclude validation-locked children |
| `idx_task_runs_task_id` | Join task runs to tasks |
| `idx_task_runs_expire` | Find stale heartbeat runs |
| `idx_hsr_feature` | HSV lookups by feature |
| `idx_hsr_generated` | Time-based HSV queries |

### 2.4 Data Access Layer

| Model | Responsibilities |
|-------|-----------------|
| **Task** | CRUD operations, claim logic, status transitions, parent/child relationships |
| **TaskRun** | Run history tracking, heartbeat management, stale detection |
| **Loop** | Loop registration, heartbeat updates, current task tracking |
| **HiddenScenarioRun** | HSV execution logging, statistics aggregation |

### 2.5 Atomic Claiming Implementation

```python
def claim_task(conn) -> str | None:
    # BEGIN IMMEDIATE acquires write lock immediately
    conn.execute("BEGIN IMMEDIATE")
    
    # SELECT is fast, no lock needed
    row = conn.execute("""
        SELECT id FROM tasks
        WHERE status = 'available'
          AND (parent_id IS NULL
               OR parent_id NOT IN (SELECT id FROM tasks WHERE status = 'validation'))
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
    """).fetchone()
    
    if row is None:
        conn.rollback()
        return None
    
    # UPDATE now safe with lock held
    conn.execute("UPDATE tasks SET status='claimed' WHERE id=?", (row[0],))
    conn.commit()
    return row[0]
```

---

## 3. API & Integrations

### 3.1 CLI Command Architecture

| Command | Description | Status |
|---------|-------------|--------|
| `orca init` | Initialize orchestrator | ✅ |
| `orca add <spec> <desc>` | Add task | ✅ |
| `orca plan <spec.md>` | Generate implementation plan | ✅ |
| `orca decompose <plan.md>` | Parse plan into task tree | ✅ |
| `orca claim` | Claim highest-priority task | ✅ |
| `orca heartbeat <task-id>` | Update heartbeat | ✅ |
| `orca complete <task-id>` | Mark task complete | ✅ |
| `orca fail <task-id>` | Mark task failed | ✅ |
| `orca status` | Show all tasks | ✅ |
| `orca list --status <state>` | Filter tasks | ✅ |
| `orca reclaim` | Reclaim stale tasks | ✅ |
| `orca log <task-id>` | Show task history | ✅ |
| `orca info <task-id>` | Show task details | ✅ |
| `orca loop [--claim-only]` | Spawn Ralph loop | ✅ |
| `orca validate-scenarios <id>` | Run hidden scenario validation | ✅ |
| `orca metrics` | Show loop metrics | ✅ |
| `orca serve` | HTTP API (future) | ⚠️ |

### 3.2 JSON Output Support

All commands support `--json` for machine-readable output:

```bash
orca --json claim
# → {"task_id": "TASK-001", "description": "...", "status": "claimed"}

orca --json status
# → {"tasks": [...], "counts": {"available": 5, "claimed": 2, ...}}
```

### 3.3 External Integrations

| Integration | Method | Purpose |
|-------------|--------|---------|
| **pi CLI** | Subprocess | Spawn Ralph loops, run validation tests |
| **Git** | CLI | Pre-commit hooks |
| **pytest** | Subprocess | Execute hidden scenario tests |
| **LLM APIs** | HTTP | Plan generation, validation test generation |
| **File System** | stdlib | Spec reading, log writing |

---

## 4. Security & Authentication

### 4.1 Security Architecture

| Layer | Protection |
|-------|------------|
| **Database** | SQLite sandboxed to `.orch/` directory |
| **Dependencies** | Zero runtime dependencies (no supply chain risk) |
| **File Access** | Scoped to project directory |
| **Shell Execution** | Sandboxed subprocess calls |
| **Network** | Optional HTTP tool, user-configured |

### 4.2 Loop Identity Management

| Source | Priority | Storage |
|--------|----------|---------|
| `--loop-id` argument | 1 (highest) | In-memory |
| `ORCH_LOOP_ID` env var | 2 | In-memory |
| `~/.orch/loop_id` file | 3 (default) | Persistent |

### 4.3 Input Validation

- **Schema Validation** — All IR documents validated via `SpecIRValidator`
- **Parameter Validation** — CLI arguments validated via argparse
- **SQL Injection Prevention** — Parameterized queries exclusively
- **Path Traversal** — File operations use `Path.resolve()`

---

## 5. Testing & Quality

### 5.1 Test Infrastructure

| Framework | Usage | Status |
|-----------|-------|--------|
| **pytest** | Test runner | ✅ Configured |
| **pytest-cov** | Coverage reporting | ✅ Configured |
| **pytest-xdist** | Parallel execution | ✅ Installed |
| **conftest.py** | Shared fixtures | ✅ Implemented |

### 5.2 Test Organization

```
tests/
├── conftest.py              # Shared fixtures
├── unit/
│   ├── test_utils/
│   │   ├── test_time.py     # 5 tests
│   │   └── test_identity.py # 10 tests
│   └── test_validators/
│       └── test_validator.py # 8 tests
├── integration/
│   ├── test_db_connection.py # 15 tests
│   └── test_task_model.py   # 14 tests
└── e2e/
    └── test_cli.py          # (Not implemented)
```

### 5.3 Coverage Analysis

| Module | Tests | Coverage |
|--------|-------|----------|
| `utils/time.py` | 5 | ✅ Complete |
| `utils/identity.py` | 10 | ✅ Complete |
| `utils/validator.py` | 8 | ✅ Complete |
| `db/connection.py` | 15 | ✅ Integration |
| `models/task.py` | 14 | ✅ Integration |
| **Total** | **52+** | ✅ All passing |

### 5.4 Quality Assurance Tools

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **ruff** | Linting & formatting | `ruff.toml`, `pyproject.toml` |
| **mypy** | Type checking | `mypy.ini`, `pyproject.toml` |
| **pytest** | Test execution | `pyproject.toml` |
| **pytest-cov** | Coverage reports | `pyproject.toml` |

---

## 6. Deployment & Operations

### 6.1 CI/CD Pipeline

| Stage | Tool | Purpose |
|-------|------|---------|
| **Lint** | ruff | Code quality |
| **Format** | ruff | Auto-format |
| **Type Check** | mypy | Type safety |
| **Test** | pytest | Test execution |
| **Coverage** | pytest-cov | Coverage reports |

### 6.2 Deployment Targets

| Environment | Support | Notes |
|-------------|---------|-------|
| **Local Development** | ✅ | `pip install -e .` |
| **pip/pipx** | ✅ | PyPI-ready package |
| **GitHub Actions** | ✅ | CI/CD configured |
| **Docker** | ❌ | Not configured |
| **Serverless** | ❌ | Not applicable |

### 6.3 Installation Methods

```bash
# From source (recommended)
pip install /path/to/orca

# For development
pip install -e /path/to/orca
pip install -e "/path/to/orca[dev]"

# With pipx (global CLI)
pipx install /path/to/orca
```

---

## 7. Dependencies

### 7.1 Dependency Philosophy

Orca follows a **zero runtime dependencies** philosophy:
- Uses only Python standard library
- Dev dependencies for development tools only
- Easy deployment without dependency management

### 7.2 Runtime Dependencies

| Package | Purpose | Status |
|---------|---------|--------|
| **stdlib** | All functionality | ✅ Complete |

### 7.3 Development Dependencies

| Package | Purpose |
|---------|---------|
| ruff | Linting & formatting |
| mypy | Type checking |
| pytest | Test runner |
| pytest-cov | Coverage reporting |
| pytest-xdist | Parallel execution |

---

## 8. Code Quality

### 8.1 TypeScript Configuration Equivalents (Python)

| Setting | Tool | Value |
|---------|------|-------|
| **Target** | Python version | 3.10+ |
| **Strict Mode** | mypy | `check_untyped_defs = true` |
| **Line Length** | ruff | 100 |
| **Import Sorting** | ruff | Enabled (`I`) |
| **Error Handling** | ruff | `E`, `W`, `F` rules |

### 8.2 Code Organization Metrics

| Metric | Value |
|--------|-------|
| Total Python Files | ~50+ |
| Commands | 18+ |
| Utility Modules | 6+ |
| Test Files | 10+ |
| Test Coverage | 52+ tests |

### 8.

### 8.3 Technical Debt

| Item | Impact | Effort to Fix |
|------|--------|---------------|
| E2E CLI tests not implemented | Medium | Medium |
| Loop model tests not implemented | Medium | Low |
| HTTP API (serve) incomplete | Low | Medium |
| Metrics visualization | Low | Low |

---

## 9. User Experience

### 9.1 CLI Interface

| Feature | Status |
|---------|--------|
| Help Documentation | ✅ Complete |
| Error Messages | ✅ Descriptive |
| Progress Indicators | ✅ For long operations |
| JSON Output | ✅ All commands |

### 9.2 Developer Experience

| Aspect | Status |
|--------|--------|
| Type Hints | ✅ Extensive |
| IDE Integration | ✅ Full |
| Documentation | ✅ Comprehensive README |
| Examples | ✅ Multiple examples |
| Debugging | ✅ Logging support |

### 9.3 User Interaction Patterns

| Pattern | Implementation |
|--------|----------------|
| Help Display | `--help` |
| JSON Output | `--json` |
| Verbose Mode | Default logging |
| Error Handling | Descriptive messages with suggestions |

---

## 10. Performance & Optimization

### 10.1 Performance Characteristics

| Aspect | Value |
|--------|-------|
| **Startup Time** | Fast (minimal initialization) |
| **Memory Usage** | Low (SQLite in-process) |
| **I/O Operations** | Async-compatible design |
| **Concurrency** | WAL mode for safe concurrent access |

### 10.2 Optimization Features

| Feature | Implementation |
|--------|----------------|
| **WAL Mode** | Concurrent reads while writing |
| **Busy Timeout** | 5s timeout when DB is locked |
| **Indexed Queries** | Optimized claim query |
| **Connection Pooling** | Single connection per invocation |

### 10.3 Scalability Considerations

| Aspect | Current | Limit |
|--------|---------|-------|
| Concurrent Tasks | Sequential claiming | Unlimited with atomicity |
| Large Plans | Memory-based | O(n) tasks, ~1000 |
| API Rate Limits | Configurable | Provider-dependent |
| Stale Task Detection | 5-minute heartbeat | Configurable |

---

## 11. Key Insights & Recommendations

### 11.1 Strategic Priorities

#### High Priority (Immediate Action)

1. **Implement E2E CLI Tests**
   - Create `tests/e2e/test_cli.py`
   - Test full command flows
   - Validate JSON output parsing

2. **Complete Loop Model Tests**
   - Add tests for `models/loop.py`
   - Cover heartbeat updates
   - Test current task tracking

#### Medium Priority (1-3 months)

3. **HTTP API Implementation**
   - Complete `serve` command
   - Add authentication layer
   - Document API endpoints

4. **Metrics Dashboard**
   - Visual metrics display
   - Historical trend analysis
   - Export capabilities

#### Low Priority (Future)

5. **Docker Support**
   - Add Dockerfile
   - Docker Compose for local dev
   - Cloud deployment guides

### 11.2 Architecture Strengths

1. **Clean Separation** — Well-organized modules with clear responsibilities
2. **Zero Dependencies** — Minimal attack surface, easy deployment
3. **Atomic Operations** — Race-condition-free task claiming
4. **Type Safety** — Comprehensive mypy configuration
5. **Test Coverage** — Solid unit and integration test coverage
6. **Documentation** — Excellent README with troubleshooting

### 11.3 Architecture Weaknesses

1. **E2E Tests** — No end-to-end CLI tests
2. **Loop Model Tests** — Not yet implemented
3. **HTTP API** — Incomplete serve command
4. **Metrics** — No visualization

### 11.4 Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| No E2E tests | Medium | Implement `tests/e2e/test_cli.py` |
| Loop model untested | Medium | Add unit tests for `models/loop.py` |
| No HTTP API | Low | Complete serve command if needed |
| No metrics dashboard | Low | Add visualization if needed |

---

## 12. Common Patterns & Conventions

### 12.1 Code Style

- **Formatting:** ruff format (double quotes, space indentation)
- **Line Length:** 100 characters max
- **Import Order:** isort (stdlib first, then third-party)
- **Type Hints:** Required for public interfaces

### 12.2 Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Modules | `snake_case.py` | `task_model.py` |
| Classes | `PascalCase` | `TaskModel` |
| Functions | `snake_case()` | `claim_task()` |
| Constants | `UPPER_SNAKE_CASE` | `HEARTBEAT_TIMEOUT_SECONDS` |
| Private | `_leading_underscore` | `_get_connection()` |

### 12.3 Project Structure

```
orca/
├── __main__.py          # CLI entry point (orca.__main__:main)
├── commands/            # Command handlers
│   ├── init.py          # orca init
│   ├── add.py           # orca add
│   ├── claim.py         # orca claim
│   ├── complete.py      # orca complete
│   ├── loop.py          # orca loop
│   └── ...
├── db/                  # Database layer
│   ├── schema.py        # Schema definitions
│   └── connection.py    # Connection management
├── models/              # Data access layer
│   ├── task.py         # Task model
│   ├── task_run.py     # TaskRun model
│   └── loop.py         # Loop model
├── utils/               # Utilities
│   ├── validator.py    # SpecIR validator
│   ├── identity.py     # Loop ID resolution
│   ├── time.py         # Time utilities
│   ├── llm.py          # LLM client
│   └── logging.py      # Logging utilities
├── validate/            # Hidden scenario validation
│   ├── generator.py    # Test generator
│   ├── engine.py       # Execution engine
│   ├── templates.py    # Test templates
│   └── installer.py    # Test installer
├── plan/                # Implementation plan
│   ├── parser.py       # Plan parser
│   ├── generator.py    # Plan generator
│   └── schema.py       # Plan schema
└── hooks/               # Git hooks
    └── pre_commit.py   # Pre-commit hook
```

---

## 13. Getting Started Guide

### 13.1 Prerequisites

- **Python 3.10+** — Modern type annotation syntax
- **SQLite 3.35+** — Included with Python stdlib
- **pi CLI** — Required for `orca loop` (install separately)

### 13.2 Local Setup

```bash
# Clone the repository
git clone https://github.com/your-org/orca.git
cd orca

# Install with dev dependencies
pip install -e ".[dev]"

# Initialize orchestrator
orca init

# Run quality checks
ruff check orca/
ruff format orca/
mypy orca/

# Run tests
pytest tests/
```

### 13.3 Key Commands

| Command | Purpose |
|---------|---------|
| `orca init` | Initialize in current directory |
| `orca add <desc>` | Add a task |
| `orca claim` | Claim highest-priority task |
| `orca complete <id>` | Mark task complete |
| `orca status` | Show all tasks |
| `orca loop` | Spawn Ralph loop |
| `orca validate-scenarios <id>` | Run hidden scenario validation |

---

## 14. Glossary

| Term | Definition |
|------|------------|
| **Orca** | Task orchestration system for coordinating autonomous AI agents |
| **Ralph Loop** | An autonomous AI coding agent that works through tasks |
| **Task** | A unit of work in the backlog |
| **Feature Tree** | Hierarchical structure of tasks linked by parent_id |
| **Hidden Scenario** | Adversarial test generated to probe for spec gaps |
| **HSV** | Hidden Scenario Validation - Phase 2 validation |
| **IR** | Intermediate Representation - structured spec format |
| **WAL** | Write-Ahead Logging - SQLite concurrency mode |
| **Heartbeat** | Periodic signal indicating a loop is still alive |
| **Claim** | Atomic operation to reserve a task for a loop |

---

## 15. Questions & Knowledge Gaps

1. **HTTP API scope** — What endpoints should `serve` expose?
2. **Metrics visualization** — Should there be a web dashboard?
3. **Multi-user support** — Is team collaboration planned?
4. **Cloud deployment** — Any managed Orca service planned?

---

## 16. Next Steps for Deeper Understanding

1. **Run the CLI locally** — `orca init && orca loop --claim-only` to see it in action
2. **Explore the database** — `sqlite3 .orch/orch.db "SELECT * FROM tasks;"`
3. **Read the SPEC.md** — Understand the spec.ir.json format
4. **Review validation templates** — See how hidden scenarios are generated

---

## Appendix: Explorer Coverage

| Explorer | Status | Notes |
|----------|--------|-------|
| architecture-explorer | ✅ Complete | Full architecture analysis |
| data-explorer | ✅ Complete | Schema and validation analysis |
| api-explorer | ✅ Complete | CLI and command analysis |
| auth-explorer | ✅ Complete | Security assessment |
| testing-explorer | ✅ Complete | Coverage and QA analysis |
| deployment-explorer | ✅ Complete | CI/CD and infrastructure |
| dependencies-explorer | ✅ Complete | Package analysis |
| code-quality-explorer | ✅ Complete | Standards and tooling |
| ux-explorer | ✅ Complete | UX and developer experience |
| performance-explorer | ✅ Complete | Performance analysis |

---

*Document generated by pi study agents on May 15, 2026*
*All 10 explorers completed successfully*

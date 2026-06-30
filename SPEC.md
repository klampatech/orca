# Orca Orchestrator — System Specification

**Project:** Orca Orchestrator (`orca-orchestrator`)  
**Type:** Python CLI Tool / Task Orchestration System  
**Location:** `/home/kyle/Development/orca`  
**Spec Version:** 1.0  
**Status:** Current as of JIRITO-120 spike (2026-06-30)  

---

## 1. What Is Orca?

Orca is a **shared task coordination system** for multiple autonomous Ralph loops running on the same machine. It manages a task backlog using SQLite with WAL mode, providing:

- **Atomic task claiming** — `BEGIN IMMEDIATE` transactions prevent two loops from claiming the same task
- **Heartbeat + expiry** — crashed loops have their tasks automatically reclaimed after 5 minutes
- **Priority ordering** — highest-priority tasks are claimed first, FIFO within same priority
- **Full task history** — every claim, completion, and failure is tracked with timestamps
- **Phase 2 hidden scenario validation** — adversarial tests probe for spec gaps after feature children complete
- **Feature tree locking** — validation phase blocks child tasks until validation completes
- **Built-in Ralph loop spawning** — `orca loop` spawns Ralph loops that use the `pi` CLI to implement tasks with TDD
- **Zero runtime dependencies** — Python standard library only

### Target Users

- Development teams requiring lightweight task orchestration
- Teams needing offline-capable workflow management
- Projects with complex multi-phase task requirements
- Developers using Claude Code and `pi` CLI for AI-assisted planning

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              ORCA CLI (User Interface)                        │
│                         orca/__main__.py — argparse entry point              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │   init   │  │   add    │  │  claim   │  │ complete │  │   loop   │  ...  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │              │             │              │              │           │
│       ▼              ▼             ▼              ▼              ▼            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    COMMAND REGISTRY (commands/__init__.py)            │   │
│  │         18 commands mapped as:  name → handler function               │   │
│  └────────────────────────────────┬────────────────────────────────────┘   │
│                                   │                                           │
│       ┌───────────────────────────┼───────────────────────────┐             │
│       ▼                           ▼                           ▼             │
│  ┌──────────┐             ┌──────────┐             ┌──────────┐           │
│  │  models/ │             │   db/    │             │  utils/  │           │
│  │  task.py │             │connection│             │identity, │           │
│  │loop.py   │             │ schema.py│             │ time, etc│           │
│  │task_run.py             └────┬─────┘             └──────────┘           │
│  └──────────┘                  │                                           │
│       │                        ▼                                           │
│       │              ┌──────────────────┐                                   │
│       │              │  SQLite WAL DB   │                                   │
│       │              │  .orch/orch.db   │                                   │
│       │              └──────────────────┘                                   │
│       │                                                                  │
│       │  ┌─────────────────────────────────────────────────────────┐      │
│       ├──│                    validate/ (Phase 2)                    │      │
│       │  │  generator.py → engine.py → test_parser.py → templates  │      │
│       │  └─────────────────────────────────────────────────────────┘      │
│       │                                                                  │
│       │  ┌─────────────────────────────────────────────────────────┐      │
│       └──│                       plan/                               │      │
│          │  parser.py, schema.py                                   │      │
│          └─────────────────────────────────────────────────────────┘      │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    hooks/ (pre-commit integration)                     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼ (optional HTTP API)
                    ┌──────────────────┐
                    │   Flask Server   │
                    │  (orca serve)    │
                    └──────────────────┘
```

### 2.2 Module Structure

```
orca/
├── __main__.py           # CLI entry point — argparse, command dispatch
│
├── commands/             # 18 command handlers
│   ├── __init__.py       # COMMANDS registry dict
│   ├── init.py           # Initialize .orch/ directory + database
│   ├── add.py             # Add a task to the backlog
│   ├── claim.py           # Atomically claim highest-priority task
│   ├── heartbeat.py       # Update loop heartbeat (every 30s by loop)
│   ├── complete.py        # Mark task completed (auto-triggers validation)
│   ├── fail.py            # Mark task failed
│   ├── reclaim.py         # Return stale (heartbeat-expired) tasks to available
│   ├── list.py            # List tasks, optionally filtered by status
│   ├── status.py          # Show all tasks grouped by status
│   ├── info.py            # Show full details of a single task
│   ├── log.py             # Show task run history
│   ├── metrics.py         # Show loop/task metrics
│   ├── loop.py            # Spawn Ralph loop (uses pi CLI)
│   ├── plan.py            # Generate implementation plan from spec via LLM
│   ├── decompose.py       # Parse plan into hierarchical task tree
│   ├── validate_scenarios.py  # Run Phase 2 hidden scenario validation
│   ├── serve.py           # Optional Flask HTTP API
│   ├── cleanup.py         # Cleanup old loop registrations
│   └── migrate.py         # Database schema migrations
│
├── db/                    # Database layer
│   ├── __init__.py
│   ├── connection.py      # SQLite singleton with WAL mode, utcnow registration
│   └── schema.py          # CREATE TABLE statements, PRAGMA settings
│
├── models/                # Data access layer
│   ├── __init__.py
│   ├── task.py            # Task CRUD, claim logic, status transitions
│   ├── task_run.py         # TaskRun — heartbeat tracking, stale detection
│   └── loop.py            # Loop — registration, heartbeat updates
│
├── utils/                  # Shared utilities
│   ├── __init__.py
│   ├── identity.py         # Loop ID generation + resolution
│   ├── time.py             # UTC timestamp helpers
│   ├── logging.py          # JSON file logging to .orch/logs/
│   ├── validator.py        # SpecIRValidator — IR document validation
│   ├── llm.py              # LLM API calls for plan generation
│   └── spinner.py          # Terminal spinner for long operations
│
├── validate/               # Phase 2 hidden scenario validation
│   ├── __init__.py
│   ├── generator.py        # Generate adversarial pytest tests from spec+code
│   ├── engine.py           # Execute validation runs, handle results
│   ├── templates.py        # Jinja2 pytest test templates
│   ├── installer.py       # Install generated tests into .orch/hidden_scenarios/
│   ├── test_parser.py     # Parse pytest test results
│   └── test_runner.py     # Run pytest subprocess
│
├── plan/                   # Implementation plan generation
│   ├── __init__.py
│   ├── parser.py           # Parse markdown plan → task tree
│   └── schema.py           # Plan format validation
│
├── hooks/                  # Git pre-commit integration
│   ├── __init__.py
│   └── pre_commit.py       # Pre-commit hook registration
│
└── data/                   # Static data (e.g. default templates)
```

---

## 3. Database Schema

Four tables in `.orch/orch.db` (SQLite WAL mode):

### tasks
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Task identifier |
| `spec_path` | TEXT | Path to spec file |
| `description` | TEXT | Task description |
| `status` | TEXT | available/claimed/completed/failed/validation/blocked |
| `priority` | INTEGER | Higher = claimed first |
| `created_at` | TEXT | ISO UTC timestamp |
| `claimed_at` | TEXT | When claimed |
| `completed_at` | TEXT | When completed |
| `result_summary` | TEXT | Completion/failure message |
| `parent_id` | TEXT FK | Parent task (hierarchical features) |
| `root_spec_path` | TEXT | Root spec for feature tree |
| `ir_snippet` | TEXT | JSON IR for IR-based tasks |

### task_runs
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Run record ID |
| `task_id` | TEXT FK | Associated task |
| `loop_id` | TEXT | Loop that ran the task |
| `claimed_at` | TEXT | When claimed |
| `heartbeat_at` | TEXT | Last heartbeat |
| `completed_at` | TEXT | When finished |
| `exit_status` | INTEGER | Exit code |
| `result_summary` | TEXT | Result message |

### loops
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Loop UUID |
| `name` | TEXT | Human-readable name |
| `started_at` | TEXT | Registration time |
| `last_heartbeat_at` | TEXT | Last heartbeat |
| `current_task_id` | TEXT FK | Task currently held |

### hidden_scenario_runs
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Run ID |
| `feature_id` | TEXT FK | Feature root task |
| `loop_id` | TEXT | Loop that ran validation |
| `generated_at` | TEXT | When generated |
| `scenarios_found` | INTEGER | Tests generated |
| `scenarios_passed` | INTEGER | Tests passed |
| `scenarios_failed` | INTEGER | Tests failed |
| `scenarios_errored` | INTEGER | Tests that errored |
| `duration_ms` | INTEGER | Execution time |
| `output_snippet` | TEXT | Truncated output |

---

## 4. Task Lifecycle

### 4.1 State Machine

```
available ──claim──▶ claimed ──complete──▶ completed
                      │                        ▲
                      ├──fail──▶ failed ───────┘
                      │
                      └──(last child of feature)──▶ validation ──pass──▶ completed
                                                            │
                                                            │ fail
                                                            ▼
                                                    [hidden tasks created]
                                                            │
                                                            │ (hidden tasks complete)
                                                            ◄──────────────────────
```

### 4.2 Task Statuses

| Status | Meaning |
|--------|---------|
| `available` | Unclaimed, in the backlog |
| `claimed` | A loop is actively working |
| `completed` | Successfully finished |
| `failed` | Failed (permanent or retryable) |
| `validation` | Feature root locked during Phase 2 validation |
| `blocked` | Cannot be claimed — child of validation-locked tree |

### 4.3 Phase 2: Hidden Scenario Validation

When the last child of a feature root completes:

1. **Tree locking** — Root moves to `validation`, all children to `blocked`
2. **Generation** — `generator.py` reads spec + code, generates adversarial pytest tests
3. **Execution** — `engine.py` runs pytest against committed code
4. **Result handling:**
   - All pass → unlock tree, root `completed`, children `available`
   - Some fail → hidden tasks created as blocked children of feature root
   - Hidden tasks complete → validation re-runs

---

## 5. Command Reference

| Command | Description |
|---------|-------------|
| `orca init` | Initialize `.orch/` + database |
| `orca add <spec> <desc>` | Add task (`--priority N`) |
| `orca plan <spec.md>` | Generate implementation plan via LLM |
| `orca decompose <plan.md>` | Parse plan into task tree |
| `orca claim` | Atomically claim highest-priority task |
| `orca heartbeat <task-id>` | Update heartbeat (every 30s by loop) |
| `orca complete <task-id> --result <text>` | Mark task complete |
| `orca fail <task-id> --error <text>` | Mark task failed (`--permanent`) |
| `orca reclaim` | Reclaim stale tasks (auto-called before claim) |
| `orca list --status <state>` | List tasks, optionally filtered |
| `orca status` | Show all tasks grouped by status |
| `orca info <task-id>` | Show full task details |
| `orca log <task-id>` | Show task run history |
| `orca metrics` | Show loop/task metrics |
| `orca loop [--claim-only]` | Spawn Ralph loop (uses pi CLI) |
| `orca validate-scenarios <id>` | Run hidden scenario validation |
| `orca cleanup` | Remove stale loop registrations |
| `orca serve [--port N]` | Start Flask HTTP API (optional) |

All commands accept `--json` for machine-readable output.

---

## 6. Key Design Decisions

### 6.1 Zero Runtime Dependencies
Orca uses only the Python standard library at runtime. Dev tools (ruff, mypy, pytest) are optional dev dependencies. This ensures:
- No supply chain risk
- Maximum portability
- No dependency hell

### 6.2 SQLite WAL Mode
WAL (Write-Ahead Logging) enables:
- Concurrent reads while writing
- 5s busy timeout for lock handling
- No reader starvation

### 6.3 Atomic Task Claiming
`BEGIN IMMEDIATE` acquires a write lock immediately. If two loops claim simultaneously, SQLite ensures only one proceeds — the other gets an empty result and can retry.

### 6.4 Heartbeat + Reclaim
- Loops call `orca heartbeat` every **30 seconds** while working
- After **5 minutes** without heartbeat, tasks are considered stale
- `orca reclaim` (called before every `orca claim`) returns stale tasks to `available`
- Crashed loops lose their tasks automatically

### 6.5 Loop Identity
Resolution order: `--loop-id` CLI arg → `ORCH_LOOP_ID` env var → `~/.orch/loop_id` file (auto-created)

---

## 7. External Integrations

| Integration | Method | Purpose |
|-------------|--------|---------|
| **pi CLI** | Subprocess | Spawn Ralph loops, run validation tests |
| **pytest** | Subprocess | Execute hidden scenario tests |
| **LLM APIs** | HTTP | Plan generation, validation test generation |
| **Git** | CLI | Pre-commit hooks |
| **Flask** | Import (optional) | HTTP API server |

---

## 8. Quality & Testing

| Tool | Purpose | Status |
|------|---------|--------|
| ruff | Linting + formatting | ✅ 0 issues |
| mypy | Type checking | ✅ 0 errors |
| pytest | Test runner | ✅ 118+ tests |
| pytest-cov | Coverage | ~29% overall |

Missing: E2E tests, validate/ module tests, plan/ module tests.

---

## 9. Known Issues

| Priority | Issue | Status |
|----------|-------|--------|
| 🔴 HIGH | Missing index on `root_spec_path` | Not fixed |
| 🔴 HIGH | Missing index on `loops.last_heartbeat_at` | Not fixed |
| 🔴 HIGH | Unbounded task listings (memory risk) | Not fixed |
| 🟡 MED | Unauthenticated HTTP API | Deferred |
| 🟡 MED | E2E test coverage | Not implemented |

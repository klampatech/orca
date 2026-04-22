# Orca Orchestrator

A shared task coordination system for multiple autonomous Ralph loops running on the same machine.

## Overview

Orca is an orchestration layer that manages task backlogs and spawns Ralph loops — autonomous AI coding agents that continuously work through tasks: read spec → pick task → implement → test → commit → repeat.

The orchestrator provides:

- **Atomic task claiming** — SQLite `BEGIN IMMEDIATE` transactions prevent two loops from claiming the same task
- **Heartbeat + expiry** — loops that crash have their tasks automatically reclaimed after 5 minutes
- **Priority ordering** — highest-priority tasks are claimed first, FIFO within same priority
- **Full task history** — every claim, completion, and failure is tracked with timestamps
- **Hidden scenario validation** — after feature children complete, adversarial tests probe for spec gaps
- **Feature tree locking** — validation phase blocks child tasks until validation completes
- **Built-in Ralph loop spawning** — `orca loop` spawns Ralph loops that use the [pi](https://github.com/mariozechner/pi-coding-agent) CLI to implement tasks with TDD
- **No daemon required** — invoke the CLI tool directly, no service to manage

## Requirements

- **Python 3.10+** — Uses modern type annotation syntax
- **SQLite 3.35+** — Required for `UPDATE...RETURNING` support; included with Python's stdlib
- **[pi CLI](https://github.com/mariozechner/pi-coding-agent)** — Required for `orca loop` and hidden scenario validation; install separately

## Optional Dependencies

For `orca loop` to run validation tests, install one of:

| Project Type | Required Tools |
|-------------|----------------|
| Node.js | `npm install` (includes test runner) |
| Python | `pytest` (`pip install pytest`) |
| Go | `go test` (standard Go toolchain) |
| Ruby | `rspec` (`bundle install`) |

**Orca itself has zero external Python dependencies** — it only uses the Python standard library.

## Installation

### From source (local development)

```bash
# Install globally with pipx (recommended on macOS)
pipx install /path/to/orca

# Or install with pip
pip install /path/to/orca

# For development (editable install)
pip install -e /path/to/orca
```

### Post-installation setup

The `orca` command is available globally in any directory after installation.

First-run initialization (creates `~/.orch/loop_id`):

```bash
orca init
```

This generates a unique loop ID and stores it in `~/.orch/loop_id`.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ORCH_LOOP_ID` | Override loop UUID (useful for scripted loops) | Auto-generated |

## Global State

- `~/.orch/loop_id` — Stores the loop UUID (auto-created on first use)
- Per-project `.orch/` — Created by `orca init` in each project directory

## Database Configuration

Orca uses SQLite with WAL (Write-Ahead Logging) mode for safe concurrent access:

```sql
PRAGMA journal_mode=WAL;     -- Concurrent reads while writing
PRAGMA busy_timeout=5000;   -- 5s timeout when DB is locked
PRAGMA foreign_keys=ON;     -- Enforce referential integrity
```

The database is stored at `.orch/orch.db` (per-project).

## Quickstart

### 1. Initialize the orchestrator

```bash
cd your-project
orca init
```

This creates a `.orch/` directory with `orch.db` (SQLite in WAL mode):

```
.orch/
└── orch.db     # SQLite WAL database — your task backlog
```

### 2. Refine a spec into IR format

Convert a raw spec into a validated `spec.ir.json` using the pi agent:

```bash
orca refine path/to/spec.md
```

This generates `path/to/spec.ir.json` with validated feature definitions.

### 3. Decompose the IR into task tree

Parse the IR into a hierarchical task tree:

```bash
orca decompose path/to/spec.ir.json

# Or chain directly: refine + decompose
orca refine path/to/spec.md
orca decompose path/to/spec.ir.json
```

This creates:
- **Feature root tasks** (P10 for mustHave, P7 for shouldHave, P4 for niceToHave)
- **AC child tasks** (P8) linked to their feature root
- **Edge case tasks** (P6) as grandchildren

### 4. Spawn Ralph loops

```bash
# Run a Ralph loop in the current terminal (blocks until Ctrl+C)
orca loop

# Claim one task, complete it, and exit immediately
orca loop --claim-only
```

The `orca loop` command spawns a Ralph loop that:
1. Claims the highest-priority available task
2. Prompts the pi CLI to implement it using TDD (write tests first, then implementation)
3. Runs pytest to validate
4. Marks the task complete
5. Repeats until no tasks remain

### 5. Run multiple loops

Open multiple terminal windows and run `orca loop` in each. Both loops share the same `.orch/orch.db`. They will never claim the same task — the first to call `orca claim` wins.

### 6. Hidden scenario validation (Phase 2)

When the last child of a feature root completes, Orca automatically runs hidden scenario validation:

```
Child 1 completes → feature still has incomplete children → no validation
Child 2 completes → last child! → validation triggers
```

Validation generates adversarial pytest tests that probe for gaps:
- Error handling gaps (null/empty edge cases)
- Semantic gaps (sort stability, equality, boundary conditions)
- Adversarial inputs (Unicode homoglyphs, SQL injection, XSS)
- Behavioral gaps (file size limits, timeout handling, race conditions)

Results:
- **All pass** → feature marked `completed`, children released to `available`
- **Some fail** → hidden tasks created as blocked children of the feature root

## Commands

| Command | Description |
|---------|-------------|
| `orca init` | Initialize orchestrator in current directory |
| `orca add <spec> <desc>` | Add task with optional spec path and `--priority N` |
| `orca refine <spec.md>` | Convert raw spec to validated spec.ir.json using pi |
| `orca decompose <spec.json> [desc]` | Parse IR into hierarchical task tree |
| `orca claim` | Atomically claim the highest-priority available task |
| `orca heartbeat <task-id>` | Update heartbeat (called every 30s by `orca loop`) |
| `orca complete <task-id> --result <text>` | Mark task completed (tests verified by default) |
| `orca fail <task-id> --error <text>` | Mark task failed (`--permanent` to keep out of pool) |
| `orca status` | Show all tasks grouped by status |
| `orca list --status <state>` | Filter tasks by status (available/claimed/completed/failed/validation/blocked) |
| `orca reclaim` | Manually reclaim stale tasks |
| `orca log <task-id>` | Show full task run history |
| `orca info <task-id>` | Show task details |
| `orca loop [--claim-only]` | Spawn a Ralph loop (uses pi CLI) |
| `orca validate-scenarios <feature_id>` | Run hidden scenario validation for a feature |
| `orca validate-scenarios --check-all` | Validate all complete features |

All commands accept `--json` for machine-readable output.

## Task Lifecycle

```
available ──claim──> claimed ──complete──> completed
                      │                        ▲
                      ├──fail──> failed ───────┘
                      │
                      └──(last child of feature completes)──> validation ──pass──> completed
                                                               │
                                                               │ fail
                                                               ▼
                                                          [hidden tasks created]
                                                               │
                                                               │ (hidden tasks complete)
                                                               ◄───────────────────────
```

### Phase 2: Validation & Blocked States

| State | Meaning |
|-------|---------|
| `available` | Task is in the backlog, unclaimed |
| `claimed` | A loop is actively working on this task |
| `completed` | Successfully finished |
| `failed` | Finished with an error (permanent or retryable) |
| `validation` | Feature root locked while hidden scenario validation runs |
| `blocked` | Cannot be claimed — child of a validation-locked tree |

During validation:
- The feature root is in `validation` state
- All children are in `blocked` state (cannot be claimed)
- Loops can still work on other features

### Reclaiming stale tasks

If a loop crashes while holding a task (e.g., the terminal was closed, the process was killed), the task stays in `claimed` status forever. The reclaim mechanism handles this:

1. Loops call `orca heartbeat` every **30 seconds** while working
2. After **5 minutes** without a heartbeat, the task is considered stale
3. `orca reclaim` (called automatically before `orca claim`) returns stale tasks to `available`
4. The next loop to claim will pick them up

You can also manually trigger reclaim:

```bash
orca reclaim
```

## How atomic claiming works

```python
conn.execute("BEGIN IMMEDIATE")          # Acquires write lock
row = conn.execute("""                   # SELECT is fast, no lock needed
    SELECT id FROM tasks
    WHERE status = 'available'
      AND (parent_id IS NULL
           OR parent_id NOT IN (SELECT id FROM tasks WHERE status = 'validation'))
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
""").fetchone()

if row is None:
    conn.rollback()
    return None  # Empty backlog

conn.execute(                            # UPDATE is now safe
    "UPDATE tasks SET status='claimed' WHERE id=?",
    (row[0],)
)
conn.commit()
```

If two loops call `claim` simultaneously, SQLite's `BEGIN IMMEDIATE` ensures only one writer proceeds — the other gets an empty result and can retry after a backoff.

**Phase 2 enhancement:** The claim query excludes children of validation-locked roots, preventing loops from working on blocked feature trees.

## Hidden Scenario Validation

When the last child of a feature root completes, validation triggers automatically:

1. **Tree locking** — Root moves to `validation`, children to `blocked`
2. **pi prompt** — Red-team assistant reads spec + code, generates pytest tests
3. **Test execution** — pytest runs against committed code
4. **Result handling:**
   - All pass → unlock tree, root `completed`, children `available`
   - Some fail → hidden tasks created as blocked children

```bash
# Manually run validation on a feature
orca validate-scenarios FEAT-001

# Validate all complete features
orca validate-scenarios --check-all
```

### Hidden scenario categories

| Category | Examples |
|----------|----------|
| Error handling | Null/empty inputs, exception paths |
| Semantic gaps | Return type, sort stability, equality |
| Adversarial inputs | Unicode homoglyphs, SQL injection, XSS |
| Behavioral gaps | File size limits, timeout handling |

## Loop identity

Loops identify themselves with a UUID. Resolution order:

1. `--loop-id` command-line argument
2. `ORCH_LOOP_ID` environment variable
3. `~/.orch/loop_id` file (created automatically on first use)

When using `orca loop`, a fresh UUID is generated for each invocation.

## Directory structure

```
project-root/
├── orca/               # Python package
│   ├── __main__.py    # CLI entry point
│   ├── commands/       # Command handlers
│   │   ├── validate_scenarios.py  # Phase 2: Hidden scenario validation
│   │   ├── complete.py            # Phase 2: Auto-trigger validation
│   │   └── ...
│   ├── db/             # Database schema & connection
│   │   ├── schema.py   # Phase 2: validation/blocked states
│   │   └── migrations/ # Phase 2: migration scripts
│   ├── models/         # Data access layer (Task, TaskRun, Loop)
│   └── utils/          # Identity, time, IR validator utilities
├── .orch/              # Created by `orca init` — add to .gitignore
│   ├── orch.db         # SQLite WAL database
│   ├── hidden_scenarios/  # Phase 2: Generated pytest tests
│   └── tasks/          # Copied spec files
├── pyproject.toml      # Package configuration (no external deps!)
└── README.md
```

### Important: Add `.orch/` to your `.gitignore`

The `.orch/` directory contains local database, task state, and generated tests — it should not be committed:

```gitignore
# Orca orchestrator (task coordination state)
.orch/
```

## Database schema

The SQLite database has four tables:

**tasks** — Task backlog
- `id`, `spec_path`, `description`, `status`, `priority`
- `created_at`, `claimed_at`, `completed_at`, `result_summary`
- `parent_id` (for sub-tasks from decompose), `root_spec_path`
- `ir_snippet` (JSON IR section for IR-based tasks)

**task_runs** — Run history per task
- `id`, `task_id`, `loop_id`
- `claimed_at`, `heartbeat_at`, `completed_at`
- `exit_status`, `result_summary`

**loops** — Registered loop state
- `id`, `name`, `started_at`, `last_heartbeat_at`, `current_task_id`

**hidden_scenario_runs** — HSV execution audit trail (Phase 2)
- `id`, `feature_id`, `loop_id`
- `generated_at`, `scenarios_found`, `scenarios_passed/failed/errored`
- `duration_ms`, `output_snippet`

## Troubleshooting

### "No loop ID found"

Run `orca init` first, or the `orca loop` command generates one automatically.

### Task stuck in `claimed` status

The loop that claimed it crashed. Run reclaim to free it:

```bash
orca reclaim
orca status   # verify it's back to available
```

### "Orchestrator not initialized"

Run `orca init` in the project directory:

```bash
cd /path/to/your/project
orca init
```

### "pi CLI not found"

Install the [pi coding agent](https://github.com/mariozechner/pi-coding-agent) for `orca loop` to work:

```bash
pipx install @mariozechner/pi-coding-agent
```

### "No code files found" during validation

Ensure the feature root has `root_spec_path` set correctly. Orca scans the directory containing `spec.ir.json` for code files.

### Feature stuck in `validation` state

Run validation to complete or unlock:

```bash
orca validate-scenarios <feature_id>
```

Or check all features:

```bash
orca validate-scenarios --check-all
```

### Check database integrity

```bash
sqlite3 .orch/orch.db "PRAGMA integrity_check;"
```

### View raw database (debugging)

```bash
# List all tasks
sqlite3 .orch/orch.db "SELECT id, status, priority, description FROM tasks;"

# View hidden scenario runs
sqlite3 .orch/orch.db "SELECT * FROM hidden_scenario_runs;"

# View pending heartbeats
sqlite3 .orch/orch.db "SELECT * FROM task_runs WHERE completed_at IS NULL;"

# Reset database (nuclear option)
rm .orch/orch.db && orca init
```

### Verbose logging

Orca outputs minimal info by default. For debugging, pipe to `cat` to see all output:

```bash
orca --json status | jq .
```

## Future enhancements

- [x] `orca validate-scenarios` — hidden scenario validation
- [ ] `orca loops` — spawn multiple loops in new terminal windows
- [ ] `orca run` — full pipeline: refine → decompose → loops
- [ ] `orca metrics` — loop throughput, avg task duration
- [ ] `orca serve` — optional HTTP API for web dashboards
- [ ] `orca deps add <task-id> <depends-on>` — task dependencies
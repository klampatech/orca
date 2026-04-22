<img width="512" height="512" alt="ORCA_LOGO2" src="https://github.com/user-attachments/assets/9b10752e-aad3-4b07-8a6f-ef9838843f2f" />


# Orca Orchestrator

A shared task coordination system for multiple autonomous Ralph loops running on the same machine.

## Overview

Orca is an orchestration layer that manages task backlogs and spawns Ralph loops — autonomous AI coding agents that continuously work through tasks: read spec → pick task → implement → test → commit → repeat.

The orchestrator provides:

- **Atomic task claiming** — SQLite `BEGIN IMMEDIATE` transactions prevent two loops from claiming the same task
- **Heartbeat + expiry** — loops that crash have their tasks automatically reclaimed after 5 minutes
- **Priority ordering** — highest-priority tasks are claimed first, FIFO within same priority
- **Full task history** — every claim, completion, and failure is tracked with timestamps
- **Built-in Ralph loop spawning** — `orca loop` spawns Ralph loops that use the [pi](https://github.com/mariozechner/pi-coding-agent) CLI to implement tasks with TDD
- **No daemon required** — invoke the CLI tool directly, no service to manage

## Requirements

- Python 3.10+
- SQLite 3 (included with Python's stdlib)
- [pi](https://github.com/mariozechner/pi-coding-agent) CLI (for `orca loop`)

## Installation

```bash
# Install globally with pipx (recommended on macOS)
pipx install /path/to/orca

# Or install with pip
pip install /path/to/orca
```

After installation, the `orca` command is available globally in any directory.

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

### 2. Add tasks to the backlog

```bash
# Add a task with a spec file
orca add path/to/spec.json "Implement user authentication"

# Add a task with priority (higher = claimed first)
orca add - "Add unit tests for auth" --priority 5

# Add a low-priority task
orca add - "Refactor error messages" --priority -1
```

### 3. Decompose a TDD spec into tasks

Write a markdown spec with `Feature:` and `Scenario:` headings, then decompose it into claimable tasks:

```bash
# Preview what would be created (dry-run)
orca decompose path/to/spec.md --dry-run

# Decompose into tasks
orca decompose path/to/spec.md

# With custom priority base
orca decompose path/to/spec.md --priority 5
```

Example spec:

```markdown
# Feature: User Authentication

## Scenario: User logs in successfully
Given the user is on the login page
When the user enters valid credentials
Then the user should see the dashboard
```

This creates:
- **1 spec-root task** (P10) — the whole feature, for tracking
- **1 sub-task per scenario** (P0) — each scenario is independently claimable

Sub-tasks are linked to their parent via `parent_id`, so loops can trace a task back to its source spec.

### 4. Spawn a Ralph loop

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

## Commands

| Command | Description |
|---------|-------------|
| `orca init` | Initialize orchestrator in current directory |
| `orca add <spec> <desc>` | Add task with optional spec path and `--priority N` |
| `orca decompose <spec.md> [desc]` | Decompose a markdown TDD spec into tasks |
| `orca claim` | Atomically claim the highest-priority available task |
| `orca heartbeat <task-id>` | Update heartbeat (called every 30s by `orca loop`) |
| `orca complete <task-id> --result <text>` | Mark task completed (tests verified by default) |
| `orca fail <task-id> --error <text>` | Mark task failed (`--permanent` to keep out of pool) |
| `orca status` | Show all tasks grouped by status |
| `orca list --status available` | Filter tasks by status |
| `orca reclaim` | Manually reclaim stale tasks |
| `orca log <task-id>` | Show full task run history |
| `orca info <task-id>` | Show task details |
| `orca loop [--claim-only]` | Spawn a Ralph loop (uses pi CLI) |
| `orca loops <n>` | Spawn N Ralph loops (not yet implemented) |

All commands accept `--json` for machine-readable output.

## Task Lifecycle

```
available ──claim──> claimed ──complete──> completed
                      │                        ▲
                      └──fail──> failed ───────┘
                          │
         (heartbeat expires after 5min) ──> available
```

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
│   ├── db/             # Database schema & connection
│   ├── models/         # Data access layer (Task, TaskRun, Loop)
│   └── utils/           # Identity & time utilities
├── .orch/              # Created by `orca init`
│   ├── orch.db         # SQLite WAL database
│   └── tasks/          # Copied spec files
├── pyproject.toml
└── README.md
```

## Database schema

The SQLite database has three tables:

**tasks** — Task backlog
- `id`, `spec_path`, `description`, `status`, `priority`
- `created_at`, `claimed_at`, `completed_at`, `result_summary`
- `parent_id` (for sub-tasks from decompose), `root_spec_path`

**task_runs** — Run history per task
- `id`, `task_id`, `loop_id`
- `claimed_at`, `heartbeat_at`, `completed_at`
- `exit_status`, `result_summary`

**loops** — Registered loop state
- `id`, `name`, `started_at`, `last_heartbeat_at`, `current_task_id`

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

### Check database integrity

```bash
sqlite3 .orch/orch.db "PRAGMA integrity_check;"
```

## Future enhancements

- [ ] `orca loops` — spawn multiple loops in new terminal windows
- [ ] `orca deps add <task-id> <depends-on>` — task dependencies
- [ ] `orca metrics` — loop throughput, avg task duration
- [ ] `orca serve` — optional HTTP API for web dashboards

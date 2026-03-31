# Ralph Loop Orchestrator

A shared task coordination system for multiple autonomous Ralph loops running on the same machine.

## Overview

Ralph is an autonomous AI coding methodology where Claude Code loops continuously: read plan → pick task → implement → test → commit → clear context → repeat. When running multiple loops concurrently, they need a coordination layer so they don't claim the same task, crashed loops have their work reclaimed, and work is distributed fairly.

The orchestrator provides:

- **Atomic task claiming** — SQLite `BEGIN IMMEDIATE` transactions prevent two loops from claiming the same task
- **Heartbeat + expiry** — loops that crash have their tasks automatically reclaimed after 60 seconds
- **Priority ordering** — highest-priority tasks are claimed first, FIFO within same priority
- **Full task history** — every claim, completion, and failure is tracked with timestamps
- **No daemon required** — loops invoke a single CLI tool, no service to manage

## Requirements

- Python 3.10+
- SQLite 3 (included with Python's stdlib)

No external dependencies.

## Quickstart

### 1. Initialize the orchestrator

```bash
cd your-ralph-project
python3 orch.py init
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

### 4. Start a Ralph loop

```bash
# Generate your loop's identity (only needed once)
export ORCH_LOOP_ID=$(uuidgen)

# Claim a task
TASK_ID=$(orca --json claim | jq -r '.task_id')

# If no task available, wait and retry
if [ "$TASK_ID" = "null" ] || [ -z "$TASK_ID" ]; then
    echo "No tasks available, waiting 10s..."
    sleep 10
    exit 0
fi

# Start heartbeat loop in background (every 30s)
while true; do
    orca heartbeat "$TASK_ID"
    sleep 30
done &
HEARTBEAT_PID=$!

# Do the actual Ralph loop work
SPEC=$(orca --json info "$TASK_ID" | jq -r '.spec_path')
echo "Working on task $TASK_ID with spec $SPEC"

# ... implement, test, commit ...

# Mark done
orca complete "$TASK_ID" --result "All tests passing, PR merged"

# Stop heartbeat
kill $HEARTBEAT_PID 2>/dev/null
```

### 5. Run a second loop (in another terminal)

```bash
# Same setup, different terminal
export ORCH_LOOP_ID=$(uuidgen)
orca --json claim
```

Both loops share the same `.orch/orch.db`. They will never claim the same task — the first to call `orca claim` wins.

## Commands

| Command | Description |
|---------|-------------|
| `orca init` | Initialize orchestrator in current directory |
| `orca add <spec> <desc>` | Add task with optional spec path and `--priority N` |
| `orca decompose <spec.md> [desc]` | Decompose a markdown TDD spec into tasks |
| `orca claim` | Atomically claim the highest-priority available task |
| `orca heartbeat <task-id>` | Update heartbeat (call every 30s while working) |
| `orca complete <task-id> --result <text>` | Mark task successfully completed |
| `orca fail <task-id> --error <text>` | Mark task failed |
| `orca status` | Show all tasks grouped by status |
| `orca list --status available` | Filter tasks by status |
| `orca reclaim` | Manually reclaim stale tasks |
| `orca log <task-id>` | Show full task run history |
| `orca info <task-id>` | Show task details |

All commands accept `--json` for machine-readable output.

## Task Lifecycle

```
available ──claim──> claimed ──complete──> completed
                      │                        ▲
                      └──fail──> failed ───────┘
                          │
         (heartbeat expires after 60s) ──> available
```

### Reclaiming stale tasks

If a loop crashes while holding a task (e.g., the terminal was closed, the process was killed), the task stays in `claimed` status forever. The reclaim mechanism handles this:

1. Loops call `orca heartbeat` every **30 seconds** while working
2. After **60 seconds** without a heartbeat, the task is considered stale
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

```bash
# Option A: environment variable
export ORCH_LOOP_ID=$(uuidgen)

# Option B: persistent identity file
mkdir -p ~/.orch
echo $(uuidgen) > ~/.orch/loop_id

# Option C: pass on each command
orca --json claim --loop-id my-loop-1
```

## Directory structure

```
project-root/
├── orch.py              # CLI entry point
├── db/
│   ├── schema.py        # SQLite schema
│   └── connection.py    # WAL-mode connection helper
├── commands/            # One file per command
├── models/              # Data access layer
├── utils/               # Identity + time helpers
└── .orch/              # Created by `orch init`
    ├── orch.db         # SQLite WAL database
    └── config          # Future: per-project config
```

## Scheduling multiple loops

The orchestrator works with any scheduler that can run multiple Claude Code processes. Example with a simple shell loop that waits for available tasks:

```bash
# Launch 3 loops in background
for i in 1 2 3; do
    (
        export ORCH_LOOP_ID="loop-$i-$(date +%s)"
        while true; do
            TASK=$(orca --json claim | jq -r '.task_id')
            if [ "$TASK" != "null" ] && [ -n "$TASK" ]; then
                echo "[loop-$i] Claimed $TASK"
                # orca heartbeat "$TASK" &
                # ... do work ...
                orca complete "$TASK" --result "Done"
            else
                echo "[loop-$i] No tasks, sleeping 30s..."
                sleep 30
            fi
        done
    ) &
done
wait
```

## Troubleshooting

### "No loop ID found"

Run `orca init` first, or set `ORCH_LOOP_ID`:

```bash
export ORCH_LOOP_ID=$(uuidgen)
```

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

### Concurrent claim race condition

SQLite handles this via `BEGIN IMMEDIATE`. If two loops race, one wins and the other gets an empty result. The losing loop should back off and retry:

```bash
TASK=$(orca --json claim | jq -r '.task_id')
if [ -z "$TASK" ] || [ "$TASK" = "null" ]; then
    sleep 5
    TASK=$(orca --json claim | jq -r '.task_id')
fi
```

### Check database integrity

```bash
sqlite3 .orch/orch.db "PRAGMA integrity_check;"
```

## Future enhancements

- [ ] `orca deps add <task-id> <depends-on>` — task dependencies
- [ ] `orca metrics` — loop throughput, avg task duration
- [ ] `orca serve` — optional HTTP API for web dashboards
- [ ] Installable via `pip install orca` (add `pyproject.toml`)

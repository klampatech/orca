#!/usr/bin/env python3
"""Ralph Loop Orchestrator — Shared task coordination for autonomous Ralph loops.

Usage:
    orca init [--loop-id ID]
    orca add <spec> <description> [--priority N]
    orca decompose <spec.md> [--priority N] [--dry-run]
    orca refine <spec.md> [--output <path>] [--max-iterations N] [--pi-skill <name>]
    orca claim [--loop-id ID]
    orca heartbeat <task-id> [--loop-id ID]
    orca complete <task-id> [--loop-id ID] [--result TEXT]
    orca fail <task-id> [--loop-id ID] [--error TEXT]
    orca status
    orca list [--status available|claimed|completed|failed]
    orca reclaim
    orca log <task-id>
    orca info <task-id>
    orca loop [--claim-only]
    orca loops <n> [--claim-only]
"""

from __future__ import annotations

import argparse
import json
import sys

from .commands import COMMANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orca",
        description="Ralph Loop Orchestrator — Shared task coordination for autonomous Ralph loops.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # init
    sub.add_parser("init", help="Initialize orchestrator in current directory")

    # add
    add = sub.add_parser("add", help="Add a task to the backlog")
    add.add_argument("spec", nargs="?", help="Path to spec file (optional)")
    add.add_argument("description", help="Task description")
    add.add_argument("--priority", type=int, default=0, help="Task priority (default: 0)")

    # claim
    claim = sub.add_parser("claim", help="Atomically claim an available task")
    claim.add_argument("loop_id", nargs="?", help="Loop ID (default: resolved from env or ~/.orch/loop_id)")

    # heartbeat
    heartbeat = sub.add_parser("heartbeat", help="Update heartbeat for an active task")
    heartbeat.add_argument("task_id", help="Task ID")
    heartbeat.add_argument("loop_id", nargs="?", help="Loop ID (default: resolved automatically)")

    # complete
    complete = sub.add_parser("complete", help="Mark a task as completed (runs tests by default)")
    complete.add_argument("task_id", help="Task ID")
    complete.add_argument("loop_id", nargs="?", help="Loop ID (default: resolved automatically)")
    complete.add_argument("--result", help="Result summary")
    complete.add_argument("--no-verify", action="store_true", help="Skip test verification (use with caution)")

    # fail
    fail = sub.add_parser("fail", help="Mark a task as failed (returns to pool by default)")
    fail.add_argument("task_id", help="Task ID")
    fail.add_argument("loop_id", nargs="?", help="Loop ID (default: resolved automatically)")
    fail.add_argument("--error", help="Error message")
    fail.add_argument("--permanent", action="store_true", help="Mark as permanently failed (not returned to pool)")

    # status
    sub.add_parser("status", help="Show all tasks grouped by status")

    # list
    lst = sub.add_parser("list", help="List tasks (optionally filtered)")
    lst.add_argument(
        "--status",
        choices=["available", "claimed", "completed", "failed"],
        help="Filter by status",
    )

    # reclaim
    sub.add_parser("reclaim", help="Reclaim tasks with expired heartbeats")

    # log
    log = sub.add_parser("log", help="Show task run history")
    log.add_argument("task_id", help="Task ID")

    # info
    info = sub.add_parser("info", help="Show detailed task information")
    info.add_argument("task_id", help="Task ID")

    # decompose
    decomp = sub.add_parser("decompose", help="Decompose a markdown TDD spec into tasks")
    decomp.add_argument("spec", help="Path to markdown TDD spec file")
    decomp.add_argument("description", nargs="?", help="Override feature title")
    decomp.add_argument("--priority", type=int, default=0, help="Base priority (default: 0)")
    decomp.add_argument("--dry-run", action="store_true", help="Show tasks without creating them")

    # refine
    refine = sub.add_parser("refine", help="Refine raw spec into valid spec.ir.json using pi")
    refine.add_argument("spec", help="Path to raw spec file (any format)")
    refine.add_argument("--output", help="Override output path (default: <spec-dir>/spec.ir.json)")
    refine.add_argument("--max-iterations", type=int, default=5, help="Max refine loops (default: 5)")
    refine.add_argument("--pi-skill", default="ir-spec-generator", help="pi skill to use (default: ir-spec-generator)")

    # loop
    loop = sub.add_parser("loop", help="Spawn a Ralph loop in a new terminal window")
    loop.add_argument("--claim-only", action="store_true", help="Claim one task and exit immediately")

    # loops
    loops = sub.add_parser("loops", help="Spawn multiple Ralph loops")
    loops.add_argument("n", type=int, help="Number of loops to spawn")
    loops.add_argument("--claim-only", action="store_true", help="Claim one task per loop and exit immediately")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command not in COMMANDS:
        parser.print_help()
        return 1

    handler, formatter = COMMANDS[args.command]

    try:
        result = handler(args)
    except RuntimeError as e:
        if args.json:
            print(json.dumps({"command": args.command, "status": "error", "message": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        if args.json:
            print(json.dumps({"command": args.command, "status": "error", "message": f"{type(e).__name__}: {e}"}))
        else:
            print(f"Unexpected error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(formatter(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())

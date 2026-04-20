# Orca IR Validator + Decompose — Phase 1 Spec

**Project:** Two-Pass Spec Validation with Parallel Ralph Loop Execution  
**Phase:** 1 of 2  
**Date:** 2026-04-20  
**Status:** Spec — pending implementation  

---

## Overview

Combines the IR validator (`agate-ir-validator`) with Orca's task orchestration to create a structured pipeline: **raw spec → validated IR → decomposed tasks → parallel Ralph loops**.

The validator ensures structural integrity of the IR. Orca handles task decomposition and parallel execution. The division of labor:

| Component | Responsibility |
|-----------|----------------|
| `pi` + custom skill | Generate and iteratively refine `spec.ir.json` from raw spec |
| `orca refine` | Orchestrate `pi` calls, validate output, detect stability |
| IR Validator | Structural validation of `spec.ir.json` against schema |
| `orca decompose` | Convert validated IR into claimable Orca tasks |
| Ralph loops | Claim tasks, implement, validate via pytest |

---

## The Pipeline

```
spec.md
    │
    ▼ orca refine
┌─────────────────────┐
│  pi + IR skill       │ ← produces spec.ir.json
│  (fresh session/loop) │
└────────┬────────────┘
         │
         ▼ validate
┌─────────────────────┐
│  IR Validator       │ ← blocks if invalid
│  (Python stdlib)    │
└────────┬────────────┘
         │
    ┌────┴────┐
    │ invalid? │
    └────┬────┘
         │
    yes  │  no
    ┌────┴────────────┐
    │ extract errors   │
    │ pi again         │ ← fresh session with errors fed back
    │ (max 5 loops)   │
    └────┬────────────┘
         │ stable hash (2 consecutive same) → stop, report to user
         │
         ▼ valid + stable
    spec.ir.json
         │
         ▼ orca decompose (manual)
    ORCA TASK TREE
         │
         ▼ orca loop (parallel N)
    Ralph loops → implement → pytest → complete/fail
```

**Manual trigger:** `orca decompose` is called manually after `orca refine` completes. Future phases automate this.

---

## Command: `orca refine <spec.md>`

### Purpose

Take a raw spec (any format) and iteratively refine it into a valid, stable `spec.ir.json` using `pi` + custom skill + IR validator.

### Input

- `<spec.md>` — Path to raw spec file (any format: PRD, brain dump, partial notes, structured text)

### Behavior

1. **Call `pi`** with the following prompt:
   - Inject raw spec.md content
   - Load IR generation skill (pre-made pi skill, user-defined)
   - Ask pi to emit `spec.ir.json` conforming to `spec-schema.json`

2. **Write output** to `spec.ir.json` in the same directory as `<spec.md>`

3. **Validate** output using bundled IR validator

4. **If invalid:**
   - Extract errors from validator output
   - Call `pi` again (fresh session) with:
     - Current `spec.ir.json`
     - Validation errors
     - Instruction to fix and emit new `spec.ir.json`
   - Track hash of output (md5)
   - Loop until: valid OR stable hash (2 consecutive same) OR max 5 iterations

5. **If stable but invalid after max iterations:** Report to user with validation errors, suggest manual review

6. **If valid:** Report success, path to `spec.ir.json`

### Output

- `spec.ir.json` written to spec.md directory
- Console output: iteration count, validation result, path to output file

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output <path>` | `<spec.md directory>/spec.ir.json` | Override output path |
| `--max-iterations <n>` | 5 | Max refine loops before giving up |
| `--pi-skill <name>` | `ir-spec-generator` | pi skill to use |

### Error Handling

- `pi` not found → error + install instructions
- Schema file missing → error (should not happen in bundled setup)
- Max iterations reached → report final validation errors, suggest manual intervention

---

## Command: `orca decompose <spec.json>`

### Purpose

Decompose a validated `spec.ir.json` into a task tree of independently claimable tasks.

### Input

- `<spec.json>` — Path to `spec.ir.json` (validated)
- Automatically detects format: JSON IR vs Gherkin markdown by file extension (.json vs .md)

### Behavior

1. **Validate schema** using bundled IR validator (blocks if invalid — should not happen post-refine)

2. **Parse JSON IR** — read `spec.ir.json`, extract:
   - `coreFeatures.mustHave`, `shouldHave`, `niceToHave`
   - Per feature: `id`, `description`, `edgeCases`
   - `acceptanceCriteria`: happyPath, errorHandling per feature

3. **Build task hierarchy:**
   ```
   FEAT-001 (mustHave) [parent, P10]
   ├── Scenario: happy path acceptance criteria  [child, P8]
   │   └── Edge case: X  [grandchild, P6]
   │   └── Edge case: Y  [grandchild, P6]
   ├── Scenario: error handling acceptance criteria  [child, P8]
       └── Edge case: Z  [grandchild, P6]
   ```

4. **IR snippet stored per task** — each task record stores the relevant IR snippet (feature + edge cases + acceptance criteria) in a dedicated field for injection at claim time

5. **Feature ID in description** — task description embeds IR reference, e.g.:
   `FEAT-001/AC-001 | Edge: invalid email format | Implement email validation`

6. **Copy spec** to `.orch/tasks/` (consistent with existing decompose behavior)

7. **Insert tasks** into Orca SQLite database with proper parent-child links

### Task Priority

| Tier | Priority |
|------|----------|
| mustHave | P10 |
| shouldHave | P7 |
| niceToHave | P4 |
| Happy-path scenarios | P8 within parent |
| Edge cases | P6 within parent |
| Error-handling scenarios | P8 within parent |

### IR Snippet Injection Field

New database field `ir_snippet TEXT` added to `tasks` table. Stores the JSON IR section relevant to this task (feature description, edge cases, acceptance criteria).

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | false | Preview tasks without inserting to DB |
| `--priority-base <n>` | 0 | Base priority offset |

### Error Handling

- Invalid JSON IR → error + validation output
- No features found → error with guidance
- Database write failure → rollback + error

---

## Database Schema Changes

### New Column: `tasks.ir_snippet`

```sql
ALTER TABLE tasks ADD COLUMN ir_snippet TEXT;
```

### Updated `tasks` Table

```sql
CREATE TABLE IF NOT EXISTS tasks (
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
    ir_snippet      TEXT,  -- NEW: JSON IR section for this task
    CHECK (status IN ('available', 'claimed', 'completed', 'failed'))
);
```

---

## Claim Time: IR Snippet Injection

When a Ralph loop calls `orca claim` and receives a task, Orca should provide the `ir_snippet` alongside the task details. Currently `orca info` returns task fields; the calling loop would access `ir_snippet` from the returned task record.

**Implementation note:** The `pi` coding agent prompt in `orca/commands/loop.py` (`_do_work`) currently builds a prompt from `description` and optionally `spec_path`. This should be extended to also inject `ir_snippet` content directly into the prompt so the loop has the full spec without reading a file.

**Updated `_do_work` prompt injection:**
```
## IR Spec Snippet (do not skip — this defines what "done" means)
{ir_snippet}

## Scenario
{description}
...
```

---

## Bundled Artifacts

### Files Copied from `agate-ir-validator`

```
orca/orca/
├── utils/
│   └── validator.py           # Copied from agate-ir-validator/validator.py
│                               # Uses Python stdlib only, no external deps
└── data/
    └── spec-schema-v2.json   # Updated schema with per-feature acceptanceCriteria
```

### Schema: `spec-schema-v2.json`

Updated from `goal-schema.json` with per-feature acceptanceCriteria structure. Validates:
- Required fields present
- Field types correct
- Enum values valid (language, architecture, etc.)
- Feature IDs referenced in acceptance criteria exist
- Given/When/Then format in acceptance criteria
- Edge cases per feature
- Anti-cheating rules for microservices

**Does NOT validate:** Semantic accuracy, feature sufficiency for stated vision.

---

## Validation: Structural vs Semantic

| Check | Type | Phase |
|-------|------|-------|
| Schema fields present | Structural | IR validation |
| Feature IDs valid | Structural | IR validation |
| Given/When/Then format | Structural | IR validation |
| Feature sufficiency for vision | Semantic | Human review (out of scope) |
| Implementation delivers spec | Semantic | Phase 2 hidden validation |
| Tests pass | Functional | Ralph loop pytest |

---

## Out of Scope (Phase 1)

- Auto-decompose after `orca refine` completes (manual decompose call)
- Hidden scenario validation (Phase 2)
- Test scaffolding generation
- Semantic validation (feature sufficiency)
- Multi-project workspaces
- Task dependencies (`--depends-on`)
- `orca loops N` (parallel window spawning)

---

## Acceptance Criteria

### `orca refine`

- [ ] Accepts any text file as `<spec.md>` input
- [ ] Calls `pi` with IR skill to produce `spec.ir.json`
- [ ] Validates output against `spec-schema-v2.json`
- [ ] On invalid: extracts errors, calls `pi` again with errors (fresh session)
- [ ] Stops on: valid output OR 2 consecutive identical hashes OR 5 iterations
- [ ] Writes final `spec.ir.json` to same directory as input (or `--output` path)
- [ ] Reports iteration count and final status to console
- [ ] Errors gracefully if `pi` not found or skill missing
- [ ] `--max-iterations` flag respected
- [ ] `--output` flag respected

### `orca decompose` (IR path)

- [ ] Detects JSON IR vs Gherkin markdown by file extension
- [ ] Validates JSON IR against schema before decomposing (blocks if invalid)
- [ ] Creates parent task per feature tier (mustHave/shouldHave/niceToHave)
- [ ] Creates child task per acceptance criteria (happy path, error handling)
- [ ] Creates grandchild task per edge case
- [ ] Priority order: mustHave → shouldHave → niceToHave; within feature: happy-path → edge cases
- [ ] Task description includes IR feature ID (e.g., `FEAT-001/AC-001/edge-002`)
- [ ] `ir_snippet` field populated per task with relevant JSON IR section
- [ ] `--dry-run` flag previews without DB insert
- [ ] Copies spec to `.orch/tasks/`
- [ ] Parent-child links set correctly

### IR Snippet Injection

- [ ] `ir_snippet` stored in `tasks.ir_snippet` column
- [ ] `orca info <task-id>` returns `ir_snippet` field
- [ ] `orca loop` prompt includes `ir_snippet` content from claimed task
- [ ] Loops receive full spec context without reading spec file

### Bundling

- [ ] `validator.py` copied to `orca/orca/utils/validator.py` with no external dependencies
- [ ] `spec-schema-v2.json` bundled in `orca/orca/data/`
- [ ] No import errors when Orca imports validator module

---

## File Changes Summary

| File | Action |
|------|--------|
| `orca/orca/utils/validator.py` | Copy from `agate-ir-validator/validator.py` (updated with v2 schema support) |
| `orca/orca/data/spec-schema-v2.json` | Copy + rename from `agate-ir-validator/goal-schema.json` |
| `orca/db/schema.py` | Add `ir_snippet TEXT` to `tasks` table |
| `orca/db/INIT_SQL` | Updated CREATE TABLE with `ir_snippet` |
| `orca/commands/decompose.py` | Add JSON IR parsing path alongside Gherkin parsing |
| `orca/commands/refine.py` | **New command** — IR refine orchestration |
| `orca/commands/__init__.py` | Register `refine` command |
| `orca/orch.py` | Add `refine` to CLI subparsers |
| `orca/commands/loop.py` | Inject `ir_snippet` into prompt at claim time |
| `orca/models/task.py` | Update `create_task` to accept `ir_snippet` |

---

## References

- IR Validator: `~/Projects/agate-ir-validator/validator.py`
- Orca: `~/Projects/orca/`
- Schema: `agate-ir-validator/goal-schema.json` (will be renamed)
- pi coding agent: https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs

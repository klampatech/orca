# Implementation Plan: Ralph Planning Loop Refactor

## Overview
- **Created**: 2026-05-13
- **Objective**: Replace `orca refine` with a Ralph-style planning loop that iteratively builds an implementation plan from specs, and add commit hook validation to ensure implementations meet functional requirements
- **Scope**: 
  - New `orca plan` command (replaces `orca refine`)
  - Updated `orca decompose` to parse plan format
  - Git pre-commit hook for functional validation
  - Test generation system
- **Excluded**: Changes to existing `orca loop` execution logic (beyond retry behavior)

## Context Summary

### Current State
- `orca refine` uses a 3-phase approach (Generate → Audit → Refine) to create `spec.ir.json` from raw specs
- LLMs struggle with consistent JSON IR format generation
- No validation between implementation and spec requirements
- Tasks are decomposed into database but progress isn't reflected back to plan

### Target State
- `orca plan` generates a flexible markdown plan with structured task format `- [ ] TASK-NNN: <description>`
- Plan format is LLM-friendly but still decomposable
- Commit hook validates implementations against spec requirements
- Retry loop gets attempt summary (what was tried, how it failed) but not full error
- Discard failed implementation, let loop figure out fix

### Key Decisions
1. **Plan format**: Markdown with `- [ ] TASK-NNN:` task syntax
2. **Plan immutability**: Frozen after decomposition, database tracks execution
3. **Validation timing**: At commit time (local pre-commit hook)
4. **Retry behavior**: Discard changes + inject attempt summary
5. **Test scope**: Per-task functional validation
6. **Auto-detection**: Framework detection + dependency setup

---

## Phases

### Phase 1: Core Infrastructure

#### Task 1.1: Define Plan Schema
**Objective**: Define the canonical format for implementation plans
**Dependencies**: None

Create `orca/plan/schema.py`:
- Schema elements: header, project, spec, features, tasks, hash
- Validation utilities for format checking
- Task ID pattern: `TASK-\d+`
- Feature header pattern: `## FEAT-\d+:`

| Element | Description | Required |
|---------|-------------|----------|
| `# Implementation Plan` | Header | Yes |
| `**Project:**` | Project name | Yes |
| `**Spec:**` | Path to source spec | Yes |
| `## Features` | Feature groupings | Yes |
| `### FEAT-NNN:` | Feature header | Yes |
| `- [ ] TASK-NNN:` | Task line (checkbox format) | Yes |
| `**Plan Hash:**` | Hash of task list for stability detection | Yes |
| `---` | Separator before metadata | Yes |

**Files**:
- `orca/plan/schema.py` — Create

---

#### Task 1.2: Create Plan Parser
**Objective**: Utility to parse plan files into structured data
**Dependencies**: Task 1.1

Create `orca/plan/parser.py`:
- `parse_plan(path) -> Plan`
- `extract_tasks(plan) -> List[Task]`
- `extract_features(plan) -> Dict[str, List[Task]]`
- `compute_hash(plan) -> str`
- `validate_plan_format(path) -> bool`

**Files**:
- `orca/plan/parser.py` — Create

---

#### Task 1.3: Create Plan Generator
**Objective**: Generate plan from spec using LLM with iteration
**Dependencies**: Task 1.2

Create `orca/plan/generator.py`:
- `generate_plan(spec_path, max_iterations=10) -> Plan`
- Iteration loop: generate → hash → compare → stable when hash matches previous for 2 iterations
- Prompt building: gap analysis, task granularity, edge case inclusion
- LLM output format: markdown with `- [ ] TASK-NNN:` lines

**Files**:
- `orca/plan/generator.py` — Create

---

### Phase 2: Orca Plan Command

#### Task 2.1: Create `orca plan` Command
**Objective**: CLI command to invoke plan generation
**Dependencies**: Task 1.3

Create `orca/commands/plan.py`:
```python
def handle_plan(args):
    """Generate implementation plan from spec."""
    # Parse args (spec path, output path, max iterations)
    # Call generator
    # Validate output
    # Log completion
```

**CLI Interface**:
```bash
orca plan <spec.md> [options]

Options:
  --output, -o    Output path (default: IMPLEMENTATION_PLAN.md)
  --max-iterations N  Max iterations (default: 10)
  --pi-skill SKILL    Pi skill for LLM (default: plan)
  --force           Overwrite existing plan
```

**Files**:
- `orca/commands/plan.py` — Create

---

#### Task 2.2: Update Command Registry
**Objective**: Register `orca plan` in CLI
**Dependencies**: Task 2.1

Update `orca/__main__.py`:
- Add `plan` subcommand
- Add command alias/description

**Files**:
- `orca/__main__.py` — Modify

---

#### Task 2.3: Remove `orca refine`
**Objective**: Remove old refinement command
**Dependencies**: Task 2.2

**Actions**:
- Remove `orca/commands/refine.py`
- Update `orca/commands/__init__.py` (remove refine)
- Update `orca/__main__.py` (remove refine command)
- Update documentation/README

**Files**:
- `orca/commands/refine.py` — Delete
- `orca/commands/__init__.py` — Modify
- `orca/__main__.py` — Modify
- `README.md` — Modify

---

### Phase 3: Decompose Integration

#### Task 3.1: Update Decompose Parser
**Objective**: Add plan format detection to `orca decompose`
**Dependencies**: Task 1.2

Update `orca/commands/decompose.py`:
- Add detection for plan format (check for `TASK-\d+` patterns)
- Add parser function: `_parse_plan_format(spec_path) -> (tasks, feature_blocks)`
- Extract tasks from `- [ ] TASK-NNN:` lines
- Group by feature sections (`## FEAT-NNN:` or implied)
- Generate task records matching existing structure

**Files**:
- `orca/commands/decompose.py` — Modify

---

#### Task 3.2: Test Decompose with Plan Format
**Objective**: Verify decompose works with generated plans
**Dependencies**: Task 3.1

**Actions**:
- Generate test plan file
- Run `orca decompose test-plan.md --dry-run`
- Verify tasks extracted correctly
- Verify feature grouping works
- Add integration tests

**Files**:
- `tests/integration/test_decompose_plan.py` — Create

---

### Phase 4: Validation Hook System

#### Task 4.1: Define Test Template Format
**Objective**: Create format for spec-based test templates
**Dependencies**: None

Create `orca/validate/templates.py`:

Test template format per task:
- TASK-XXX header
- Description of what task implements
- Functional requirements (numbered list)
- Test cases (Given/When/Then format)
- Edge cases to test

```markdown
## TASK-001: Login Endpoint

### Description
Implements user authentication via email/password

### Functional Requirements
1. Accept POST /api/auth/login with {email, password}
2. Return JWT token on valid credentials
3. Return 401 on invalid credentials

### Test Cases
- TC-001: Valid credentials → HTTP 200, JWT in response
- TC-002: Invalid password → HTTP 401
```

**Files**:
- `orca/validate/templates.py` — Create

---

#### Task 4.2: Create Test Generator
**Objective**: Generate actual test code from templates
**Dependencies**: Task 4.1

Create `orca/validate/generator.py`:
- `generate_tests(task, spec_template, impl_path) -> List[TestFile]`
- Framework detection (pytest/Jest/Go test/etc.)
- Template-to-code conversion
- Test file creation

**Framework Support**:
| Framework | Detection | Template |
|-----------|-----------|----------|
| pytest | `pyproject.toml`, `pytest.ini` | Python unittest/pytest |
| Jest | `package.json`, `jest.config.js` | JavaScript/Jest |
| Go test | `go.mod` | Go testing package |
| RSpec | `Gemfile` | Ruby RSpec |

**Files**:
- `orca/validate/generator.py` — Create

---

#### Task 4.3: Create Validation Engine
**Objective**: Core validation logic
**Dependencies**: Task 4.2

Create `orca/validate/engine.py`:
```python
class ValidationEngine:
    def validate(task_id, spec_path, impl_path) -> ValidationResult:
        # 1. Load task spec from plan
        # 2. Generate test code from template
        # 3. Setup test environment (install deps)
        # 4. Run tests
        # 5. Return pass/fail + details
        
    def generate_summary(failed_attempt) -> AttemptSummary:
        # Generate context summary for retry
        # "What was tried" + "How it failed" (no full error)
```

**Files**:
- `orca/validate/engine.py` — Create

---

#### Task 4.4: Create Pre-commit Hook
**Objective**: Git hook for commit validation
**Dependencies**: Task 4.3

Create `orca/hooks/pre_commit.py`:
```bash
#!/bin/bash
# .git/hooks/pre-commit (installed by orca init)
orca validate --staged --commit-msg "$1"
```

Create installation utility:
- `orca install-hooks` — Install pre-commit hook
- Hook location: `.git/hooks/pre-commit`
- Backup existing hook if present

**Files**:
- `orca/hooks/pre_commit.py` — Create
- `orca/hooks/__init__.py` — Create

---

#### Task 4.5: Update Loop Retry Logic
**Objective**: Implement retry with attempt summary
**Dependencies**: Task 4.4

Update `orca/commands/loop.py`:
```python
def handle_retry(task_id, attempt_summary):
    # 1. Reset changes (git reset --hard)
    # 2. Inject attempt summary into context
    # 3. Re-claim task
    # 4. Fresh implementation attempt
```

**Attempt Summary Format**:
```markdown
# Attempt Summary for TASK-001

**Previous attempt at**: 2026-05-13T10:30:00

## What Was Tried
- Implemented login endpoint at /api/auth/login
- Added JWT token generation using auth0

## How It Failed
- Functional validation tests failed
- Implementation did not match acceptance criteria

## Spec Reference
[Spec requirements for TASK-001 remain unchanged]
```

**Files**:
- `orca/commands/loop.py` — Modify

---

### Phase 5: Dependencies & Setup

#### Task 5.1: Create Dependency Installer
**Objective**: Auto-install test dependencies
**Dependencies**: Task 4.2

Create `orca/validate/installer.py`:
```python
def ensure_test_deps(project_path) -> bool:
    # Detect project type
    # Install appropriate test packages
    # Return success/failure
```

**Supported Installations**:
- `npm install` (Node.js)
- `pip install pytest` (Python)
- `go get -t ./...` (Go)
- `bundle install` (Ruby)

**Files**:
- `orca/validate/installer.py` — Create

---

#### Task 5.2: Update `orca init`
**Objective**: Install hooks during init
**Dependencies**: Task 4.4

Update `orca/commands/init.py`:
- Call hook installer after creating `.orch/`
- Warn if hooks already exist

**Files**:
- `orca/commands/init.py` — Modify

---

### Phase 6: Documentation & Tests

#### Task 6.1: Write Unit Tests
**Objective**: Test coverage for all new components
**Dependencies**: Phases 1-5

**Test Files to Create**:
- `tests/unit/plan/test_schema.py`
- `tests/unit/plan/test_parser.py`
- `tests/unit/plan/test_generator.py`
- `tests/unit/validate/test_templates.py`
- `tests/unit/validate/test_generator.py`
- `tests/unit/validate/test_engine.py`
- `tests/unit/validate/test_installer.py`
- `tests/unit/hooks/test_pre_commit.py`

**Test Coverage Target**: 80%+

**Files**:
- `tests/unit/plan/` — Create directory
- `tests/unit/validate/` — Create directory
- `tests/unit/hooks/` — Create directory

---

#### Task 6.2: Update Documentation
**Objective**: Document new commands and hooks
**Dependencies**: Phase 2, 4

**Files to Update**:
- `README.md` — Add `orca plan` section, update command table
- `docs/` — Create new documentation files

**Documentation Sections**:
1. `docs/plan.md` — How to use `orca plan`
2. `docs/validate.md` — Validation system architecture
3. `docs/hooks.md` — Pre-commit hook setup and usage

**Files**:
- `README.md` — Modify
- `docs/plan.md` — Create
- `docs/validate.md` — Create
- `docs/hooks.md` — Create

---

## File Manifest

| Action | Path | Description |
|--------|------|-------------|
| Create | `orca/plan/__init__.py` | Plan module init |
| Create | `orca/plan/schema.py` | Plan format definition |
| Create | `orca/plan/parser.py` | Plan file parser |
| Create | `orca/plan/generator.py` | LLM-based plan generator |
| Create | `orca/commands/plan.py` | CLI command |
| Create | `orca/validate/__init__.py` | Validate module init |
| Create | `orca/validate/templates.py` | Test template format |
| Create | `orca/validate/generator.py` | Test code generator |
| Create | `orca/validate/engine.py` | Validation engine |
| Create | `orca/validate/installer.py` | Test dependency installer |
| Create | `orca/hooks/__init__.py` | Hooks module init |
| Create | `orca/hooks/pre_commit.py` | Pre-commit hook |
| Create | `tests/unit/plan/` | Plan unit tests |
| Create | `tests/unit/validate/` | Validate unit tests |
| Create | `tests/unit/hooks/` | Hook unit tests |
| Create | `docs/plan.md` | Plan command docs |
| Create | `docs/validate.md` | Validation docs |
| Create | `docs/hooks.md` | Hook docs |
| Modify | `orca/__main__.py` | Add plan command, remove refine |
| Modify | `orca/commands/__init__.py` | Update imports |
| Modify | `orca/commands/decompose.py` | Add plan format support |
| Modify | `orca/commands/loop.py` | Add retry with summary |
| Modify | `orca/commands/init.py` | Install hooks |
| Modify | `README.md` | Update documentation |
| Delete | `orca/commands/refine.py` | Remove old command |

---

## Success Criteria

- [ ] `orca plan spec.md` generates valid markdown plan with task format `- [ ] TASK-NNN:`
- [ ] Plan hash stabilizes after 2 consecutive identical iterations
- [ ] `orca decompose plan.md` correctly extracts tasks and features
- [ ] Pre-commit hook installs and validates commits
- [ ] Test generation produces valid test code for detected framework
- [ ] Retry loop discards changes and provides attempt summary
- [ ] Loop can successfully fix failed implementations using summary context
- [ ] All new code has 80%+ test coverage
- [ ] Documentation complete for new commands

---

## Implementation Order

1. **Phase 1** (Core Infrastructure) — Foundation
2. **Phase 2** (Plan Command) — CLI integration
3. **Phase 3** (Decompose Integration) — Connect plan to tasks
4. **Phase 4** (Validation Hook) — Commit validation system
5. **Phase 5** (Dependencies) — Test setup
6. **Phase 6** (Documentation) — Final polish

---

## Notes

### Plan Format Rationale
- LLMs can generate consistently (no JSON schema complexity)
- Still structured enough for reliable parsing
- Human-readable and editable
- Aligns with Ralph playbook "LLM chooses format" philosophy

### Stability Detection
Plan is "complete" when `hash(task_list)` is identical for 2 consecutive iterations.

### Validation Flow
```
1. pi implements task
2. Unit tests pass
3. Pre-commit hook triggers
4. orca validate --task-id TASK-xxx
5. Test generator creates functional tests from spec
6. Tests run against implementation
7. Pass: commit allowed
8. Fail: commit blocked, task re-queued
```

### Retry Behavior
- Discard changes (git reset --hard)
- Inject attempt summary
- Loop re-implements from scratch with context

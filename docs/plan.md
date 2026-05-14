# Plan Command

Generate implementation plans from spec files using LLM.

## Usage

```bash
orca plan <spec.md> [options]
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--output`, `-o` | Output path for the plan | `IMPLEMENTATION_PLAN.md` |
| `--max-iterations` | Maximum refinement iterations | `10` |
| `--pi-skill` | Pi skill to use for LLM | `plan` |
| `--force` | Overwrite existing plan | `false` |

## Examples

```bash
# Generate plan from spec
orca plan docs/spec.md

# Custom output path
orca plan docs/spec.md -o my-plan.md

# More iterations for complex specs
orca plan docs/spec.md --max-iterations 20

# Use specific pi skill
orca plan docs/spec.md --pi-skill custom-plan
```

## Plan Format

Plans are generated in LLM-friendly markdown format:

```markdown
# Implementation Plan

**Project:** MyProject
**Spec:** docs/spec.md

## Features

### FEAT-001: Authentication
- [ ] TASK-001: Create user model
- [ ] TASK-002: Implement login endpoint

### FEAT-002: Data Storage
- [ ] TASK-003: Set up database
- [ ] TASK-004: Create CRUD operations

---

**Plan Hash:** abc123def4
```

## Generation Process

1. **Initial generation** - LLM creates plan from spec content
2. **Stability check** - Hash computed from task IDs
3. **Gap detection** - LLM identifies missing features/tasks
4. **Refinement** - Iterative improvement until stable
5. **Stability** - Plan complete when hash unchanged for 2 iterations

## Integration with Decompose

After generating a plan, decompose it into tasks:

```bash
# Generate plan
orca plan docs/spec.md

# Decompose into tasks
orca decompose IMPLEMENTATION_PLAN.md

# List generated tasks
orca list --status available
```
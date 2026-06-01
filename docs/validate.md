# Validation System

Commit-time functional validation ensures implementations meet spec requirements.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Validation Engine                       │
├─────────────────────────────────────────────────────────────┤
│  templates.py    │  Test template format & parsing         │
│  generator.py    │  Framework detection & test generation  │
│  engine.py       │  Core validation logic                  │
│  installer.py    │  Test dependency auto-installation      │
└─────────────────────────────────────────────────────────────┘
```

## Components

### Test Templates

Test templates define functional requirements for each task:

```python
from orca.validate import TestTemplate, format_task_test

template = TestTemplate(
    task_id="TASK-001",
    description="Login endpoint",
    functional_requirements=[
        "Accept POST /api/auth/login",
        "Return JWT on valid credentials",
        "Return 401 on invalid credentials",
    ],
    test_cases=[...],
    edge_cases=["empty password", "invalid email format"],
)
```

### Test Generator

Automatically detects test framework and generates tests:

```python
from orca.validate import TestGenerator

gen = TestGenerator()
framework = gen.detect_framework(Path.cwd())

# Generate tests for a task
test_files = gen.generate_tests(task, template, output_dir)
```

**Supported Frameworks:**

| Framework | Detection Files |
|-----------|-----------------|
| pytest | `pyproject.toml`, `pytest.ini` |
| Jest | `package.json`, `jest.config.js` |
| Go test | `go.mod` |
| RSpec | `Gemfile` |

### Validation Engine

Runs validation and returns results:

```python
from orca.validate import ValidationEngine

engine = ValidationEngine()
result = engine.validate(
    task_id="TASK-001",
    spec_path=Path("spec.md"),
    impl_path=Path("."),
)

if result.passed:
    print("Implementation meets requirements")
else:
    print(f"Failures: {result.errors}")
```

### Dependency Installer

Auto-installs test dependencies:

```python
from orca.validate import DependencyInstaller

installer = DependencyInstaller()
installed = installer.ensure_deps(Path.cwd())
```

## Pre-commit Hook

The validation system integrates with git pre-commit:

```bash
# Install hook (done automatically by orca init)
orca hooks install

# Hook runs: orca validate --staged
```

## Attempt Summary

When validation fails, an attempt summary is generated for retry:

```markdown
# Attempt Summary for TASK-001

## What Was Tried
- Implemented login endpoint at /api/auth/login
- Added JWT token generation

## How It Failed
- Functional validation tests failed
- Missing password length validation

## Spec Reference
[Original task requirements]
```
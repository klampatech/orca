# Git Hooks

Orca installs a pre-commit hook for commit-time validation.

## Installation

Hooks are installed automatically when running `orca init`:

```bash
cd my-project
orca init
# Output includes: "✓ Pre-commit hook installed"
```

## Manual Installation

```python
from orca.hooks import install_hooks

installed = install_hooks(Path.cwd())
```

## How It Works

The pre-commit hook runs before each commit:

```bash
#!/bin/bash
# .git/hooks/pre-commit
orca validate --staged --commit-msg "$1"
```

## Validation Flow

```
1. Developer runs: git commit -m "Implement login"
2. Pre-commit hook triggers
3. orca validate --staged runs
4. Tests generated from spec requirements
5. Tests execute against staged changes
6. Pass: commit proceeds
7. Fail: commit blocked, task re-queued
```

## Skipping Hooks

To commit without validation:

```bash
git commit --no-verify -m "WIP"
```

## Hook Management

```bash
# Check if hook is installed
ls -la .git/hooks/pre-commit

# Update hook (after orca update)
orca init --force

# Remove hook
rm .git/hooks/pre-commit
```
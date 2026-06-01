"""Git hooks for Orca validation."""

from .pre_commit import install_hooks, run_pre_commit_validation

__all__ = ["install_hooks", "run_pre_commit_validation"]

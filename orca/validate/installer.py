"""Test dependency installer."""

import subprocess
import sys
from pathlib import Path
from typing import Optional


class DependencyInstaller:
    """Installer for test framework dependencies."""

    def __init__(self, dry_run: bool = False):
        """Initialize the dependency installer.

        Args:
            dry_run: If True, only report what would be installed
        """
        self.dry_run = dry_run

    def detect_project_type(self, project_path: Path) -> str:
        """Detect the type of project from its structure.

        Args:
            project_path: Root path of the project

        Returns:
            Project type: python, node, go, ruby, or unknown
        """
        if not project_path.exists():
            return "unknown"

        # Python project indicators
        if any(project_path.glob("*.py")) or (
            project_path / "pyproject.toml"
        ).exists() or (project_path / "setup.py").exists():
            return "python"

        # Node.js project indicators
        if (project_path / "package.json").exists():
            return "node"

        # Go project indicators
        if (project_path / "go.mod").exists():
            return "go"

        # Ruby project indicators
        if (project_path / "Gemfile").exists():
            return "ruby"

        return "unknown"

    def _run_command(
        self, cmd: list[str], cwd: Path, description: str
    ) -> tuple[bool, str]:
        """Run an installation command.

        Args:
            cmd: Command and arguments as list
            cwd: Working directory
            description: Description of what is being installed

        Returns:
            Tuple of (success, output/error message)
        """
        if self.dry_run:
            return True, f"[DRY RUN] Would run: {' '.join(cmd)}"

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr or result.stdout
        except subprocess.TimeoutExpired:
            return False, f"{description} timed out after 5 minutes"
        except FileNotFoundError:
            return False, f"Command not found: {cmd[0]}"
        except Exception as e:
            return False, f"{description} failed: {str(e)}"

    def _install_python_deps(self, project_path: Path) -> tuple[bool, str]:
        """Install Python test dependencies."""
        deps_to_install = []

        # Check if pytest is available
        try:
            subprocess.run(
                ["pytest", "--version"],
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            deps_to_install.append("pytest")

        if not deps_to_install:
            return True, "pytest already installed"

        # Try pip first, then uv
        success, output = self._run_command(
            [sys.executable, "-m", "pip", "install"] + deps_to_install,
            project_path,
            "Installing Python test dependencies",
        )

        if not success:
            # Try uv as fallback
            success, output = self._run_command(
                ["uv", "pip", "install"] + deps_to_install,
                project_path,
                "Installing Python test dependencies via uv",
            )

        return success, output

    def _install_node_deps(self, project_path: Path) -> tuple[bool, str]:
        """Install Node.js test dependencies."""
        package_json = project_path / "package.json"
        if not package_json.exists():
            return False, "package.json not found"

        # Check if test script exists and dependencies are installed
        import json

        try:
            with open(package_json) as f:
                pkg = json.load(f)

            dev_deps = pkg.get("devDependencies", {})
            deps = pkg.get("dependencies", {})

            test_deps = ["jest", "vitest", "mocha", "tap", "ava"]
            missing = [
                dep for dep in test_deps if dep not in dev_deps and dep not in deps
            ]

            if not missing:
                return True, "Test framework already in dependencies"

            # Try npm install first
            success, output = self._run_command(
                ["npm", "install"],
                project_path,
                "Installing Node.js dependencies",
            )

            return success, output

        except (json.JSONDecodeError, IOError) as e:
            return False, f"Failed to read package.json: {e}"

    def _install_go_deps(self, project_path: Path) -> tuple[bool, str]:
        """Install Go test dependencies."""
        return self._run_command(
            ["go", "mod", "tidy"],
            project_path,
            "Installing Go dependencies",
        )

    def _install_ruby_deps(self, project_path: Path) -> tuple[bool, str]:
        """Install Ruby test dependencies."""
        # Check for bundler
        try:
            subprocess.run(
                ["bundle", "--version"],
                capture_output=True,
                timeout=10,
            )
            return self._run_command(
                ["bundle", "install"],
                project_path,
                "Installing Ruby dependencies",
            )
        except FileNotFoundError:
            return False, "bundler not found - install with: gem install bundler"

    def ensure_deps(self, project_path: Path) -> bool:
        """Ensure test dependencies are installed for the project.

        Args:
            project_path: Root path of the project

        Returns:
            True if dependencies are available, False otherwise
        """
        if project_path is None:
            project_path = Path.cwd()

        project_type = self.detect_project_type(project_path)

        if project_type == "unknown":
            # No specific project type detected - dependencies may already exist
            return True

        success, output = False, ""

        if project_type == "python":
            success, output = self._install_python_deps(project_path)
        elif project_type == "node":
            success, output = self._install_node_deps(project_path)
        elif project_type == "go":
            success, output = self._install_go_deps(project_path)
        elif project_type == "ruby":
            success, output = self._install_ruby_deps(project_path)

        if success:
            print(f"[DependencyInstaller] {project_type} test deps ready: {output}")
        else:
            print(f"[DependencyInstaller] Warning: {output}")

        return success

    def check_deps(self, project_path: Path) -> dict[str, bool]:
        """Check which test dependencies are available.

        Args:
            project_path: Root path of the project

        Returns:
            Dictionary mapping dependency names to availability
        """
        project_type = self.detect_project_type(project_path)
        deps = {}

        if project_type == "python":
            deps["pytest"] = self._is_command_available("pytest")
            deps["pip"] = self._is_command_available("pip")
        elif project_type == "node":
            deps["npm"] = self._is_command_available("npm")
            deps["jest"] = self._is_command_available("jest")
        elif project_type == "go":
            deps["go"] = self._is_command_available("go")
        elif project_type == "ruby":
            deps["bundle"] = self._is_command_available("bundle")
            deps["rspec"] = self._is_command_available("rspec")

        deps["project_type"] = project_type != "unknown"
        return deps

    def _is_command_available(self, cmd: str) -> bool:
        """Check if a command is available in PATH."""
        try:
            subprocess.run(
                ["which", cmd] if sys.platform != "win32" else ["where", cmd],
                capture_output=True,
                timeout=10,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


def ensure_test_deps(project_path: Path, dry_run: bool = False) -> bool:
    """Convenience function to ensure test dependencies are installed.

    Args:
        project_path: Root path of the project
        dry_run: If True, only report what would be installed

    Returns:
        True if dependencies are available, False otherwise
    """
    installer = DependencyInstaller(dry_run=dry_run)
    return installer.ensure_deps(project_path)
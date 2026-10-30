"""Create and inspect a disposable application and file-only Git remote."""

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ORIGINAL_SOURCE = "import os\nimport sys\n\nvalue = 1\n"
TARGET_PATH = "src/service.py"


def git(directory: Path, *arguments: str) -> str:
    """Run bounded local Git commands and expose useful failure evidence."""
    return subprocess.run(
        ["git", "-C", str(directory), *arguments],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout.strip()


@dataclass(frozen=True)
class ScenarioRepository:
    """Identify an application checkout, its original commit, and bare remote."""

    root: Path
    remote: Path
    original_sha: str

    @property
    def source(self) -> Path:
        """Return the sole permitted edit path."""
        return self.root / TARGET_PATH

    @property
    def validation_command(self) -> str:
        """Use installed pytest without dependency resolution or plugin discovery."""
        return (
            f"{shlex.quote(sys.executable)} -m pytest -q --color=no --tb=short "
            "-c pyproject.toml -p no:cacheprovider"
        )


def create_repository(directory: Path) -> ScenarioRepository:
    """Seed passing tests, two unused imports, and a clean local remote."""
    root = directory / "application"
    remote = directory / "origin.git"
    files = {
        TARGET_PATH: ORIGINAL_SOURCE,
        "tests/test_service.py": (
            "from service import value\n\ndef test_value():\n    assert value == 1\n"
        ),
        "pyproject.toml": (
            '[tool.pytest.ini_options]\npythonpath = ["src"]\ntestpaths = ["tests"]\n'
        ),
    }
    for relative_path, contents in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    git(directory, "init", "--bare", str(remote))
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Offline Scenario")
    git(root, "config", "user.email", "offline@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", ".")
    git(root, "commit", "-m", "Seed scenario application")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-u", "origin", "main")
    return ScenarioRepository(root, remote, git(root, "rev-parse", "HEAD"))

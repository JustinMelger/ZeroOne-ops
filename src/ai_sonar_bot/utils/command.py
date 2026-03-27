"""Command helpers."""

from pathlib import Path


def repo_root() -> Path:
    """Return the current repository root.

    Returns:
        Current working directory.
    """
    return Path.cwd()

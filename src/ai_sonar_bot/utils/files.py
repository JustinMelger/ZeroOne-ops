"""Filesystem helpers."""

from pathlib import Path


def ensure_parent(path: Path) -> None:
    """Create a file's parent directory if needed.

    Args:
        path: Target path whose parent should exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

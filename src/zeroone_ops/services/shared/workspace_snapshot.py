"""Workspace snapshot service.

This module captures and restores repository file contents for rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Represent a captured workspace snapshot for a set of files.

    Attributes:
        files: Mapping from absolute file path to original file content, or
            ``None`` when the file did not exist before capture.
    """

    files: dict[Path, str | None]


class WorkspaceSnapshotService:
    """Capture and restore repository file contents.

    Args:
        repo_root: Repository root path.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialize the workspace snapshot service.

        Args:
            repo_root: Repository root path.
        """
        self.repo_root = repo_root

    def capture(self, file_paths: list[str]) -> WorkspaceSnapshot:
        """Capture current file contents for repository-relative paths.

        Args:
            file_paths: Repository-relative file paths to capture.

        Returns:
            Snapshot of the current file contents.
        """
        files: dict[Path, str | None] = {}
        for file_path in file_paths:
            target = self.repo_root / file_path
            files[target] = target.read_text(encoding="utf-8") if target.exists() else None
        return WorkspaceSnapshot(files=files)

    def restore(self, snapshot: WorkspaceSnapshot) -> None:
        """Restore files from a previously captured snapshot.

        Args:
            snapshot: Snapshot to restore.
        """
        for target, content in snapshot.files.items():
            if content is None:
                if target.exists():
                    target.unlink()
                continue
            target.write_text(content, encoding="utf-8")

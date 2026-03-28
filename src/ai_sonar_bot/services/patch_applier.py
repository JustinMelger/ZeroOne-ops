"""Patch application service.

This module validates and applies unified diff patches to the local git
repository.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from ai_sonar_bot.models.analysis import PatchProposal


class PatchApplyError(RuntimeError):
    """Raised when a proposed patch cannot be applied safely."""


class PatchApplier:
    """Validate and apply unified diff patches.

    Args:
        repo_root: Repository root where patch application will run.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialize the patch applier.

        Args:
            repo_root: Repository root where patch application will run.
        """
        self.repo_root = repo_root

    def apply(self, proposal: PatchProposal) -> None:
        """Validate and apply a patch proposal.

        Args:
            proposal: Proposed patch to apply.

        Raises:
            PatchApplyError: If the patch is unsafe or cannot be applied.
        """
        self._validate_patch_paths(proposal.files_touched)
        self._ensure_git_repository()
        self._run_git_apply(proposal.unified_diff)

    def _validate_patch_paths(self, files_touched: list[str]) -> None:
        """Validate patch paths stay inside the repository.

        Args:
            files_touched: Paths declared by the patch proposal.

        Raises:
            PatchApplyError: If any path is unsafe.
        """
        if not files_touched:
            raise PatchApplyError("Patch proposal does not declare any touched files.")

        for file_path in files_touched:
            posix_path = PurePosixPath(file_path)
            if posix_path.is_absolute():
                raise PatchApplyError(f"Patch path must be relative: {file_path}")
            if ".." in posix_path.parts:
                raise PatchApplyError(f"Patch path escapes repository root: {file_path}")
            resolved_path = (self.repo_root / Path(posix_path)).resolve()
            repo_root_resolved = self.repo_root.resolve()
            if (
                repo_root_resolved not in resolved_path.parents
                and resolved_path != repo_root_resolved
            ):
                raise PatchApplyError(f"Patch path escapes repository root: {file_path}")

    def _ensure_git_repository(self) -> None:
        """Verify the target directory is a git repository.

        Raises:
            PatchApplyError: If the repository check fails.
        """
        completed = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or completed.stdout.strip() != "true":
            raise PatchApplyError("Patch application requires a git repository.")

    def _run_git_apply(self, unified_diff: str) -> None:
        """Apply a unified diff with git.

        Args:
            unified_diff: Unified diff content.

        Raises:
            PatchApplyError: If git apply fails.
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".diff",
            dir=self.repo_root,
            delete=False,
        ) as handle:
            handle.write(unified_diff)
            temp_path = Path(handle.name)

        try:
            completed = subprocess.run(
                ["git", "apply", "--reject", "--whitespace=nowarn", str(temp_path)],
                cwd=self.repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            temp_path.unlink(missing_ok=True)

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "git apply failed."
            raise PatchApplyError(message)

"""Git branch management.

This module will own the local git workflow once provider integration is added.
"""

from __future__ import annotations

from pathlib import Path


class BranchManager:
    """Manage git branch lifecycle operations.

    Args:
        repo_root: Repository root where git commands will run.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialize the branch manager.

        Args:
            repo_root: Repository root where git commands will run.
        """
        self.repo_root = repo_root

    def ensure_ready(self) -> None:
        """Validate that the repository is ready for automation."""
        raise NotImplementedError("Git workflow is not implemented yet.")

    def create_branch(self, branch_name: str) -> None:
        """Create a work branch.

        Args:
            branch_name: Branch name to create.
        """
        raise NotImplementedError("Git workflow is not implemented yet.")

    def commit_and_push(self, commit_message: str) -> str:
        """Commit and push the prepared change set.

        Args:
            commit_message: Commit message to use.

        Returns:
            The resulting commit SHA.
        """
        raise NotImplementedError("Git workflow is not implemented yet.")

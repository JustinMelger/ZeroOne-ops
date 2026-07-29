"""Git branch management.

This module owns the local git workflow used before publish.
"""

from __future__ import annotations

# Bandit: this service intentionally uses subprocess for trusted git CLI operations.
import subprocess  # nosec B404
from pathlib import Path

from zeroone_ops.utils.git import build_issue_branch_name


class BranchManagerError(RuntimeError):
    """Raised when a git workflow operation fails."""


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
        """Validate that the repository is ready for automation.

        Raises:
            BranchManagerError: If the repository is missing or dirty.
        """
        if self._run_git_command(["rev-parse", "--is-inside-work-tree"]).strip() != "true":
            raise BranchManagerError(f"Not a git repository: {self.repo_root}")
        status = self._run_git_command(["status", "--porcelain"])
        if status.strip():
            raise BranchManagerError("Repository has uncommitted or untracked changes.")

    def build_branch_name(self, *, branch_prefix: str, issue_key: str, file_path: str) -> str:
        """Build a predictable branch name for an issue.

        Args:
            branch_prefix: Configured branch prefix.
            issue_key: SonarQube issue key.
            file_path: Issue file path.

        Returns:
            Predictable branch name safe for git.
        """
        return build_issue_branch_name(
            branch_prefix=branch_prefix,
            issue_key=issue_key,
            file_path=file_path,
        )

    def create_branch(self, branch_name: str) -> None:
        """Create a work branch.

        Args:
            branch_name: Branch name to create.

        Raises:
            BranchManagerError: If branch creation fails.
        """
        self._run_git_command(["checkout", "-b", branch_name])

    def commit_and_push(
        self,
        commit_message: str,
        *,
        push: bool = True,
        remote_name: str = "origin",
        files_to_commit: list[str] | None = None,
    ) -> str:
        """Commit and push the prepared change set.

        Args:
            commit_message: Commit message to use.
            push: Whether to push the commit to a remote.
            remote_name: Remote name to push to.
            files_to_commit: Optional repository-relative patch paths to stage.

        Returns:
            The resulting commit SHA.

        Raises:
            BranchManagerError: If committing or pushing fails.
        """
        if files_to_commit is None:
            self._run_git_command(["add", "-A"])
        else:
            # Setup commands must not leak staged side effects into a patch commit.
            self._run_git_command(["reset"])
            if files_to_commit:
                self._run_git_command(["add", "--", *files_to_commit])
        diff = self._run_git_command(["diff", "--cached", "--name-only"])
        if not diff.strip():
            raise BranchManagerError("No staged changes available to commit.")
        self._run_git_command(["commit", "-m", commit_message])
        commit_sha = self._run_git_command(["rev-parse", "HEAD"]).strip()
        if push:
            self.push_current_branch(remote_name=remote_name)
        return commit_sha

    def push_current_branch(self, *, remote_name: str = "origin") -> str:
        """Push the current branch to the configured remote."""
        current_branch = self._run_git_command(["branch", "--show-current"]).strip()
        self._run_git_command(["push", "-u", remote_name, current_branch])
        return current_branch

    def reset_index(self) -> None:
        """Reset the git index to the current HEAD state.

        Raises:
            BranchManagerError: If index reset fails.
        """
        self._run_git_command(["reset", "--mixed", "HEAD"])

    def _run_git_command(self, args: list[str]) -> str:
        """Run a git command in the repository.

        Args:
            args: Git command arguments, excluding the ``git`` prefix.

        Returns:
            Command standard output.

        Raises:
            BranchManagerError: If the git command fails.
        """
        # Git operations intentionally invoke the trusted local git CLI with explicit argv.
        completed = subprocess.run(  # nosec B603 B607
            ["git", *args],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "Unknown git error."
            raise BranchManagerError(message)
        return completed.stdout

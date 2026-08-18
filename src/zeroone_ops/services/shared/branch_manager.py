"""Git branch management.

This module owns the local git workflow used before publish.
"""

from __future__ import annotations

# Bandit: this service intentionally uses subprocess for trusted git CLI operations.
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.utils.git import build_issue_branch_name


class BranchManagerError(RuntimeError):
    """Raised when a git workflow operation fails."""


_MAX_REPORTED_WORKSPACE_CHANGES = 10


@dataclass(frozen=True)
class _WorkspaceChange:
    """Represent one parsed Git porcelain workspace change."""

    category: str
    path: str
    previous_path: str | None = None


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
        status = self._run_git_command(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
        if status:
            changes = _parse_porcelain_status(status)
            raise BranchManagerError(_format_dirty_workspace_message(changes))

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
        current_branch = self.current_branch()
        self._run_git_command(["push", "-u", remote_name, current_branch])
        return current_branch

    def current_branch(self) -> str:
        """Return the checked-out branch name before a remote side effect."""
        return self._run_git_command(["branch", "--show-current"]).strip()

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
            encoding="utf-8",
            # NUL-delimited porcelain emits literal filename bytes. Preserve
            # unusual filesystem names as safe text for operator diagnostics.
            errors="backslashreplace",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "Unknown git error."
            raise BranchManagerError(message)
        return completed.stdout


def _parse_porcelain_status(status: str) -> list[_WorkspaceChange]:
    """Parse NUL-delimited Git porcelain v1 output into workspace changes."""
    entries = status.split("\0")
    changes: list[_WorkspaceChange] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            changes.append(_WorkspaceChange(category="changed", path=entry))
            continue

        state = entry[:2]
        path = entry[3:]
        previous_path = None
        if "R" in state or "C" in state:
            if index < len(entries):
                previous_path = entries[index] or None
                index += 1
        changes.append(
            _WorkspaceChange(
                category=_workspace_change_category(state),
                path=path,
                previous_path=previous_path,
            )
        )
    return changes


def _workspace_change_category(state: str) -> str:
    """Return one operator-facing category from Git's two-column status."""
    if state == "??":
        return "untracked"
    if "U" in state:
        return "unmerged"
    if "R" in state:
        return "renamed"
    if "C" in state:
        return "copied"
    if state[0] != " " and state[1] != " ":
        return "staged and modified"
    if state[0] == "A":
        return "staged addition"
    if state[0] == "M":
        return "staged modification"
    if state[0] == "D":
        return "staged deletion"
    if state[1] == "M":
        return "modified"
    if state[1] == "D":
        return "deleted"
    return "changed"


def _format_dirty_workspace_message(changes: list[_WorkspaceChange]) -> str:
    """Render bounded, Markdown-safe remediation workspace diagnostics."""
    lines = ["Repository has uncommitted or untracked changes:"]
    visible_changes = changes[:_MAX_REPORTED_WORKSPACE_CHANGES]
    for change in visible_changes:
        path = _escape_workspace_path(change.path)
        if change.previous_path is not None:
            previous_path = _escape_workspace_path(change.previous_path)
            path = f"{path} (from {previous_path})"
        lines.append(f"- {change.category}: {path}")
    omitted_count = len(changes) - len(visible_changes)
    if omitted_count:
        lines.append(f"... and {omitted_count} more paths.")
    lines.append("Ignore generated runtime files or clean the workspace before retrying.")
    return "\n".join(lines)


def _escape_workspace_path(path: str) -> str:
    """Escape path control characters and Markdown delimiters for issue rendering."""
    escaped: list[str] = []
    for character in path:
        if character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif character in "\\`*_[]<>()#":
            escaped.append(f"\\{character}")
        else:
            escaped.append(character)
    return "".join(escaped)

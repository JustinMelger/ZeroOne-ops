"""Runtime-owned workspace output policy for remediation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from zeroone_ops.models.config import AppConfig

LOGGER = logging.getLogger(__name__)
MAX_REPORTED_RUNTIME_OUTPUTS = 10


@dataclass(frozen=True)
class WorkspaceChange:
    """Represent one parsed Git porcelain workspace change."""

    category: str
    path: str
    previous_path: str | None = None


class RuntimeWorkspacePolicy:
    """Allow only configured generated outputs to remain untracked."""

    def __init__(self, owned_untracked_paths: frozenset[str] = frozenset()) -> None:
        """Initialize the exact repository-relative output paths."""
        self.owned_untracked_paths = owned_untracked_paths

    @classmethod
    def from_config(cls, *, config: AppConfig, repo_root: Path) -> RuntimeWorkspacePolicy:
        """Build the remediation-only ownership policy from repository config."""
        configured_paths = [
            config.state.path,
            config.openai_solution_output_path,
            *(artifact.path for artifact in config.sarif.artifacts),
        ]
        repository_root = repo_root.resolve()
        owned_paths = {
            relative_path
            for configured_path in configured_paths
            if (
                relative_path := _owned_relative_path(
                    configured_path=configured_path,
                    repository_root=repository_root,
                )
            )
            is not None
        }
        return cls(frozenset(owned_paths))

    def split_changes(
        self, changes: list[WorkspaceChange]
    ) -> tuple[list[WorkspaceChange], list[WorkspaceChange]]:
        """Return blocking changes and exact runtime-owned untracked outputs."""
        blocking_changes: list[WorkspaceChange] = []
        ignored_runtime_outputs: list[WorkspaceChange] = []
        for change in changes:
            if (
                change.category == "untracked"
                and _normalize_status_path(change.path) in self.owned_untracked_paths
            ):
                ignored_runtime_outputs.append(change)
            else:
                blocking_changes.append(change)
        return blocking_changes, ignored_runtime_outputs


def parse_porcelain_status(status: str) -> list[WorkspaceChange]:
    """Parse NUL-delimited Git porcelain v1 output into workspace changes."""
    entries = status.split("\0")
    changes: list[WorkspaceChange] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            changes.append(WorkspaceChange(category="changed", path=entry))
            continue

        state = entry[:2]
        path = entry[3:]
        previous_path = None
        if "R" in state or "C" in state:
            if index < len(entries):
                previous_path = entries[index] or None
                index += 1
        changes.append(
            WorkspaceChange(
                category=_workspace_change_category(state),
                path=path,
                previous_path=previous_path,
            )
        )
    return changes


def log_ignored_runtime_outputs(changes: list[WorkspaceChange]) -> None:
    """Log bounded configured outputs that are safely ignored as untracked."""
    if not changes:
        return
    visible_paths = [change.path for change in changes[:MAX_REPORTED_RUNTIME_OUTPUTS]]
    omitted_count = len(changes) - len(visible_paths)
    suffix = f"; and {omitted_count} more" if omitted_count else ""
    LOGGER.info(
        "ignored configured runtime workspace output(s): %s%s",
        ", ".join(visible_paths),
        suffix,
    )


def _owned_relative_path(*, configured_path: Path, repository_root: Path) -> str | None:
    """Return a safe exact output path or reject a non-local configuration path."""
    if configured_path.is_absolute() or ".." in PurePosixPath(configured_path.as_posix()).parts:
        return None
    resolved_path = (repository_root / configured_path).resolve()
    if resolved_path == repository_root or repository_root not in resolved_path.parents:
        return None
    return resolved_path.relative_to(repository_root).as_posix()


def _normalize_status_path(path: str) -> str:
    """Normalize a Git-reported path for exact configured-path comparison."""
    return PurePosixPath(path).as_posix()


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

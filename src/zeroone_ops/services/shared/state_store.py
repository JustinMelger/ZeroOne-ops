"""JSON-backed state store.

This module persists local execution state for issue tracking and run history.
"""

from __future__ import annotations

import json
from pathlib import Path

from zeroone_ops.models.state import AppState, IssueState, RepositoryState, RunRecord, utc_now


class StateStore:
    """Load and save repository-local execution state.

    Args:
        path: Path to the JSON state file.
        base_branch: Repository base branch name.
        gitlab_project_id: GitLab project identifier, if known.
        sonarqube_project_key: SonarQube project key, if known.
    """

    def __init__(
        self,
        path: Path,
        *,
        base_branch: str,
        gitlab_project_id: str | None,
        sonarqube_project_key: str | None,
    ) -> None:
        """Initialize the state store.

        Args:
            path: Path to the JSON state file.
            base_branch: Repository base branch name.
            gitlab_project_id: GitLab project identifier, if known.
            sonarqube_project_key: SonarQube project key, if known.
        """
        self.path = path
        self.default_repository = RepositoryState(
            base_branch=base_branch,
            gitlab_project_id=gitlab_project_id,
            sonarqube_project_key=sonarqube_project_key,
        )

    def load(self) -> AppState:
        """Load application state from disk.

        Returns:
            The persisted application state, or a default state if the file does
            not yet exist.
        """
        if not self.path.exists():
            return AppState(repository=self.default_repository)
        return AppState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: AppState) -> None:
        """Persist application state to disk.

        Args:
            state: State object to persist.
        """
        state.updated_at = utc_now()
        payload = state.model_dump(mode="json", exclude_none=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.path)

    def append_run(self, state: AppState, run: RunRecord) -> AppState:
        """Append a run record to state.

        Args:
            state: Current application state.
            run: Run record to append.

        Returns:
            The mutated state object.
        """
        state.runs.append(run)
        return state

    def set_issue_state(self, state: AppState, issue_key: str, issue_state: IssueState) -> AppState:
        """Update the latest state for an issue.

        Args:
            state: Current application state.
            issue_key: SonarQube issue key.
            issue_state: Latest issue lifecycle state.

        Returns:
            The mutated state object.
        """
        state.issues[issue_key] = issue_state
        return state

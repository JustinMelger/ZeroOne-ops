"""Helpers for building CLI-facing run summaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.state import RunStatus


@dataclass(frozen=True)
class RunSummary:
    """Summarize a bot execution result."""

    run_id: str
    status: RunStatus
    message: str
    state_path: Path
    issue_key: str | None = None
    dashboard_item_id: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    change_request_url: str | None = None


class RunSummaryBuilder:
    """Build consistent run summaries for workflow runners."""

    def __init__(self, *, execution_mode: str, state_path: Path) -> None:
        """Initialize the summary builder."""
        self.execution_mode = execution_mode
        self.state_path = state_path

    def build(
        self,
        *,
        run_id: str,
        status: RunStatus,
        message: str,
        issue_key: str | None = None,
        dashboard_item_id: str | None = None,
        branch_name: str | None = None,
        commit_sha: str | None = None,
        change_request_url: str | None = None,
        change_request_action: str | None = None,
    ) -> RunSummary:
        """Build one CLI-facing run summary."""
        summary = f"[{self.execution_mode}] {message}"
        if change_request_url is not None:
            if change_request_action is None:
                summary = f"{summary} Change request: {change_request_url}"
            else:
                summary = f"{summary} Change request {change_request_action}: {change_request_url}"
        return RunSummary(
            run_id=run_id,
            status=status,
            message=summary,
            state_path=self.state_path,
            issue_key=issue_key,
            dashboard_item_id=dashboard_item_id,
            branch_name=branch_name,
            commit_sha=commit_sha,
            change_request_url=change_request_url,
        )

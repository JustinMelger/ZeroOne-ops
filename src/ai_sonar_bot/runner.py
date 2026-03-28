"""Application runner.

This module coordinates the top-level execution flow for the bot.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.state import IssueState, RunRecord, RunStatus, utc_now
from ai_sonar_bot.services.analysis_service import AnalysisService
from ai_sonar_bot.services.issue_intake import IssueIntakeService
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import load_config

LOGGER = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """Summarize a bot execution result.

    Attributes:
        run_id: Unique identifier for the execution.
        status: Terminal run status.
        message: Human-readable result summary.
        state_path: Path to the persisted state file.
    """

    run_id: str
    status: RunStatus
    message: str
    state_path: Path


def _build_run_id() -> str:
    """Build a unique run identifier.

    Returns:
        A timestamp-based run identifier with a random suffix.
    """
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _project_id_from_env() -> str | None:
    """Read the GitLab project ID override from the environment.

    Returns:
        The configured GitLab project ID, if present.
    """
    return os.environ.get("GITLAB_PROJECT_ID")


def _sonarqube_key_from_env() -> str | None:
    """Read the SonarQube project key override from the environment.

    Returns:
        The configured SonarQube project key, if present.
    """
    return os.environ.get("SONARQUBE_PROJECT_KEY")


def run(*, dry_run: bool = False) -> RunSummary:
    """Run the bot.

    Args:
        dry_run: Whether to execute in dry-run mode.

    Returns:
        A summary of the run result.
    """
    config = load_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()

    run_id = _build_run_id()
    started_at = utc_now()
    record = RunRecord(
        run_id=run_id,
        status=RunStatus.STARTED,
        started_at=started_at,
        updated_at=started_at,
    )
    state_store.append_run(state, record)
    repo_root = Path.cwd()
    intake_result = IssueIntakeService(
        repo_root=repo_root,
        config=config,
    ).select_issue(
        state=state,
        dry_run=dry_run or config.dry_run,
        run_id=run_id,
    )

    if intake_result.selected_issue is not None:
        issue_state = state.issues.get(intake_result.selected_issue.key)
        attempt_count = issue_state.attempt_count if issue_state is not None else 0
        record.status = RunStatus.SELECTED
        record.issue_key = intake_result.selected_issue.key
        record.updated_at = utc_now()
        state.active_issue_key = intake_result.selected_issue.key
        state_store.set_issue_state(
            state,
            issue_key=intake_result.selected_issue.key,
            issue_state=IssueState(
                status=RunStatus.SELECTED.value,
                last_run_id=run_id,
                attempt_count=attempt_count,
            ),
        )
        analysis_result = AnalysisService(repo_root=repo_root, config=config).analyze_issue(
            selected_issue=intake_result.selected_issue,
            dry_run=dry_run or config.dry_run,
        )
        state_store.save(state)
        return RunSummary(
            run_id=run_id,
            status=record.status,
            message=(
                f"[{config.execution_mode}] Selected SonarQube issue "
                f"{intake_result.selected_issue.key} in {intake_result.selected_issue.file_path} "
                f"({intake_result.selected_issue.rule}, {intake_result.selected_issue.severity}). "
                f"{analysis_result.summary}"
            ),
            state_path=config.state.path,
        )

    record.status = RunStatus.NO_ISSUE
    record.updated_at = utc_now()
    state.active_issue_key = None
    state_store.save(state)
    LOGGER.info(
        "run complete",
        extra={"run_id": run_id, "issue_count": intake_result.issue_count},
    )
    return RunSummary(
        run_id=run_id,
        status=record.status,
        message=f"[{config.execution_mode}] {intake_result.message}",
        state_path=config.state.path,
    )

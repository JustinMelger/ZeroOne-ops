"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from ai_sonar_bot.services.execution_service import ExecutionService
from ai_sonar_bot.services.issue_intake import IssueIntakeService
from ai_sonar_bot.services.run_state_service import RunStateService, RunSummary
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import load_config


def _build_run_id() -> str:
    """Build a unique run identifier."""
    from ai_sonar_bot.models.state import utc_now

    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _project_id_from_env() -> str | None:
    """Read the GitLab project ID override from the environment."""
    return os.environ.get("GITLAB_PROJECT_ID")


def _sonarqube_key_from_env() -> str | None:
    """Read the SonarQube project key override from the environment."""
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
    run_state_service = RunStateService(config=config, state_store=state_store, state=state)

    run_id = _build_run_id()
    record = run_state_service.start_run(run_id)
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run

    intake_result = IssueIntakeService(
        repo_root=repo_root,
        config=config,
    ).select_issue(
        state=state,
        dry_run=active_dry_run,
        run_id=run_id,
    )

    if intake_result.selected_issue is None:
        return run_state_service.finish_no_issue(
            record=record,
            message=intake_result.message,
            issue_count=intake_result.issue_count,
        )

    attempt_count = run_state_service.mark_selected(
        record=record,
        issue_key=intake_result.selected_issue.key,
    )

    execution_result = ExecutionService(repo_root=repo_root, config=config).execute(
        selected_issue=intake_result.selected_issue,
        dry_run=active_dry_run,
    )

    record.branch_name = execution_result.branch_name
    record.commit_sha = execution_result.commit_sha

    if execution_result.failure is not None:
        return run_state_service.fail_issue(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + (0 if active_dry_run else 1),
            error_message=execution_result.failure.message,
            failure=execution_result.failure,
        )
    if (
        execution_result.final_status is not None
        and execution_result.final_status.value == "rejected"
    ):
        return run_state_service.reject_issue(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + 1,
            branch_name=execution_result.branch_name,
            message=execution_result.status_message,
        )

    if execution_result.commit_sha is not None:
        run_state_service.mark_fix_generated(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + 1,
            branch_name=execution_result.branch_name,
            commit_sha=execution_result.commit_sha,
        )

    if execution_result.mr_url is not None:
        run_state_service.mark_mr_created(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + 1,
            branch_name=execution_result.branch_name,
            mr_url=execution_result.mr_url,
        )

    run_state_service.finish_success(record=record)
    message = (
        f"Selected SonarQube issue {intake_result.selected_issue.key} in "
        f"{intake_result.selected_issue.file_path} "
        f"({intake_result.selected_issue.rule}, {intake_result.selected_issue.severity}). "
        f"{execution_result.status_message}"
    )
    return run_state_service.build_summary(
        run_id=record.run_id,
        status=record.status,
        message=message,
        mr_url=execution_result.mr_url,
        mr_action=execution_result.mr_action,
    )

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
from ai_sonar_bot.providers.gitlab_client import GitLabClient, GitLabClientError
from ai_sonar_bot.services.analysis_service import AnalysisService
from ai_sonar_bot.services.branch_manager import BranchManager, BranchManagerError
from ai_sonar_bot.services.issue_intake import IssueIntakeService
from ai_sonar_bot.services.mr_service import MergeRequestService
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import load_config, load_gitlab_connection_config

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


@dataclass
class BranchPreparationResult:
    """Summarize branch creation for a non-dry-run execution."""

    branch_name: str | None = None
    error_message: str | None = None


@dataclass
class CommitResult:
    """Summarize local commit creation for a non-dry-run execution."""

    commit_sha: str | None = None
    error_message: str | None = None


@dataclass
class PublishResult:
    """Summarize remote publish and merge request creation."""

    branch_name: str | None = None
    mr_url: str | None = None
    mr_action: str | None = None
    error_message: str | None = None


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
        active_dry_run = dry_run or config.dry_run
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
        if not active_dry_run:
            branch_result = _prepare_branch(
                repo_root=repo_root,
                branch_prefix=config.branch_prefix,
                issue_key=intake_result.selected_issue.key,
                file_path=intake_result.selected_issue.file_path,
            )
            if branch_result.error_message is not None:
                record.status = RunStatus.FAILED
                record.error_message = branch_result.error_message
                record.updated_at = utc_now()
                state_store.set_issue_state(
                    state,
                    issue_key=intake_result.selected_issue.key,
                    issue_state=IssueState(
                        status=RunStatus.FAILED.value,
                        last_run_id=run_id,
                        attempt_count=attempt_count,
                        last_error=branch_result.error_message,
                    ),
                )
                state_store.save(state)
                return RunSummary(
                    run_id=run_id,
                    status=record.status,
                    message=f"[{config.execution_mode}] {branch_result.error_message}",
                    state_path=config.state.path,
                )
            record.branch_name = branch_result.branch_name
        analysis_result = AnalysisService(repo_root=repo_root, config=config).analyze_issue(
            selected_issue=intake_result.selected_issue,
            dry_run=active_dry_run,
        )
        if (
            not active_dry_run
            and analysis_result.patch is not None
            and analysis_result.patch_applied
            and analysis_result.validation_passed
        ):
            commit_result = _commit_local_changes(
                repo_root=repo_root,
                commit_message=analysis_result.patch.commit_message,
            )
            if commit_result.error_message is not None:
                record.status = RunStatus.FAILED
                record.error_message = commit_result.error_message
                record.updated_at = utc_now()
                state_store.set_issue_state(
                    state,
                    issue_key=intake_result.selected_issue.key,
                    issue_state=IssueState(
                        status=RunStatus.FAILED.value,
                        last_run_id=run_id,
                        attempt_count=attempt_count + 1,
                        branch_name=record.branch_name,
                        last_error=commit_result.error_message,
                    ),
                )
                state_store.save(state)
                return RunSummary(
                    run_id=run_id,
                    status=record.status,
                    message=f"[{config.execution_mode}] {commit_result.error_message}",
                    state_path=config.state.path,
                )
            record.status = RunStatus.FIX_GENERATED
            record.commit_sha = commit_result.commit_sha
            record.updated_at = utc_now()
            state_store.set_issue_state(
                state,
                issue_key=intake_result.selected_issue.key,
                issue_state=IssueState(
                    status=RunStatus.FIX_GENERATED.value,
                    last_run_id=run_id,
                    attempt_count=attempt_count + 1,
                    branch_name=record.branch_name,
                ),
            )
            if config.execution_mode == "ci":
                publish_result = _publish_branch_and_create_mr(
                    repo_root=repo_root,
                    branch_name=record.branch_name or "",
                    mr_title=analysis_result.patch.mr_title,
                    mr_description=analysis_result.patch.mr_description,
                    target_branch=config.gitlab.target_branch,
                    labels=config.gitlab.labels,
                )
                if publish_result.error_message is not None:
                    record.status = RunStatus.FAILED
                    record.error_message = publish_result.error_message
                    record.updated_at = utc_now()
                    state_store.set_issue_state(
                        state,
                        issue_key=intake_result.selected_issue.key,
                        issue_state=IssueState(
                            status=RunStatus.FAILED.value,
                            last_run_id=run_id,
                            attempt_count=attempt_count + 1,
                            branch_name=record.branch_name,
                            last_error=publish_result.error_message,
                        ),
                    )
                    state_store.save(state)
                    return RunSummary(
                        run_id=run_id,
                        status=record.status,
                        message=f"[{config.execution_mode}] {publish_result.error_message}",
                        state_path=config.state.path,
                    )
                record.status = RunStatus.MR_CREATED
                record.mr_url = publish_result.mr_url
                record.updated_at = utc_now()
                state_store.set_issue_state(
                    state,
                    issue_key=intake_result.selected_issue.key,
                    issue_state=IssueState(
                        status=RunStatus.MR_CREATED.value,
                        last_run_id=run_id,
                        attempt_count=attempt_count + 1,
                        branch_name=record.branch_name,
                        mr_url=publish_result.mr_url,
                    ),
                )
        state_store.save(state)
        message = (
            f"[{config.execution_mode}] Selected SonarQube issue "
            f"{intake_result.selected_issue.key} in {intake_result.selected_issue.file_path} "
            f"({intake_result.selected_issue.rule}, {intake_result.selected_issue.severity}). "
            f"{analysis_result.summary}"
        )
        if record.mr_url is not None:
            mr_action = publish_result.mr_action if config.execution_mode == "ci" else None
            if mr_action is None:
                message = f"{message} Merge request: {record.mr_url}"
            else:
                message = f"{message} Merge request {mr_action}: {record.mr_url}"
        return RunSummary(
            run_id=run_id,
            status=record.status,
            message=message,
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


def _prepare_branch(
    *,
    repo_root: Path,
    branch_prefix: str,
    issue_key: str,
    file_path: str,
) -> BranchPreparationResult:
    """Create a work branch for a selected issue."""
    manager = BranchManager(repo_root)
    try:
        manager.ensure_ready()
        branch_name = manager.build_branch_name(
            branch_prefix=branch_prefix,
            issue_key=issue_key,
            file_path=file_path,
        )
        manager.create_branch(branch_name)
    except BranchManagerError as error:
        return BranchPreparationResult(error_message=f"Branch preparation failed: {error}")
    return BranchPreparationResult(branch_name=branch_name)


def _commit_local_changes(*, repo_root: Path, commit_message: str) -> CommitResult:
    """Commit validated local changes without pushing."""
    try:
        commit_sha = BranchManager(repo_root).commit_and_push(commit_message, push=False)
    except BranchManagerError as error:
        return CommitResult(error_message=f"Commit failed: {error}")
    return CommitResult(commit_sha=commit_sha)


def _publish_branch_and_create_mr(
    *,
    repo_root: Path,
    branch_name: str,
    mr_title: str,
    mr_description: str,
    target_branch: str,
    labels: list[str],
) -> PublishResult:
    """Push the current branch and create or reuse a GitLab merge request."""
    try:
        gitlab_config = load_gitlab_connection_config()
        pushed_branch = BranchManager(repo_root).push_current_branch()
        merge_request_service = MergeRequestService(GitLabClient(gitlab_config))
        existing_mr = merge_request_service.find_open(
            project_id=gitlab_config.project_id,
            source_branch=pushed_branch,
            target_branch=target_branch,
        )
        if existing_mr is not None:
            return PublishResult(
                branch_name=pushed_branch,
                mr_url=existing_mr.web_url,
                mr_action="reused",
            )
        created_mr = merge_request_service.create(
            project_id=gitlab_config.project_id,
            source_branch=branch_name,
            target_branch=target_branch,
            title=mr_title,
            description=mr_description,
            labels=labels,
        )
    except (BranchManagerError, GitLabClientError, RuntimeError) as error:
        return PublishResult(error_message=f"Publish failed: {error}")
    return PublishResult(
        branch_name=branch_name,
        mr_url=created_mr.web_url,
        mr_action="created",
    )

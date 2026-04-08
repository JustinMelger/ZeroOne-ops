"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from ai_sonar_bot.models.state import (
    FailureDetails,
    FailureStage,
    RunRecord,
    RunStatus,
    utc_now,
)
from ai_sonar_bot.providers.gitlab_dashboard_client import GitLabDashboardClient
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.dashboard_item_intake import DashboardItemIntakeService
from ai_sonar_bot.services.dashboard_item_normalizer import DashboardItemNormalizer
from ai_sonar_bot.services.dashboard_reconciliation_intake import (
    DashboardReconciliationIntakeService,
)
from ai_sonar_bot.services.dashboard_reconciliation_service import (
    DashboardReconciliationService,
)
from ai_sonar_bot.services.dashboard_remediation_updater import DashboardRemediationUpdater
from ai_sonar_bot.services.dashboard_service import DashboardService
from ai_sonar_bot.services.execution_service import ExecutionService
from ai_sonar_bot.services.issue_intake import IssueIntakeService
from ai_sonar_bot.services.mr_intake import MergeRequestIntakeService
from ai_sonar_bot.services.remediation_context_builder import RemediationContextBuilder
from ai_sonar_bot.services.remediation_execution_adapter import (
    remediation_work_item_to_execution_target,
    sonar_issue_to_work_item,
)
from ai_sonar_bot.services.review_analysis_service import ReviewAnalysisService
from ai_sonar_bot.services.review_context_builder import ReviewContextBuilder
from ai_sonar_bot.services.review_dashboard_updater import ReviewDashboardUpdater
from ai_sonar_bot.services.review_publisher import ReviewPublisher
from ai_sonar_bot.services.review_state_service import ReviewStateService
from ai_sonar_bot.services.run_state_service import RunStateService, RunSummary
from ai_sonar_bot.services.sonar_dashboard_sync_service import SonarDashboardSyncService
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import load_config, load_gitlab_connection_config

LOGGER = logging.getLogger(__name__)


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


def _fail_dashboard_update(
    *,
    run_state_service: RunStateService,
    record: RunRecord,
    dashboard_item_id: str,
    workflow_message: str,
    dashboard_error_message: str,
) -> RunSummary:
    """Return a failed run summary when a dashboard lifecycle write fails."""
    message = f"{workflow_message} Dashboard lifecycle update failed: {dashboard_error_message}"
    return run_state_service.fail_dashboard_item(
        record=record,
        dashboard_item_id=dashboard_item_id,
        error_message=message,
        failure=FailureDetails(
            stage=FailureStage.DASHBOARD_UPDATE,
            message=message,
        ),
    )


def _with_dashboard_recovery_note(
    message: str,
    *,
    recovered_stale_item_ids: tuple[str, ...],
) -> str:
    """Append one stale-recovery note to a dashboard remediation summary."""
    if not recovered_stale_item_ids:
        return message
    if len(recovered_stale_item_ids) == 1:
        recovery_note = (
            "Recovered stale in_progress dashboard item before remediation: "
            f"{recovered_stale_item_ids[0]}."
        )
    else:
        recovery_note = (
            "Recovered stale in_progress dashboard items before remediation: "
            f"{', '.join(recovered_stale_item_ids)}."
        )
    return f"{message} {recovery_note}"


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
    work_item = sonar_issue_to_work_item(intake_result.selected_issue)

    execution_result = ExecutionService(repo_root=repo_root, config=config).execute(
        selected_issue=remediation_work_item_to_execution_target(work_item),
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
        f"Selected SonarQube issue {work_item.source_ref} in "
        f"{work_item.file_path} "
        f"({work_item.rule_id}, {work_item.severity}). "
        f"{execution_result.status_message}"
    )
    return run_state_service.build_summary(
        run_id=record.run_id,
        status=record.status,
        message=message,
        issue_key=intake_result.selected_issue.key,
        branch_name=record.branch_name,
        commit_sha=record.commit_sha,
        mr_url=execution_result.mr_url,
        mr_action=execution_result.mr_action,
    )


def review(*, dry_run: bool = False) -> RunSummary:
    """Run the merge-request review workflow."""
    config = load_config()
    gitlab_config = load_gitlab_connection_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()
    review_state_service = ReviewStateService(state_store=state_store, state=state)

    run_id = _build_run_id()
    record = review_state_service.start_run(run_id)
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run

    intake_result = MergeRequestIntakeService().select_merge_request(state=state)
    if intake_result.selected_merge_request is None:
        return review_state_service.finish_no_review(
            record=record,
            message=f"[{config.execution_mode}] {intake_result.message}",
        )
    LOGGER.info(
        "review run targeting merge request",
        extra={
            "run_id": run_id,
            "mr_iid": intake_result.selected_merge_request.iid,
            "head_sha": intake_result.selected_merge_request.head_sha,
            "source_branch": intake_result.selected_merge_request.source_branch,
            "target_branch": intake_result.selected_merge_request.target_branch,
            "dry_run": active_dry_run,
        },
    )

    review_client = GitLabReviewClient(gitlab_config)
    context_result = ReviewContextBuilder(
        repo_root=repo_root,
        config=config,
        review_client=review_client,
    ).build(
        intake_result.selected_merge_request,
        project_id=gitlab_config.project_id,
    )
    if context_result.context is None:
        return review_state_service.fail_review(
            record=record,
            error_message=f"[{config.execution_mode}] {context_result.message}",
            failure=FailureDetails(
                stage=FailureStage.REVIEW_CONTEXT,
                message=context_result.message,
            ),
        )
    changed_file_count = len(context_result.context.changed_files)
    total_context_lines = sum(
        changed_file.end_line - changed_file.start_line + 1
        for changed_file in context_result.context.changed_files
    )
    LOGGER.info(
        "review context built",
        extra={
            "run_id": run_id,
            "mr_iid": context_result.context.mr_iid,
            "head_sha": context_result.context.head_sha,
            "changed_file_count": changed_file_count,
            "context_line_count": total_context_lines,
        },
    )

    analysis_result = ReviewAnalysisService(config).analyze(context_result.context)
    if analysis_result.review_result is None:
        return review_state_service.fail_review(
            record=record,
            error_message=f"[{config.execution_mode}] {analysis_result.message}",
            failure=FailureDetails(
                stage=FailureStage.REVIEW_ANALYSIS,
                message=analysis_result.message,
            ),
        )
    LOGGER.info(
        "review analysis completed",
        extra={
            "run_id": run_id,
            "mr_iid": context_result.context.mr_iid,
            "head_sha": context_result.context.head_sha,
            "classification": analysis_result.review_result.classification,
            "finding_count": len(analysis_result.review_result.findings),
        },
    )

    note_url: str | None = None
    dashboard_warning: str | None = None
    if not active_dry_run:
        publish_result = ReviewPublisher(review_client).publish(
            project_id=gitlab_config.project_id,
            merge_request_iid=context_result.context.mr_iid,
            context=context_result.context,
            review_result=analysis_result.review_result,
        )
        if publish_result.error_message is not None:
            return review_state_service.fail_review(
                record=record,
                error_message=f"[{config.execution_mode}] {publish_result.error_message}",
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_PUBLISH,
                    message=publish_result.error_message,
                ),
            )
        if publish_result.note is not None:
            note_url = publish_result.note.web_url
            LOGGER.info(
                "review note published",
                extra={
                    "run_id": run_id,
                    "mr_iid": context_result.context.mr_iid,
                    "head_sha": context_result.context.head_sha,
                    "note_id": publish_result.note.id,
                    "note_url": publish_result.note.web_url,
                },
            )
        dashboard_update = ReviewDashboardUpdater(
            DashboardService(GitLabDashboardClient(gitlab_config))
        ).update(
            project_id=gitlab_config.project_id,
            merge_request=intake_result.selected_merge_request,
            review_result=analysis_result.review_result,
        )
        dashboard_warning = dashboard_update.error_message
        if dashboard_warning is None:
            LOGGER.info(
                "review dashboard mirrored",
                extra={
                    "run_id": run_id,
                    "mr_iid": context_result.context.mr_iid,
                    "head_sha": context_result.context.head_sha,
                    "dashboard_issue_url": dashboard_update.dashboard_issue_url,
                },
            )
        else:
            LOGGER.warning(
                "review dashboard mirror warning",
                extra={
                    "run_id": run_id,
                    "mr_iid": context_result.context.mr_iid,
                    "head_sha": context_result.context.head_sha,
                },
            )
    else:
        LOGGER.info(
            "review dry-run skipped publication",
            extra={
                "run_id": run_id,
                "mr_iid": context_result.context.mr_iid,
                "head_sha": context_result.context.head_sha,
            },
        )

    summary = review_state_service.mark_reviewed(
        record=record,
        merge_request=intake_result.selected_merge_request,
        review_result=analysis_result.review_result,
        note_url=note_url,
        dry_run=active_dry_run,
    )
    return RunSummary(
        run_id=summary.run_id,
        status=summary.status,
        message=(
            f"[{config.execution_mode}] {summary.message}"
            if dashboard_warning is None
            else f"[{config.execution_mode}] {summary.message} {dashboard_warning}"
        ),
        state_path=summary.state_path,
    )


def dashboard_remediate(*, dry_run: bool = False) -> RunSummary:
    """Run dashboard-backed remediation."""
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
    if not active_dry_run and config.execution_mode != "ci":
        message = (
            "Dashboard remediation live execution is only supported in CI mode. "
            "Use --dry-run locally."
        )
        return run_state_service.fail_run(
            record=record,
            error_message=message,
            failure=FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message=message,
            ),
        )
    gitlab_config = load_gitlab_connection_config()
    dashboard_service = DashboardService(GitLabDashboardClient(gitlab_config))
    intake_result = DashboardItemIntakeService(
        repo_root=repo_root,
        config=config,
        dashboard_service=dashboard_service,
    ).select_item(
        project_id=gitlab_config.project_id,
        state=state,
    )
    recovered_stale_item_ids = getattr(intake_result, "recovered_stale_item_ids", ())
    if intake_result.selected_item is None:
        return run_state_service.finish_no_issue(
            record=record,
            message=_with_dashboard_recovery_note(
                intake_result.message,
                recovered_stale_item_ids=recovered_stale_item_ids,
            ),
            issue_count=intake_result.item_count,
        )

    run_state_service.mark_dashboard_selected(
        record=record,
        dashboard_item_id=intake_result.selected_item.id,
    )

    normalizer = DashboardItemNormalizer()
    normalization_result = normalizer.normalize(intake_result.selected_item)
    if normalization_result.work_item is None:
        if not active_dry_run:
            DashboardRemediationUpdater(dashboard_service).mark_rejected(
                project_id=gitlab_config.project_id,
                dashboard_item_id=intake_result.selected_item.id,
                run_id=run_id,
                rejection_reason=normalization_result.message,
            )
        return run_state_service.reject_dashboard_item(
            record=record,
            dashboard_item_id=intake_result.selected_item.id,
            branch_name=None,
            message=_with_dashboard_recovery_note(
                normalization_result.message,
                recovered_stale_item_ids=recovered_stale_item_ids,
            ),
        )
    work_item = normalization_result.work_item
    context = RemediationContextBuilder(repo_root, config).build(work_item)
    if context is None:
        message = f"Context unavailable for dashboard item {work_item.dashboard_item_id}."
        if not active_dry_run:
            DashboardRemediationUpdater(dashboard_service).mark_failed(
                project_id=gitlab_config.project_id,
                dashboard_item_id=work_item.dashboard_item_id,
                run_id=run_id,
                error_message=message,
            )
        return run_state_service.fail_dashboard_item(
            record=record,
            dashboard_item_id=work_item.dashboard_item_id,
            error_message=_with_dashboard_recovery_note(
                message,
                recovered_stale_item_ids=recovered_stale_item_ids,
            ),
            failure=FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message=message,
            ),
        )

    live_dashboard_updates = not active_dry_run and config.execution_mode == "ci"
    if live_dashboard_updates:
        in_progress_result = DashboardRemediationUpdater(dashboard_service).mark_in_progress(
            project_id=gitlab_config.project_id,
            dashboard_item_id=work_item.dashboard_item_id,
            run_id=run_id,
        )
        if in_progress_result.error_message is not None:
            return _fail_dashboard_update(
                run_state_service=run_state_service,
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                workflow_message=(
                    f"Selected dashboard item {work_item.dashboard_item_id} for remediation."
                ),
                dashboard_error_message=in_progress_result.error_message,
            )

    selected_issue = remediation_work_item_to_execution_target(work_item)
    execution_result = ExecutionService(repo_root=repo_root, config=config).execute_with_context(
        selected_issue=selected_issue,
        context=context,
        dry_run=active_dry_run,
    )
    record.branch_name = execution_result.branch_name
    record.commit_sha = execution_result.commit_sha

    if execution_result.failure is not None:
        if live_dashboard_updates:
            failed_update = DashboardRemediationUpdater(dashboard_service).mark_failed(
                project_id=gitlab_config.project_id,
                dashboard_item_id=work_item.dashboard_item_id,
                run_id=run_id,
                error_message=execution_result.failure.message,
            )
            if failed_update.error_message is not None:
                return _fail_dashboard_update(
                    run_state_service=run_state_service,
                    record=record,
                    dashboard_item_id=work_item.dashboard_item_id,
                    workflow_message=_with_dashboard_recovery_note(
                        execution_result.failure.message,
                        recovered_stale_item_ids=recovered_stale_item_ids,
                    ),
                    dashboard_error_message=failed_update.error_message,
                )
        return run_state_service.fail_dashboard_item(
            record=record,
            dashboard_item_id=work_item.dashboard_item_id,
            error_message=_with_dashboard_recovery_note(
                execution_result.failure.message,
                recovered_stale_item_ids=recovered_stale_item_ids,
            ),
            failure=execution_result.failure,
        )
    if (
        execution_result.final_status is not None
        and execution_result.final_status.value == "rejected"
    ):
        if live_dashboard_updates:
            rejected_update = DashboardRemediationUpdater(dashboard_service).mark_rejected(
                project_id=gitlab_config.project_id,
                dashboard_item_id=work_item.dashboard_item_id,
                run_id=run_id,
                rejection_reason=execution_result.status_message,
            )
            if rejected_update.error_message is not None:
                return _fail_dashboard_update(
                    run_state_service=run_state_service,
                    record=record,
                    dashboard_item_id=work_item.dashboard_item_id,
                    workflow_message=_with_dashboard_recovery_note(
                        execution_result.status_message,
                        recovered_stale_item_ids=recovered_stale_item_ids,
                    ),
                    dashboard_error_message=rejected_update.error_message,
                )
        return run_state_service.reject_dashboard_item(
            record=record,
            dashboard_item_id=work_item.dashboard_item_id,
            branch_name=execution_result.branch_name,
            message=_with_dashboard_recovery_note(
                execution_result.status_message,
                recovered_stale_item_ids=recovered_stale_item_ids,
            ),
        )

    if (
        live_dashboard_updates
        and execution_result.mr_url is not None
        and execution_result.commit_sha
    ):
        record.mr_url = execution_result.mr_url
        mr_opened_update = DashboardRemediationUpdater(dashboard_service).mark_mr_opened(
            project_id=gitlab_config.project_id,
            dashboard_item_id=work_item.dashboard_item_id,
            run_id=run_id,
            branch_name=execution_result.branch_name or "",
            merge_request_url=execution_result.mr_url,
            commit_sha=execution_result.commit_sha,
        )
        if mr_opened_update.error_message is not None:
            return _fail_dashboard_update(
                run_state_service=run_state_service,
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                workflow_message=_with_dashboard_recovery_note(
                    "Remediation succeeded and created a merge request, but the dashboard "
                    "state could not be updated.",
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
                dashboard_error_message=mr_opened_update.error_message,
            )

    if execution_result.mr_url is not None:
        run_state_service.mark_dashboard_mr_created(
            record=record,
            dashboard_item_id=work_item.dashboard_item_id,
            branch_name=execution_result.branch_name,
            mr_url=execution_result.mr_url,
        )

    run_state_service.finish_success(record=record)
    return run_state_service.build_summary(
        run_id=record.run_id,
        status=record.status,
        message=_with_dashboard_recovery_note(
            (
                f"Selected dashboard item {work_item.dashboard_item_id} in "
                f"{work_item.file_path} ({work_item.rule_id}, {work_item.severity}). "
                f"{execution_result.status_message}"
            ),
            recovered_stale_item_ids=recovered_stale_item_ids,
        ),
        dashboard_item_id=work_item.dashboard_item_id,
        branch_name=record.branch_name,
        commit_sha=record.commit_sha,
        mr_url=execution_result.mr_url,
        mr_action=execution_result.mr_action,
    )


def sync_dashboard_sonar(*, dry_run: bool = False) -> RunSummary:
    """Sync eligible SonarQube issues into the dashboard."""
    config = load_config()
    gitlab_config = load_gitlab_connection_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()
    run_id = _build_run_id()
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run

    intake_service = IssueIntakeService(repo_root=repo_root, config=config)
    collection = intake_service.collect_eligible_issues(
        state=state,
        dry_run=active_dry_run,
        run_id=run_id,
        allow_remote_duplicate_lookup=not active_dry_run,
    )
    if not collection.eligible_issues:
        return RunSummary(
            run_id=run_id,
            status=collection_message_status(collection.message),
            message=f"[{config.execution_mode}] {collection.message}",
            state_path=state_store.path,
        )
    if active_dry_run:
        return RunSummary(
            run_id=run_id,
            status=collection_message_status("synced"),
            message=(
                f"[{config.execution_mode}] Dry-run found {len(collection.eligible_issues)} "
                "eligible SonarQube issues for dashboard sync."
            ),
            state_path=state_store.path,
        )

    sync_result = SonarDashboardSyncService(
        DashboardService(GitLabDashboardClient(gitlab_config))
    ).sync(
        project_id=gitlab_config.project_id,
        issues=collection.eligible_issues,
    )
    return RunSummary(
        run_id=run_id,
        status=collection_message_status("synced"),
        message=(
            f"[{config.execution_mode}] Synced {sync_result.synced_count} eligible "
            f"SonarQube issues to the dashboard. Dashboard: {sync_result.dashboard_issue_url}"
        ),
        state_path=state_store.path,
    )


def dashboard_reconcile(*, dry_run: bool = False) -> RunSummary:
    """Run dashboard reconciliation."""
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
    active_dry_run = dry_run or config.dry_run
    if not active_dry_run and config.execution_mode != "ci":
        message = (
            "Dashboard reconciliation live execution is only supported in CI mode. "
            "Use --dry-run locally."
        )
        return run_state_service.fail_run(
            record=record,
            error_message=message,
            failure=FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message=message,
            ),
        )

    gitlab_config = load_gitlab_connection_config()
    dashboard_service = DashboardService(GitLabDashboardClient(gitlab_config))
    review_client = GitLabReviewClient(gitlab_config)
    intake_result = DashboardReconciliationIntakeService(
        dashboard_service=dashboard_service,
    ).select_item(project_id=gitlab_config.project_id)
    if intake_result.selected_item is None:
        return run_state_service.finish_no_issue(
            record=record,
            message=intake_result.message,
            issue_count=intake_result.item_count,
        )

    selected_item = intake_result.selected_item
    decision = DashboardReconciliationService(review_client).decide(
        project_id=gitlab_config.project_id,
        item=selected_item,
    )
    record.dashboard_item_id = selected_item.id
    record.branch_name = selected_item.branch_name
    record.commit_sha = selected_item.commit_sha
    record.mr_url = selected_item.merge_request_url
    record.updated_at = utc_now()

    if active_dry_run:
        record.status = RunStatus.SELECTED
        state_store.save(state)
        return run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=(
                f"Dry-run would reconcile dashboard item {selected_item.id}: "
                f"{decision.message}"
            ),
            dashboard_item_id=selected_item.id,
            branch_name=selected_item.branch_name,
            commit_sha=selected_item.commit_sha,
            mr_url=selected_item.merge_request_url,
        )

    if decision.action == "noop":
        record.status = RunStatus.NO_ISSUE
        state_store.save(state)
        return run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=decision.message,
            dashboard_item_id=selected_item.id,
            branch_name=selected_item.branch_name,
            commit_sha=selected_item.commit_sha,
            mr_url=selected_item.merge_request_url,
        )

    updater = DashboardRemediationUpdater(dashboard_service)
    if decision.action == "done":
        update_result = updater.mark_done(
            project_id=gitlab_config.project_id,
            dashboard_item_id=selected_item.id,
            run_id=run_id,
            summary=decision.message,
        )
        if update_result.error_message is not None:
            return _fail_dashboard_update(
                run_state_service=run_state_service,
                record=record,
                dashboard_item_id=selected_item.id,
                workflow_message=decision.message,
                dashboard_error_message=update_result.error_message,
            )
        run_state_service.mark_dashboard_done(
            record=record,
            dashboard_item_id=selected_item.id,
            branch_name=selected_item.branch_name,
            commit_sha=selected_item.commit_sha,
            mr_url=selected_item.merge_request_url,
        )
        record.status = RunStatus.RECONCILED
        run_state_service.finish_success(record=record)
        return run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=decision.message,
            dashboard_item_id=selected_item.id,
            branch_name=selected_item.branch_name,
            commit_sha=selected_item.commit_sha,
            mr_url=selected_item.merge_request_url,
        )

    if decision.action == "open":
        update_result = updater.mark_open(
            project_id=gitlab_config.project_id,
            dashboard_item_id=selected_item.id,
            run_id=run_id,
            summary=decision.message,
        )
        if update_result.error_message is not None:
            return _fail_dashboard_update(
                run_state_service=run_state_service,
                record=record,
                dashboard_item_id=selected_item.id,
                workflow_message=decision.message,
                dashboard_error_message=update_result.error_message,
            )
        run_state_service.mark_dashboard_reopened(
            record=record,
            dashboard_item_id=selected_item.id,
            branch_name=selected_item.branch_name,
            commit_sha=selected_item.commit_sha,
            mr_url=selected_item.merge_request_url,
        )
        record.status = RunStatus.RECONCILED
        run_state_service.finish_success(record=record)
        return run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=decision.message,
            dashboard_item_id=selected_item.id,
            branch_name=selected_item.branch_name,
            commit_sha=selected_item.commit_sha,
            mr_url=selected_item.merge_request_url,
        )

    return run_state_service.fail_dashboard_item(
        record=record,
        dashboard_item_id=selected_item.id,
        error_message=decision.message,
        failure=FailureDetails(
            stage=FailureStage.RECONCILIATION,
            message=decision.message,
        ),
    )


def collection_message_status(message: str) -> RunStatus:
    """Map dashboard-sync outcomes to run statuses."""
    return RunStatus.NO_ISSUE if message != "synced" else RunStatus.SYNCED

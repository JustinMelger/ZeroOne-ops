"""Merge request review workflow runner."""

from __future__ import annotations

import logging
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.review import ReviewResult
from ai_sonar_bot.models.state import FailureDetails, FailureStage, RunRecord
from ai_sonar_bot.providers.gitlab_dashboard_client import GitLabDashboardClient
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.dashboard_service import DashboardService
from ai_sonar_bot.services.mr_intake import MergeRequestIntakeService
from ai_sonar_bot.services.review_analysis_service import ReviewAnalysisService
from ai_sonar_bot.services.review_context_builder import ReviewContextBuilder
from ai_sonar_bot.services.review_dashboard_updater import ReviewDashboardUpdater
from ai_sonar_bot.services.review_publisher import ReviewPublisher
from ai_sonar_bot.services.review_state_service import ReviewStateService
from ai_sonar_bot.services.run_state_service import RunSummary

LOGGER = logging.getLogger(__name__)


class ReviewRunner:
    """Run the merge-request review workflow with injected dependencies."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        review_client: GitLabReviewClient,
        dashboard_client: GitLabDashboardClient,
        review_state_service: ReviewStateService,
    ) -> None:
        """Initialize the review workflow runner."""
        self.repo_root = repo_root
        self.config = config
        self.review_client = review_client
        self.dashboard_client = dashboard_client
        self.review_state_service = review_state_service

    def run(
        self,
        *,
        project_id: str,
        run_id: str,
        record: RunRecord,
        active_dry_run: bool,
    ) -> RunSummary:
        """Run one merge-request review workflow."""
        intake_result = MergeRequestIntakeService().select_merge_request(
            state=self.review_state_service.state
        )
        if intake_result.selected_merge_request is None:
            return self.review_state_service.finish_no_review(
                record=record,
                message=f"[{self.config.execution_mode}] {intake_result.message}",
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

        context_result = ReviewContextBuilder(
            repo_root=self.repo_root,
            config=self.config,
            review_client=self.review_client,
        ).build(
            intake_result.selected_merge_request,
            project_id=project_id,
        )
        if context_result.context is None:
            return self.review_state_service.fail_review(
                record=record,
                error_message=f"[{self.config.execution_mode}] {context_result.message}",
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_CONTEXT,
                    message=context_result.message,
                ),
            )
        prior_review_context = self.review_state_service.load_prior_review_context(
            mr_iid=intake_result.selected_merge_request.iid,
            current_head_sha=intake_result.selected_merge_request.head_sha,
        )
        if prior_review_context is not None:
            context_result = context_result.__class__(
                context=context_result.context.model_copy(
                    update={"prior_review_context": prior_review_context}
                ),
                message=context_result.message,
            )
        context = context_result.context
        if context is None:  # pragma: no cover - defensive guard after enrichment
            return self.review_state_service.fail_review(
                record=record,
                error_message=(f"[{self.config.execution_mode}] Could not build review context."),
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_CONTEXT,
                    message="Could not build review context.",
                ),
            )

        changed_file_count = len(context.changed_files)
        total_context_lines = sum(
            changed_file.end_line - changed_file.start_line + 1
            for changed_file in context.changed_files
        )
        LOGGER.info(
            "review context built",
            extra={
                "run_id": run_id,
                "mr_iid": context.mr_iid,
                "head_sha": context.head_sha,
                "changed_file_count": changed_file_count,
                "context_line_count": total_context_lines,
            },
        )

        analysis_result = ReviewAnalysisService(self.config).analyze(context)
        if analysis_result.review_result is None:
            return self.review_state_service.fail_review(
                record=record,
                error_message=f"[{self.config.execution_mode}] {analysis_result.message}",
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_ANALYSIS,
                    message=analysis_result.message,
                ),
            )

        LOGGER.info(
            "review analysis completed",
            extra={
                "run_id": run_id,
                "mr_iid": context.mr_iid,
                "head_sha": context.head_sha,
                "classification": analysis_result.review_result.classification,
                "finding_count": len(analysis_result.review_result.findings),
            },
        )

        note_url: str | None = None
        dashboard_warning: str | None = None
        if not active_dry_run:
            if self._should_publish_note(analysis_result.review_result):
                publish_result = ReviewPublisher(self.review_client).publish(
                    project_id=project_id,
                    merge_request_iid=context.mr_iid,
                    context=context,
                    review_result=analysis_result.review_result,
                )
                if publish_result.error_message is not None:
                    return self.review_state_service.fail_review(
                        record=record,
                        error_message=(
                            f"[{self.config.execution_mode}] {publish_result.error_message}"
                        ),
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
                            "mr_iid": context.mr_iid,
                            "head_sha": context.head_sha,
                            "note_id": publish_result.note.id,
                            "note_url": publish_result.note.web_url,
                        },
                    )
            else:
                LOGGER.info(
                    "review note publication skipped by config",
                    extra={
                        "run_id": run_id,
                        "mr_iid": context.mr_iid,
                        "head_sha": context.head_sha,
                        "classification": analysis_result.review_result.classification,
                    },
                )

            dashboard_update = ReviewDashboardUpdater(
                DashboardService(self.dashboard_client)
            ).update(
                project_id=project_id,
                merge_request=intake_result.selected_merge_request,
                review_result=analysis_result.review_result,
            )
            dashboard_warning = dashboard_update.error_message
            if dashboard_warning is None:
                LOGGER.info(
                    "review dashboard mirrored",
                    extra={
                        "run_id": run_id,
                        "mr_iid": context.mr_iid,
                        "head_sha": context.head_sha,
                        "dashboard_issue_url": dashboard_update.dashboard_issue_url,
                    },
                )
            else:
                LOGGER.warning(
                    "review dashboard mirror warning",
                    extra={
                        "run_id": run_id,
                        "mr_iid": context.mr_iid,
                        "head_sha": context.head_sha,
                    },
                )
        else:
            LOGGER.info(
                "review dry-run skipped publication",
                extra={
                    "run_id": run_id,
                    "mr_iid": context.mr_iid,
                    "head_sha": context.head_sha,
                },
            )

        summary = self.review_state_service.mark_reviewed(
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
                f"[{self.config.execution_mode}] {summary.message}"
                if dashboard_warning is None
                else f"[{self.config.execution_mode}] {summary.message} {dashboard_warning}"
            ),
            state_path=summary.state_path,
        )

    def _should_publish_note(self, review_result: ReviewResult) -> bool:
        """Return whether one review result should produce an MR note."""
        if review_result.classification == "no_findings":
            return self.config.review.publish_no_findings_note
        return True

"""Merge request review workflow runner."""

from __future__ import annotations

import logging
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import PriorReviewContext
from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.gitlab_review_client import GitLabReviewClient
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.review.mr_intake import MergeRequestIntakeService
from zeroone_ops.services.review.review_analysis_service import ReviewAnalysisService
from zeroone_ops.services.review.review_context_builder import ReviewContextBuilder
from zeroone_ops.services.review.review_dashboard_updater import (
    ReviewDashboardUpdater,
)
from zeroone_ops.services.review.review_gitlab_prior_context_service import (
    ReviewGitLabPriorContextService,
)
from zeroone_ops.services.review.review_gitlab_prior_note_parser import (
    ReviewGitLabPriorNoteParser,
)
from zeroone_ops.services.review.review_overlap_analysis_service import (
    ReviewOverlapAnalysisService,
)
from zeroone_ops.services.review.review_overlap_packet_builder import (
    OverlapPacketBuilder,
)
from zeroone_ops.services.review.review_publisher import ReviewPublisher
from zeroone_ops.services.review.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import RunSummary

LOGGER = logging.getLogger(__name__)
_UNRESOLVED_BOT_AUTHOR_USERNAME = object()


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
        prior_context_service: ReviewGitLabPriorContextService | None = None,
        prior_note_parser: ReviewGitLabPriorNoteParser | None = None,
    ) -> None:
        """Initialize the review workflow runner."""
        self.repo_root = repo_root
        self.config = config
        self.review_client = review_client
        self.dashboard_client = dashboard_client
        self.review_state_service = review_state_service
        self.prior_context_service = prior_context_service
        self.prior_note_parser = prior_note_parser or ReviewGitLabPriorNoteParser()
        self._resolved_bot_author_username: str | None | object = _UNRESOLVED_BOT_AUTHOR_USERNAME

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
        prior_review_context = self._load_gitlab_prior_review_context(
            run_id=run_id,
            project_id=project_id,
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

        overlap_result = None
        overlap_packet = OverlapPacketBuilder().build(
            context=context,
            review_result=analysis_result.review_result,
        )
        if overlap_packet is not None:
            overlap_analysis = ReviewOverlapAnalysisService(self.config).analyze(overlap_packet)
            if overlap_analysis.overlap_result is not None:
                overlap_result = overlap_analysis.overlap_result
                LOGGER.info(
                    "review overlap reconciliation completed",
                    extra={
                        "run_id": run_id,
                        "mr_iid": context.mr_iid,
                        "head_sha": context.head_sha,
                        "prior_head_sha": overlap_result.prior_reviewed_head_sha,
                        "resolution_count": len(overlap_result.resolutions),
                    },
                )
            else:
                LOGGER.warning(
                    (
                        "review overlap reconciliation unavailable; omitting continuity wording "
                        f"[status={overlap_analysis.status} prior={overlap_packet.prior_head_sha} "
                        f"curr={len(overlap_packet.current_findings)} "
                        f"prev={len(overlap_packet.prior_findings)} "
                        f"cand={len(overlap_packet.candidates)}] "
                        f"{overlap_analysis.message}"
                    ),
                    extra={
                        "run_id": run_id,
                        "mr_iid": context.mr_iid,
                        "head_sha": context.head_sha,
                        "prior_head_sha": overlap_packet.prior_head_sha,
                        "current_finding_count": len(overlap_packet.current_findings),
                        "prior_finding_count": len(overlap_packet.prior_findings),
                        "candidate_count": len(overlap_packet.candidates),
                        "overlap_status": overlap_analysis.status,
                        "overlap_message": overlap_analysis.message,
                    },
                )

        note_url: str | None = None
        dashboard_warning: str | None = None
        if not active_dry_run:
            publish_result = ReviewPublisher(self.review_client).publish(
                project_id=project_id,
                merge_request_iid=context.mr_iid,
                context=context,
                review_result=analysis_result.review_result,
                overlap_result=overlap_result,
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

    def _resolve_prior_note_author_username(
        self,
        *,
        run_id: str,
        mr_iid: int,
        current_head_sha: str,
    ) -> str | None:
        """Resolve and cache the GitLab username behind the active review token."""
        if self._resolved_bot_author_username is not _UNRESOLVED_BOT_AUTHOR_USERNAME:
            return self._resolved_bot_author_username  # type: ignore[return-value]
        try:
            resolved_username = self.review_client.get_current_user_username()
        except Exception:
            LOGGER.warning(
                "review gitlab current user lookup failed; prior-note author filter disabled",
                extra={
                    "run_id": run_id,
                    "mr_iid": mr_iid,
                    "head_sha": current_head_sha,
                },
            )
            self._resolved_bot_author_username = None
            return None
        self._resolved_bot_author_username = resolved_username
        LOGGER.info(
            f"review gitlab current user resolved (username={resolved_username})",
            extra={
                "run_id": run_id,
                "mr_iid": mr_iid,
                "head_sha": current_head_sha,
                "bot_author_username": resolved_username,
            },
        )
        return resolved_username

    def _load_gitlab_prior_review_context(
        self,
        *,
        run_id: str,
        project_id: str,
        mr_iid: int,
        current_head_sha: str,
    ) -> PriorReviewContext | None:
        """Load prior review context from the latest earlier machine-safe MR note."""
        prior_context_service = self.prior_context_service or ReviewGitLabPriorContextService(
            self.review_client,
            bot_author_username=self._resolve_prior_note_author_username(
                run_id=run_id,
                mr_iid=mr_iid,
                current_head_sha=current_head_sha,
            ),
        )
        try:
            selection_result = prior_context_service.select_latest_prior_review_note(
                project_id=project_id,
                merge_request_iid=mr_iid,
                current_head_sha=current_head_sha,
            )
        except Exception:  # pragma: no cover - exercised via integration stubs
            LOGGER.warning(
                "review gitlab prior note lookup failed; omitting continuity context",
                extra={
                    "run_id": run_id,
                    "mr_iid": mr_iid,
                    "head_sha": current_head_sha,
                },
            )
            return None
        if selection_result.selected_note is None:
            LOGGER.info(
                (
                    "review gitlab prior note not found "
                    f"[reason={selection_result.reason_code} "
                    f"considered={selection_result.considered_note_count} "
                    f"author={selection_result.author_matched_note_count} "
                    f"machine={selection_result.machine_safe_note_count} "
                    f"parseable={selection_result.parseable_note_count} "
                    f"current_sha={selection_result.current_sha_skipped_count}]"
                ),
                extra={
                    "run_id": run_id,
                    "mr_iid": mr_iid,
                    "head_sha": current_head_sha,
                    "considered_note_count": selection_result.considered_note_count,
                    "author_matched_note_count": selection_result.author_matched_note_count,
                    "machine_safe_note_count": selection_result.machine_safe_note_count,
                    "parseable_note_count": selection_result.parseable_note_count,
                    "current_sha_skipped_count": selection_result.current_sha_skipped_count,
                    "reason_code": selection_result.reason_code,
                },
            )
            return None

        try:
            parse_result = self.prior_note_parser.parse_note(
                note=selection_result.selected_note,
                expected_merge_request_iid=mr_iid,
            )
        except Exception:  # pragma: no cover - defensive guard for malformed parser wiring
            LOGGER.warning(
                (
                    "review gitlab prior note parse crashed; omitting continuity context "
                    f"(selected_note_id={selection_result.selected_note.id})"
                ),
                extra={
                    "run_id": run_id,
                    "mr_iid": mr_iid,
                    "head_sha": current_head_sha,
                    "selected_note_id": selection_result.selected_note.id,
                },
            )
            return None
        if parse_result.prior_review_pass is None:
            LOGGER.warning(
                (
                    "review gitlab prior note parse failed; omitting continuity context "
                    f"[note={selection_result.selected_note.id} "
                    f"reason={selection_result.reason_code}] "
                    f"{parse_result.message}"
                ),
                extra={
                    "run_id": run_id,
                    "mr_iid": mr_iid,
                    "head_sha": current_head_sha,
                    "selected_note_id": selection_result.selected_note.id,
                    "considered_note_count": selection_result.considered_note_count,
                    "author_matched_note_count": selection_result.author_matched_note_count,
                    "machine_safe_note_count": selection_result.machine_safe_note_count,
                    "parseable_note_count": selection_result.parseable_note_count,
                    "current_sha_skipped_count": selection_result.current_sha_skipped_count,
                    "reason_code": selection_result.reason_code,
                },
            )
            return None

        LOGGER.info(
            (
                "review gitlab prior note selected "
                f"[note={selection_result.selected_note.id} "
                f"prior={parse_result.prior_review_pass.reviewed_head_sha} "
                f"reason={selection_result.reason_code} "
                f"considered={selection_result.considered_note_count} "
                f"author={selection_result.author_matched_note_count} "
                f"machine={selection_result.machine_safe_note_count} "
                f"parseable={selection_result.parseable_note_count} "
                f"current_sha={selection_result.current_sha_skipped_count}]"
            ),
            extra={
                "run_id": run_id,
                "mr_iid": mr_iid,
                "head_sha": current_head_sha,
                "selected_note_id": selection_result.selected_note.id,
                "considered_note_count": selection_result.considered_note_count,
                "author_matched_note_count": selection_result.author_matched_note_count,
                "machine_safe_note_count": selection_result.machine_safe_note_count,
                "parseable_note_count": selection_result.parseable_note_count,
                "current_sha_skipped_count": selection_result.current_sha_skipped_count,
                "reason_code": selection_result.reason_code,
                "prior_head_sha": parse_result.prior_review_pass.reviewed_head_sha,
            },
        )
        return PriorReviewContext(
            merge_request_iid=mr_iid,
            passes=[parse_result.prior_review_pass],
        )

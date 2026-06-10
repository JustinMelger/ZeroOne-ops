"""Merge request review workflow runner."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    MergeRequestReviewCandidate,
    PriorReviewContext,
    PriorReviewPass,
    ReviewResult,
)
from zeroone_ops.models.state import (
    FailureDetails,
    FailureStage,
    ReviewDiagnosticCandidate,
    ReviewDiagnosticDroppedCandidate,
    ReviewInlineCommentDecision,
    ReviewRunDiagnostics,
    RunRecord,
)
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.gitlab_review_client import GitLabReviewClient
from zeroone_ops.services.dashboard.dashboard_policy_view_builder import DashboardPolicyViewBuilder
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.review.mr_intake import MergeRequestIntakeService
from zeroone_ops.services.review.review_artifact_builder import ReviewArtifactBuilder
from zeroone_ops.services.review.review_artifact_validator import (
    ReviewArtifactValidator,
)
from zeroone_ops.services.review.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
    ReviewCandidateStageResult,
)
from zeroone_ops.services.review.review_context_builder import ReviewContextBuilder
from zeroone_ops.services.review.review_dashboard_updater import (
    ReviewDashboardUpdater,
)
from zeroone_ops.services.review.review_gitlab_prior_context_service import (
    ReviewGitLabPriorContextService,
    extract_machine_safe_review_note_payload,
)
from zeroone_ops.services.review.review_gitlab_prior_note_parser import (
    ReviewGitLabPriorNoteParser,
)
from zeroone_ops.services.review.review_inline_comment_continuity_service import (
    ReviewInlineCommentContinuityService,
)
from zeroone_ops.services.review.review_publisher import ReviewPublisher
from zeroone_ops.services.review.review_reconciliation_service import (
    ReviewReconciliationResult,
    ReviewReconciliationService,
)
from zeroone_ops.services.review.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import RunSummary

LOGGER = logging.getLogger(__name__)
_UNRESOLVED_BOT_AUTHOR_USERNAME = object()
_AUTHORITATIVE_REVIEW_CLASSIFICATIONS = frozenset(
    {"no_findings", "findings_present", "manual_review_only"}
)


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

        existing_review = self._load_same_sha_review_reference(
            run_id=run_id,
            project_id=project_id,
            merge_request=intake_result.selected_merge_request,
        )
        if existing_review is not None:
            summary = self.review_state_service.mark_same_sha_reused(
                record=record,
                merge_request=intake_result.selected_merge_request,
                prior_classification=existing_review.classification,
            )
            return RunSummary(
                run_id=summary.run_id,
                status=summary.status,
                message=f"[{self.config.execution_mode}] {summary.message}",
                state_path=summary.state_path,
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

        candidate_stage_result = ReviewCandidateGenerationService(self.config).analyze(context)
        if candidate_stage_result.raw_review_result is None:
            return self.review_state_service.fail_review(
                record=record,
                error_message=f"[{self.config.execution_mode}] {candidate_stage_result.message}",
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_ANALYSIS,
                    message=candidate_stage_result.message,
                ),
            )
        review_result = candidate_stage_result.raw_review_result

        LOGGER.info(
            "review candidate stage completed",
            extra={
                "run_id": run_id,
                "mr_iid": context.mr_iid,
                "head_sha": context.head_sha,
                "candidate_count": (
                    0
                    if candidate_stage_result.candidate_result is None
                    else len(candidate_stage_result.candidate_result.findings)
                ),
                "grounded_candidate_count": len(candidate_stage_result.accepted_candidate_ids),
                "grounding_dropped_candidate_count": len(candidate_stage_result.dropped_candidates),
                "accepted_candidate_count": len(candidate_stage_result.accepted_candidate_ids),
                "dropped_candidate_count": len(candidate_stage_result.dropped_candidates),
                "classification": review_result.classification,
                "finding_count": len(review_result.findings),
            },
        )

        reconciliation_result = ReviewReconciliationService(self.config).reconcile(
            context=context,
            candidate_stage_result=candidate_stage_result,
        )
        review_result = reconciliation_result.review_result or review_result
        overlap_result = reconciliation_result.overlap_result
        artifact_result = None
        validation_result = None
        if reconciliation_result.reconciled_decision is not None:
            artifact_result = ReviewArtifactBuilder().build(
                reconciled_decision=reconciliation_result.reconciled_decision,
                overlap_result=overlap_result,
            )
        publish_artifact = None
        if artifact_result is not None:
            validation_result = ReviewArtifactValidator().validate(artifact_result.artifact)
            publish_artifact = artifact_result.artifact
            if validation_result.status == "rejected":
                publish_artifact = ReviewArtifactValidator().build_manual_review_only_fallback(
                    artifact=artifact_result.artifact,
                    validation_result=validation_result,
                )
            inline_comment_continuity_result = (
                ReviewInlineCommentContinuityService().apply_if_enabled(
                    context=context,
                    artifact=publish_artifact,
                    enabled=self.config.review.inline_comments_enabled,
                )
            )
            publish_artifact = inline_comment_continuity_result.artifact
            review_result = publish_artifact.to_review_result()

        LOGGER.info(
            "review reconciliation completed",
            extra={
                "run_id": run_id,
                "mr_iid": context.mr_iid,
                "head_sha": context.head_sha,
                "classification": review_result.classification,
                "precision_accepted_candidate_count": (
                    0
                    if reconciliation_result.precision_decision is None
                    else sum(
                        len(finding.source_candidate_ids)
                        for finding in reconciliation_result.precision_decision.accepted_findings
                    )
                ),
                "precision_dropped_candidate_count": (
                    0
                    if reconciliation_result.precision_decision is None
                    else len(reconciliation_result.precision_decision.dropped_candidates)
                ),
                "accepted_finding_count": (
                    0
                    if reconciliation_result.reconciled_decision is None
                    else len(reconciliation_result.reconciled_decision.accepted_findings)
                ),
                "dropped_candidate_count": (
                    0
                    if reconciliation_result.reconciled_decision is None
                    else len(reconciliation_result.reconciled_decision.dropped_candidates)
                ),
                "has_overlap_result": overlap_result is not None,
                "artifact_follow_up_line_count": (
                    0 if publish_artifact is None else len(publish_artifact.follow_up_lines)
                ),
                "final_published_finding_count": len(review_result.findings),
                "artifact_validation_status": (
                    None if validation_result is None else validation_result.status
                ),
                "artifact_validation_issue_count": (
                    0 if validation_result is None else len(validation_result.issues)
                ),
                "reused_inline_comment_count": (
                    0
                    if artifact_result is None
                    else inline_comment_continuity_result.reused_inline_comment_count
                ),
                "inline_comment_decision_count": (
                    0
                    if artifact_result is None
                    else len(inline_comment_continuity_result.decisions)
                ),
            },
        )
        if context.prior_review_context is not None and overlap_result is None:
            LOGGER.warning(
                "review overlap reconciliation unavailable; omitting continuity wording",
                extra={
                    "run_id": run_id,
                    "mr_iid": context.mr_iid,
                    "head_sha": context.head_sha,
                    "reconciliation_message": reconciliation_result.message,
                },
            )

        note_id: int | None = None
        note_url: str | None = None
        dashboard_warning: str | None = None
        publish_warning: str | None = None
        publish_result = None
        if not active_dry_run:
            if artifact_result is None:
                return self.review_state_service.fail_review(
                    record=record,
                    error_message=(
                        f"[{self.config.execution_mode}] "
                        "Review artifact build failed before publish."
                    ),
                    failure=FailureDetails(
                        stage=FailureStage.REVIEW_PUBLISH,
                        message="Review artifact build failed before publish.",
                    ),
                )
            if publish_artifact is None:  # pragma: no cover - defensive typing guard
                return self.review_state_service.fail_review(
                    record=record,
                    error_message=(
                        f"[{self.config.execution_mode}] "
                        "Validated review artifact was unavailable before publish."
                    ),
                    failure=FailureDetails(
                        stage=FailureStage.REVIEW_PUBLISH,
                        message="Validated review artifact was unavailable before publish.",
                    ),
                )
            publish_result = ReviewPublisher(self.review_client).publish_artifact(
                project_id=project_id,
                merge_request_iid=context.mr_iid,
                context=context,
                artifact=publish_artifact,
                inline_comment_decisions=inline_comment_continuity_result.decisions,
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
                note_id = publish_result.note.id
                note_url = publish_result.note.web_url
                publish_artifact = publish_result.artifact
                review_result = publish_artifact.to_review_result()
                publish_warning = publish_result.warning_message
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
                if publish_warning is not None:
                    LOGGER.warning(
                        "review inline comment transport warning",
                        extra={
                            "run_id": run_id,
                            "mr_iid": context.mr_iid,
                            "head_sha": context.head_sha,
                            "warning": publish_warning,
                        },
                    )
            dashboard_update = ReviewDashboardUpdater(
                DashboardService(
                    self.dashboard_client,
                    policy_view_builder=DashboardPolicyViewBuilder(
                        repo_root=self.repo_root,
                        config=self.config,
                        state=self.review_state_service.state,
                    ),
                )
            ).update(
                project_id=project_id,
                merge_request=intake_result.selected_merge_request,
                review_result=review_result,
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

        if publish_artifact is None:  # pragma: no cover - defensive typing guard
            return self.review_state_service.fail_review(
                record=record,
                error_message=(
                    f"[{self.config.execution_mode}] "
                    "Validated review artifact was unavailable before state persistence."
                ),
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_PUBLISH,
                    message="Validated review artifact was unavailable before state persistence.",
                ),
            )

        inline_comment_decisions = (
            []
            if active_dry_run
            else (
                publish_result.inline_comment_decisions
                if publish_result is not None and publish_result.inline_comment_decisions
                else inline_comment_continuity_result.decisions
            )
        )
        _log_inline_comment_rollout(
            run_id=run_id,
            mr_iid=context.mr_iid,
            head_sha=context.head_sha,
            inline_comments_enabled=self.config.review.inline_comments_enabled,
            inline_comment_transport_enabled=(
                self.config.review.inline_comments_enabled and not active_dry_run
            ),
            decisions=inline_comment_decisions,
        )
        record.review_diagnostics = _build_review_run_diagnostics(
            head_sha=context.head_sha,
            candidate_stage_result=candidate_stage_result,
            reconciliation_result=reconciliation_result,
            review_result=review_result,
            inline_comment_decisions=inline_comment_decisions,
        )
        summary = self.review_state_service.mark_reviewed(
            record=record,
            merge_request=intake_result.selected_merge_request,
            artifact=publish_artifact,
            note_id=note_id,
            note_url=note_url,
            dry_run=active_dry_run,
        )
        return RunSummary(
            run_id=summary.run_id,
            status=summary.status,
            message=(
                f"[{self.config.execution_mode}] {summary.message}"
                if publish_warning is None and dashboard_warning is None
                else " ".join(
                    part
                    for part in (
                        f"[{self.config.execution_mode}] {summary.message}",
                        publish_warning,
                        dashboard_warning,
                    )
                    if part
                )
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

    def _load_same_sha_review_reference(
        self,
        *,
        run_id: str,
        project_id: str,
        merge_request: MergeRequestReviewCandidate,
    ) -> PriorReviewPass | None:
        """Return the authoritative existing review reference for one MR SHA."""
        review_state = self.review_state_service.state.reviews.get(
            f"{merge_request.iid}:{merge_request.head_sha}"
        )
        if review_state is not None and _is_authoritative_review_classification(
            review_state.status
        ):
            return PriorReviewPass(
                reviewed_head_sha=review_state.head_sha,
                classification=review_state.status,
                findings_count=review_state.findings_count,
                summary=review_state.summary,
                note_url=review_state.note_url,
                findings=[],
            )

        try:
            notes = self.review_client.list_merge_request_notes(
                project_id=project_id,
                merge_request_iid=merge_request.iid,
            )
        except (GitLabClientError, httpx.HTTPError, OSError) as exc:
            LOGGER.warning(
                "review same-sha lookup via gitlab note failed; continuing without reuse",
                extra={
                    "run_id": run_id,
                    "mr_iid": merge_request.iid,
                    "head_sha": merge_request.head_sha,
                    "error": str(exc),
                },
            )
            return None
        bot_author_username = self._resolve_prior_note_author_username(
            run_id=run_id,
            mr_iid=merge_request.iid,
            current_head_sha=merge_request.head_sha,
        )
        if bot_author_username is None:
            LOGGER.info(
                "review same-sha gitlab note reuse disabled because bot username is unresolved",
                extra={
                    "run_id": run_id,
                    "mr_iid": merge_request.iid,
                    "head_sha": merge_request.head_sha,
                },
            )
            return None
        candidate_notes = []
        for note in notes:
            if note.author_username != bot_author_username:
                continue
            payload = extract_machine_safe_review_note_payload(note.body)
            if payload is None:
                continue
            reviewed_head_sha = payload.get("reviewed_head_sha")
            classification = payload.get("classification")
            if reviewed_head_sha != merge_request.head_sha:
                continue
            if not isinstance(classification, str) or not _is_authoritative_review_classification(
                classification
            ):
                continue
            candidate_notes.append(note)
        if not candidate_notes:
            return None
        selected_note = sorted(
            candidate_notes,
            key=lambda note: ((note.created_at or ""), note.id),
            reverse=True,
        )[0]
        parse_result = self.prior_note_parser.parse_note(
            note=selected_note,
            expected_merge_request_iid=merge_request.iid,
        )
        return parse_result.prior_review_pass


def _is_authoritative_review_classification(classification: str) -> bool:
    """Return whether one review classification is authoritative for same-SHA reuse."""
    return classification in _AUTHORITATIVE_REVIEW_CLASSIFICATIONS


def _build_review_run_diagnostics(
    *,
    head_sha: str,
    candidate_stage_result: ReviewCandidateStageResult,
    reconciliation_result: ReviewReconciliationResult,
    review_result: ReviewResult,
    inline_comment_decisions: list[ReviewInlineCommentDecision],
) -> ReviewRunDiagnostics:
    """Build one bounded staged-review diagnostics record for internal use."""
    candidate_findings = (
        []
        if candidate_stage_result.candidate_result is None
        else [
            ReviewDiagnosticCandidate(
                candidate_id=finding.candidate_id,
                title=finding.title,
                file_path=finding.file_path,
            )
            for finding in candidate_stage_result.candidate_result.findings
        ]
    )
    precision_accepted_candidate_ids = (
        []
        if reconciliation_result.precision_decision is None
        else [
            candidate_id
            for finding in reconciliation_result.precision_decision.accepted_findings
            for candidate_id in finding.source_candidate_ids
        ]
    )
    precision_dropped_candidates = (
        []
        if reconciliation_result.precision_decision is None
        else [
            ReviewDiagnosticDroppedCandidate(
                candidate_id=candidate.candidate_id,
                drop_reason=candidate.drop_reason,
                notes=candidate.notes,
            )
            for candidate in reconciliation_result.precision_decision.dropped_candidates
        ]
    )
    return ReviewRunDiagnostics(
        reviewed_head_sha=head_sha,
        candidate_findings=candidate_findings,
        grounding_accepted_candidate_ids=list(candidate_stage_result.accepted_candidate_ids),
        grounding_dropped_candidates=[
            ReviewDiagnosticDroppedCandidate(
                candidate_id=candidate.candidate_id,
                drop_reason=candidate.drop_reason,
                notes=candidate.notes,
            )
            for candidate in candidate_stage_result.dropped_candidates
        ],
        precision_accepted_candidate_ids=precision_accepted_candidate_ids,
        precision_dropped_candidates=precision_dropped_candidates,
        inline_comment_decisions=inline_comment_decisions,
        final_published_finding_summaries=[
            f"{finding.file_path}: {finding.title}" for finding in review_result.findings
        ],
        final_classification=review_result.classification,
    )


def _log_inline_comment_rollout(
    *,
    run_id: str,
    mr_iid: int,
    head_sha: str,
    inline_comments_enabled: bool,
    inline_comment_transport_enabled: bool,
    decisions: list[ReviewInlineCommentDecision],
) -> None:
    """Emit compact CI-visible rollout diagnostics for inline-comment continuity."""
    if not decisions:
        LOGGER.info(
            "review inline comment rollout summary",
            extra={
                "run_id": run_id,
                "mr_iid": mr_iid,
                "head_sha": head_sha,
                "inline_comments_enabled": inline_comments_enabled,
                "inline_comment_transport_enabled": inline_comment_transport_enabled,
                "inline_comment_decision_count": 0,
                "inline_comment_reuse_count": 0,
                "inline_comment_new_candidate_count": 0,
                "inline_comment_summary_only_count": 0,
                "inline_comment_trusted_count": 0,
                "inline_comment_weak_count": 0,
                "inline_comment_untrusted_count": 0,
            },
        )
        return

    for decision in decisions:
        LOGGER.info(
            "review inline comment decision",
            extra={
                "run_id": run_id,
                "mr_iid": mr_iid,
                "head_sha": head_sha,
                "finding_identity": decision.finding_identity,
                "severity": decision.severity,
                "file_path": decision.file_path,
                "line_start": decision.line_start,
                "line_end": decision.line_end,
                "region_hint": decision.region_hint,
                "inline_comments_enabled": decision.inline_comments_enabled,
                "inline_comment_transport_enabled": inline_comment_transport_enabled,
                "location_trust": decision.location_trust,
                "existing_inline_comment_found": decision.existing_inline_comment_found,
                "anchor_reuse_decision": decision.anchor_reuse_decision,
                "anchor_reuse_reason": decision.anchor_reuse_reason,
                "authoritative_note_id": decision.authoritative_note_id,
                "existing_comment_id": decision.existing_comment_id,
                "new_comment_id": decision.new_comment_id,
            },
        )

    LOGGER.info(
        "review inline comment rollout summary",
        extra={
            "run_id": run_id,
            "mr_iid": mr_iid,
            "head_sha": head_sha,
            "inline_comments_enabled": inline_comments_enabled,
            "inline_comment_transport_enabled": inline_comment_transport_enabled,
            "inline_comment_decision_count": len(decisions),
            "inline_comment_reuse_count": sum(
                1 for decision in decisions if decision.anchor_reuse_decision == "reuse"
            ),
            "inline_comment_new_candidate_count": sum(
                1 for decision in decisions if decision.anchor_reuse_decision == "new"
            ),
            "inline_comment_summary_only_count": sum(
                1 for decision in decisions if decision.anchor_reuse_decision == "summary_only"
            ),
            "inline_comment_trusted_count": sum(
                1 for decision in decisions if decision.location_trust == "trusted"
            ),
            "inline_comment_weak_count": sum(
                1 for decision in decisions if decision.location_trust == "weak"
            ),
            "inline_comment_untrusted_count": sum(
                1 for decision in decisions if decision.location_trust == "untrusted"
            ),
        },
    )

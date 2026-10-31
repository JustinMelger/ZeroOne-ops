"""Change-request review workflow runner."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ReviewResult,
)
from zeroone_ops.models.state import (
    FailureDetails,
    FailureStage,
    ReviewDiagnosticCandidate,
    ReviewDiagnosticCandidateAnnotation,
    ReviewDiagnosticDroppedCandidate,
    ReviewInlineCommentDecision,
    ReviewRunDiagnostics,
    RunRecord,
)
from zeroone_ops.providers.review.platform import ChangeRequestReviewPlatformProtocol
from zeroone_ops.services.review.context.remediation_review_context_resolver import (
    RemediationReviewContextResolver,
)
from zeroone_ops.services.review.context.review_context_builder import (
    ReviewContextBuilder,
)
from zeroone_ops.services.review.continuity.review_continuity_context_service import (
    ReviewContinuityContextService,
)
from zeroone_ops.services.review.continuity.review_inline_comment_continuity_service import (
    ReviewInlineCommentContinuityService,
)
from zeroone_ops.services.review.continuity.review_projection_repair_service import (
    ReviewProjectionRepairService,
)
from zeroone_ops.services.review.intake.change_request_intake import ChangeRequestIntakeService
from zeroone_ops.services.review.pipeline.review_artifact_builder import (
    ReviewArtifactBuilder,
)
from zeroone_ops.services.review.pipeline.review_artifact_validator import (
    ReviewArtifactValidator,
)
from zeroone_ops.services.review.pipeline.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
    ReviewCandidateStageResult,
)
from zeroone_ops.services.review.pipeline.review_reconciliation_service import (
    ReviewReconciliationResult,
    ReviewReconciliationService,
)
from zeroone_ops.services.review.publish.review_finalization_service import (
    ReviewFinalizationService,
    ReviewProjectionService,
)
from zeroone_ops.services.review.publish.review_publisher import ReviewPublisher
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import RunSummary

LOGGER = logging.getLogger(__name__)


class ReviewRunner:
    """Run the change-request review workflow with injected dependencies."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        review_client: ChangeRequestReviewPlatformProtocol,
        review_state_service: ReviewStateService,
        remediation_context_resolver: RemediationReviewContextResolver,
        continuity_context_service: ReviewContinuityContextService,
        projection_repair_service: ReviewProjectionRepairService,
        review_projection_factory: Callable[[], ReviewProjectionService | None],
    ) -> None:
        """Initialize the review workflow runner."""
        self.repo_root = repo_root
        self.config = config
        self.review_client = review_client
        self.review_state_service = review_state_service
        self.remediation_context_resolver = remediation_context_resolver
        self.continuity_context_service = continuity_context_service
        self.projection_repair_service = projection_repair_service
        self.review_projection_factory = review_projection_factory

    def run(
        self,
        *,
        repository_id: str,
        current_change_request_number: int | None,
        triggered_head_sha: str | None,
        run_id: str,
        record: RunRecord,
        active_dry_run: bool,
    ) -> RunSummary:
        """Run one change-request review workflow."""
        intake_result = ChangeRequestIntakeService(self.review_client).select_change_request(
            state=self.review_state_service.state,
            repository_id=repository_id,
            change_request_number=current_change_request_number,
            triggered_head_sha=triggered_head_sha,
        )
        selected_change_request = intake_result.selected_change_request
        if selected_change_request is None:
            if intake_result.selected_skip_reason == "head_sha_mismatch":
                return self.review_state_service.fail_review(
                    record=record,
                    error_message=f"[{self.config.execution_mode}] {intake_result.message}",
                    failure=FailureDetails(
                        stage=FailureStage.REVIEW_INTAKE,
                        message=intake_result.message,
                    ),
                )
            return self.review_state_service.finish_no_review(
                record=record,
                message=f"[{self.config.execution_mode}] {intake_result.message}",
            )

        existing_review = self.continuity_context_service.load_same_sha_review_reference(
            run_id=run_id,
            repository_id=repository_id,
            change_request=selected_change_request,
        )
        if existing_review is not None:
            same_sha_state = self.review_state_service.state.reviews.get(
                f"{selected_change_request.change_request_number}:{selected_change_request.head_sha}"
            )
            projection_retry_message = self.projection_repair_service.retry_if_needed(
                run_id=run_id,
                repository_id=repository_id,
                change_request=selected_change_request,
                review_state=same_sha_state,
                active_dry_run=active_dry_run,
            )
            summary = self.review_state_service.mark_same_sha_reused(
                record=record,
                change_request=selected_change_request,
                prior_classification=existing_review.classification,
            )
            return RunSummary(
                run_id=summary.run_id,
                status=summary.status,
                message=" ".join(
                    part
                    for part in (
                        f"[{self.config.execution_mode}] {summary.message}",
                        projection_retry_message,
                    )
                    if part
                ),
                state_path=summary.state_path,
            )

        LOGGER.info(
            "review run targeting change request",
            extra={
                "run_id": run_id,
                "change_request_number": selected_change_request.change_request_number,
                "head_sha": selected_change_request.head_sha,
                "source_branch": selected_change_request.source_branch,
                "target_branch": selected_change_request.target_branch,
                "dry_run": active_dry_run,
            },
        )

        context_result = ReviewContextBuilder(
            repo_root=self.repo_root,
            config=self.config,
        ).build(
            selected_change_request,
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
        context = context_result.context
        prior_review_context = self.continuity_context_service.load_prior_review_context(
            run_id=run_id,
            repository_id=repository_id,
            change_request_number=selected_change_request.change_request_number,
            current_head_sha=selected_change_request.head_sha,
        )
        if prior_review_context is not None:
            context = context.model_copy(update={"prior_review_context": prior_review_context})
        if not active_dry_run:
            context = self.remediation_context_resolver.resolve(
                repository_id=repository_id,
                context=context,
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
                "change_request_number": context.change_request_number,
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
                "change_request_number": context.change_request_number,
                "head_sha": context.head_sha,
                "candidate_count": (
                    0
                    if candidate_stage_result.candidate_result is None
                    else len(candidate_stage_result.candidate_result.findings)
                ),
                "forwarded_candidate_count": len(candidate_stage_result.forwarded_candidate_ids),
                "candidate_annotation_count": len(candidate_stage_result.candidate_annotations),
                "pre_precision_dropped_candidate_count": len(
                    candidate_stage_result.pre_precision_dropped_candidates
                ),
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
                "change_request_number": context.change_request_number,
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
                    "change_request_number": context.change_request_number,
                    "head_sha": context.head_sha,
                    "reconciliation_message": reconciliation_result.message,
                },
            )

        if artifact_result is None:
            return self.review_state_service.fail_review(
                record=record,
                error_message=(
                    f"[{self.config.execution_mode}] Review artifact build failed before publish."
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
                    "Validated review artifact was unavailable before state persistence."
                ),
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_PUBLISH,
                    message="Validated review artifact was unavailable before state persistence.",
                ),
            )

        finalization_result = ReviewFinalizationService(
            review_publisher=ReviewPublisher(self.review_client),
            review_projection_factory=self.review_projection_factory,
        ).finalize(
            run_id=run_id,
            repository_id=repository_id,
            active_dry_run=active_dry_run,
            change_request=selected_change_request,
            context=context,
            artifact=publish_artifact,
            inline_comment_decisions=inline_comment_continuity_result.decisions,
        )
        if finalization_result.error_message is not None:
            return self.review_state_service.fail_review(
                record=record,
                error_message=(
                    f"[{self.config.execution_mode}] {finalization_result.error_message}"
                ),
                failure=FailureDetails(
                    stage=FailureStage.REVIEW_PUBLISH,
                    message=finalization_result.error_message,
                ),
            )

        publish_artifact = finalization_result.artifact
        review_result = finalization_result.review_result
        note_id = finalization_result.note_id
        note_url = finalization_result.note_url
        publish_warning = finalization_result.publish_warning
        projection_warning = finalization_result.projection_warning

        inline_comment_decisions = finalization_result.inline_comment_decisions
        _log_inline_comment_rollout(
            run_id=run_id,
            change_request_number=context.change_request_number,
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
            change_request=selected_change_request,
            artifact=publish_artifact,
            note_id=note_id,
            note_url=note_url,
            projection_retry_pending=projection_warning is not None,
            projection_retry_warning=projection_warning,
            dry_run=active_dry_run,
        )
        return RunSummary(
            run_id=summary.run_id,
            status=summary.status,
            message=(
                f"[{self.config.execution_mode}] {summary.message}"
                if publish_warning is None and projection_warning is None
                else " ".join(
                    part
                    for part in (
                        f"[{self.config.execution_mode}] {summary.message}",
                        publish_warning,
                        projection_warning,
                    )
                    if part
                )
            ),
            state_path=summary.state_path,
        )


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
        forwarded_candidate_ids=list(candidate_stage_result.forwarded_candidate_ids),
        pre_precision_dropped_candidates=[
            ReviewDiagnosticDroppedCandidate(
                candidate_id=candidate.candidate_id,
                drop_reason=candidate.drop_reason,
                notes=candidate.notes,
            )
            for candidate in candidate_stage_result.pre_precision_dropped_candidates
        ],
        candidate_annotations=[
            ReviewDiagnosticCandidateAnnotation(
                candidate_id=annotation.candidate_id,
                flags=list(annotation.flags),
                notes=list(annotation.notes),
            )
            for annotation in candidate_stage_result.candidate_annotations
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
    change_request_number: int,
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
                "change_request_number": change_request_number,
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
                "change_request_number": change_request_number,
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
            "change_request_number": change_request_number,
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

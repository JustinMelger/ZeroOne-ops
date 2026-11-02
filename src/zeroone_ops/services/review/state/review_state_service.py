"""Review state orchestration service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewInlineComment,
    PriorReviewPass,
    PublishableReviewArtifact,
    ReviewComment,
)
from zeroone_ops.models.state import (
    AppState,
    ChangeRequestReviewState,
    FailureDetails,
    PriorReviewFindingState,
    PriorReviewInlineCommentState,
    RunRecord,
    RunStatus,
    utc_now,
)
from zeroone_ops.services.review.intake.change_request_selector import build_review_revision_key
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.shared.state_store import StateStore

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zeroone_ops.models.review_overview import ReviewOverviewPass


class ReviewStateService:
    """Persist review run lifecycle and reviewed revision state."""

    def __init__(
        self,
        state_store: StateStore,
        state: AppState,
        *,
        max_prior_review_passes: int = 2,
    ) -> None:
        """Initialize the review state service."""
        self.state_store = state_store
        self.state = state
        self.max_prior_review_passes = max_prior_review_passes

    def start_run(self, run_id: str) -> RunRecord:
        """Append and return a new started run record."""
        started_at = utc_now()
        record = RunRecord(
            run_id=run_id,
            status=RunStatus.STARTED,
            started_at=started_at,
            updated_at=started_at,
        )
        self.state_store.append_run(self.state, record)
        return record

    def finish_no_review(self, *, record: RunRecord, message: str) -> RunSummary:
        """Persist a no-review result and return the run summary."""
        record.status = RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        self.state_store.save(self.state)
        return RunSummary(
            run_id=record.run_id,
            status=record.status,
            message=message,
            state_path=self.state_store.path,
        )

    def fail_review(
        self,
        *,
        record: RunRecord,
        error_message: str,
        failure: FailureDetails,
    ) -> RunSummary:
        """Persist a failed review run and return the summary."""
        record.status = RunStatus.FAILED
        record.error_message = error_message
        record.failure = failure
        record.updated_at = utc_now()
        self.state_store.save(self.state)
        LOGGER.error(
            "review run failed",
            extra={"run_id": record.run_id, "stage": failure.stage.value},
        )
        return RunSummary(
            run_id=record.run_id,
            status=record.status,
            message=error_message,
            state_path=self.state_store.path,
        )

    def mark_reviewed(
        self,
        *,
        record: RunRecord,
        change_request: ChangeRequestReviewCandidate,
        artifact: PublishableReviewArtifact,
        note_id: int | None,
        note_url: str | None,
        projection_retry_pending: bool = False,
        projection_retry_warning: str | None = None,
        review_pass_id: str | None = None,
        projection_reference: str | None = None,
        overview_pass: ReviewOverviewPass | None = None,
        dry_run: bool,
    ) -> RunSummary:
        """Persist a reviewed change-request revision and return the summary."""
        if overview_pass is not None:
            if overview_pass.head_sha != change_request.head_sha:
                raise ValueError("Completed overview pass must match the reviewed head.")
            overview_pass = overview_pass.model_copy(
                update={
                    "artifact": artifact.model_copy(deep=True),
                    "projection_pending": projection_retry_pending,
                    "projection_warning": projection_retry_warning,
                },
                deep=True,
            )
            review_pass_id = overview_pass.pass_id
            projection_reference = overview_pass.projection_reference
        record.status = RunStatus.REVIEWED
        record.updated_at = utc_now()
        if not dry_run:
            dedup_key = build_review_revision_key(
                change_request_number=change_request.change_request_number,
                head_sha=change_request.head_sha,
            )
            self.state.reviews[dedup_key] = ChangeRequestReviewState(
                change_request_number=change_request.change_request_number,
                head_sha=change_request.head_sha,
                status=artifact.classification,
                last_run_id=record.run_id,
                findings_count=len(artifact.findings),
                summary=artifact.summary,
                follow_up_lines=list(artifact.follow_up_lines),
                findings=_build_prior_review_findings_from_artifact(artifact),
                note_id=note_id,
                note_url=note_url,
                projection_retry_pending=projection_retry_pending,
                projection_retry_warning=projection_retry_warning,
                projection_artifact=artifact.model_copy(deep=True),
                review_pass_id=review_pass_id,
                projection_reference=projection_reference,
                overview_pass=(
                    overview_pass.model_copy(deep=True) if overview_pass is not None else None
                ),
            )
            self._trim_prior_reviews_for_change_request(
                change_request.change_request_number,
                current_review_key=dedup_key if overview_pass is not None else None,
            )
        self.state_store.save(self.state)
        summary_clause = _review_classification_summary(artifact)
        base_message = (
            f"Reviewed change request #{change_request.change_request_number} "
            f"at {change_request.head_sha}. "
            f"Classification: {artifact.classification}. {summary_clause}"
        )
        if dry_run:
            base_message = f"{base_message} Dry-run skipped note publication."
        elif note_url is not None:
            base_message = f"{base_message} Review note: {note_url}"
        return RunSummary(
            run_id=record.run_id,
            status=record.status,
            message=base_message,
            state_path=self.state_store.path,
        )

    def hydrate_overview_pass(
        self,
        *,
        change_request_number: int,
        review_pass: ReviewOverviewPass,
        note: ReviewComment,
    ) -> None:
        """Replace the local cache with one verified provider snapshot."""
        review_pass = self.retain_local_inline_metadata(
            change_request_number=change_request_number, review_pass=review_pass
        )
        artifact = review_pass.artifact
        key = build_review_revision_key(
            change_request_number=change_request_number, head_sha=review_pass.head_sha
        )
        self.state.reviews[key] = ChangeRequestReviewState(
            change_request_number=change_request_number,
            head_sha=review_pass.head_sha,
            status=artifact.classification,
            last_run_id=review_pass.run_id,
            findings_count=len(artifact.findings),
            summary=artifact.summary,
            follow_up_lines=list(artifact.follow_up_lines),
            findings=_build_prior_review_findings_from_artifact(artifact),
            note_id=note.id,
            note_url=note.web_url,
            review_pass_id=review_pass.pass_id,
            projection_reference=review_pass.projection_reference,
            projection_retry_pending=review_pass.projection_pending,
            projection_retry_warning=review_pass.projection_warning,
            projection_artifact=artifact.model_copy(deep=True),
            overview_pass=review_pass.model_copy(deep=True),
            updated_at=review_pass.completed_at,
        )
        self._trim_prior_reviews_for_change_request(change_request_number, current_review_key=key)
        self.state_store.save(self.state)

    def retain_local_inline_metadata(
        self, *, change_request_number: int, review_pass: ReviewOverviewPass
    ) -> ReviewOverviewPass:
        """Fill missing receipts for an identical provider pass, preserving remote authority."""
        cached = self.state.reviews.get(
            build_review_revision_key(
                change_request_number=change_request_number, head_sha=review_pass.head_sha
            )
        )
        local = cached.overview_pass if cached is not None else None
        if local is None:
            return review_pass
        mutable_fields = {
            "artifact",
            "inline_decisions",
            "projection_pending",
            "projection_warning",
            "projection_reference",
        }
        if local.model_dump(exclude=mutable_fields) != review_pass.model_dump(
            exclude=mutable_fields
        ):
            return review_pass
        artifact_exclusions = {"findings": {"__all__": {"inline_comment"}}}
        if local.artifact.model_dump(
            exclude=artifact_exclusions
        ) != review_pass.artifact.model_dump(exclude=artifact_exclusions):
            return review_pass

        findings = []
        for remote_finding, local_finding in zip(
            review_pass.artifact.findings, local.artifact.findings, strict=True
        ):
            receipt = local_finding.inline_comment
            remote_receipt = remote_finding.inline_comment
            if (
                receipt is not None
                and receipt.status == "published"
                and (remote_receipt is None or remote_receipt.status == "shadow")
            ):
                remote_finding = remote_finding.model_copy(
                    update={"inline_comment": receipt.model_copy(deep=True)}, deep=True
                )
            findings.append(remote_finding)
        actual_receipts = {
            finding.inline_comment.comment_id
            for finding in findings
            if finding.inline_comment is not None and finding.inline_comment.status == "published"
        }
        decisions = {
            (
                decision.finding_identity,
                decision.file_path,
                decision.line_start,
                decision.line_end,
            ): decision
            for decision in review_pass.inline_decisions
        }
        for decision in local.inline_decisions:
            key = (
                decision.finding_identity,
                decision.file_path,
                decision.line_start,
                decision.line_end,
            )
            remote_decision = decisions.get(key)
            receipt_id = decision.new_comment_id or decision.existing_comment_id
            if receipt_id in actual_receipts and (
                remote_decision is None
                or (remote_decision.new_comment_id or remote_decision.existing_comment_id) is None
            ):
                decisions[key] = decision.model_copy(deep=True)
        return review_pass.model_copy(
            update={
                "artifact": review_pass.artifact.model_copy(
                    update={"findings": findings}, deep=True
                ),
                "inline_decisions": list(decisions.values()),
            },
            deep=True,
        )

    def update_projection_retry_state(
        self,
        *,
        change_request_number: int,
        head_sha: str,
        last_run_id: str,
        pending: bool,
        warning: str | None,
    ) -> None:
        """Persist the current projection-retry state for one reviewed revision."""
        review_state = self.state.reviews.get(
            build_review_revision_key(
                change_request_number=change_request_number,
                head_sha=head_sha,
            )
        )
        if review_state is None:
            return
        review_state.projection_retry_pending = pending
        review_state.projection_retry_warning = warning
        if review_state.overview_pass is not None:
            review_state.overview_pass = review_state.overview_pass.model_copy(
                update={"projection_pending": pending, "projection_warning": warning}, deep=True
            )
        review_state.last_run_id = last_run_id
        review_state.updated_at = utc_now()
        self.state_store.save(self.state)

    def mark_same_sha_reused(
        self,
        *,
        record: RunRecord,
        change_request: ChangeRequestReviewCandidate,
        prior_classification: str | None,
    ) -> RunSummary:
        """Persist an operational same-SHA reuse outcome and return the summary."""
        record.status = RunStatus.REVIEWED
        record.updated_at = utc_now()
        self.state_store.save(self.state)
        message = (
            f"Reviewed change request #{change_request.change_request_number} "
            f"at {change_request.head_sha}. "
        )
        message += "No new changes after the last review."
        if prior_classification is not None:
            message += f" Earlier classification: {prior_classification}."
        return RunSummary(
            run_id=record.run_id,
            status=record.status,
            message=message,
            state_path=self.state_store.path,
        )

    def _trim_prior_reviews_for_change_request(
        self, change_request_number: int, *, current_review_key: str | None = None
    ) -> None:
        """Keep only the most recent bounded review passes for one change request."""
        retention_limit = self.max_prior_review_passes
        if current_review_key is not None:
            retention_limit = max(1, retention_limit)
        if retention_limit <= 0:
            review_keys_to_remove = [
                key
                for key, value in self.state.reviews.items()
                if value.change_request_number == change_request_number
            ]
            for key in review_keys_to_remove:
                self.state.reviews.pop(key, None)
            return

        matching_reviews = [
            (key, value)
            for key, value in self.state.reviews.items()
            if value.change_request_number == change_request_number
        ]
        if len(matching_reviews) <= retention_limit:
            return

        matching_reviews.sort(
            key=lambda pair: (
                pair[0] == current_review_key,
                pair[1].updated_at,
                pair[1].head_sha,
            ),
            reverse=True,
        )
        for key, _value in matching_reviews[retention_limit:]:
            self.state.reviews.pop(key, None)

    def load_prior_review_context(
        self,
        *,
        change_request_number: int,
        current_head_sha: str,
    ) -> PriorReviewContext | None:
        """Return bounded persisted prior review context for one change request."""
        matching_reviews = [
            review_state
            for review_state in self.state.reviews.values()
            if review_state.change_request_number == change_request_number
            and review_state.head_sha != current_head_sha
        ]
        if not matching_reviews:
            return None
        matching_reviews.sort(
            key=lambda review_state: (review_state.updated_at, review_state.head_sha),
            reverse=True,
        )
        return PriorReviewContext(
            change_request_number=change_request_number,
            passes=[
                PriorReviewPass(
                    reviewed_head_sha=review_state.head_sha,
                    classification=review_state.status,
                    findings_count=review_state.findings_count,
                    summary=review_state.summary,
                    note_id=review_state.note_id,
                    note_url=review_state.note_url,
                    findings=[
                        PriorReviewFinding(
                            identity=finding.identity,
                            legacy_identity=finding.legacy_identity,
                            summary=finding.summary,
                            severity=finding.severity,
                            file_path=finding.file_path,
                            line_start=finding.line_start,
                            line_end=finding.line_end,
                            title=finding.title,
                            symbol=finding.symbol,
                            issue_kind=finding.issue_kind,
                            region_hint=finding.region_hint,
                            inline_comment=(
                                None
                                if finding.inline_comment is None
                                else PriorReviewInlineComment(
                                    comment_id=finding.inline_comment.comment_id,
                                    comment_url=finding.inline_comment.comment_url,
                                    status=finding.inline_comment.status,
                                    anchor_file_path=finding.inline_comment.anchor_file_path,
                                    anchor_line_start=finding.inline_comment.anchor_line_start,
                                    anchor_line_end=finding.inline_comment.anchor_line_end,
                                )
                            ),
                        )
                        for finding in review_state.findings
                    ],
                )
                for review_state in matching_reviews[: self.max_prior_review_passes]
            ],
        )


def build_overview_prior_review_pass(
    *, review_pass: ReviewOverviewPass, note: ReviewComment
) -> PriorReviewPass:
    """Build full continuity evidence from a verified complete overview snapshot."""
    artifact = review_pass.artifact
    return PriorReviewPass(
        reviewed_head_sha=review_pass.head_sha,
        classification=artifact.classification,
        findings_count=len(artifact.findings),
        summary=artifact.summary,
        note_id=note.id,
        note_url=note.web_url,
        findings=[
            PriorReviewFinding.model_validate(finding.model_dump())
            for finding in _build_prior_review_findings_from_artifact(artifact)
        ],
    )


def _build_prior_review_findings_from_artifact(
    artifact: PublishableReviewArtifact,
) -> list[PriorReviewFindingState]:
    """Mirror publish-shaped findings into persisted prior-review state."""
    normalized_findings: list[PriorReviewFindingState] = []
    for finding in artifact.findings:
        normalized_findings.append(
            PriorReviewFindingState(
                identity=finding.stable_identity,
                legacy_identity=finding.legacy_identity,
                summary=f"{finding.file_path}: {finding.title}",
                severity=finding.severity,
                file_path=finding.file_path,
                line_start=finding.line_start,
                line_end=finding.line_end,
                title=finding.title,
                symbol=finding.symbol,
                issue_kind=finding.issue_kind,
                region_hint=finding.region_hint,
                inline_comment=(
                    None
                    if finding.inline_comment is None
                    else PriorReviewInlineCommentState(
                        comment_id=finding.inline_comment.comment_id,
                        comment_url=finding.inline_comment.comment_url,
                        status=finding.inline_comment.status,
                        anchor_file_path=finding.inline_comment.anchor_file_path,
                        anchor_line_start=finding.inline_comment.anchor_line_start,
                        anchor_line_end=finding.inline_comment.anchor_line_end,
                    )
                ),
            )
        )
    return normalized_findings


def _review_classification_summary(artifact: PublishableReviewArtifact) -> str:
    """Return one operator-facing review outcome summary."""
    if artifact.classification == "manual_review_only":
        return (
            f"Bot assessment was insufficient for a trustworthy review decision. {artifact.summary}"
        )
    return artifact.summary

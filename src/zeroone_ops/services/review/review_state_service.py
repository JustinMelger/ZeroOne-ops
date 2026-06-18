"""Review state orchestration service."""

from __future__ import annotations

import logging

from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewInlineComment,
    PriorReviewPass,
    PublishableReviewArtifact,
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
from zeroone_ops.services.review.change_request_selector import build_review_revision_key
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.shared.state_store import StateStore

LOGGER = logging.getLogger(__name__)


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
        merge_request: ChangeRequestReviewCandidate,
        artifact: PublishableReviewArtifact,
        note_id: int | None,
        note_url: str | None,
        dry_run: bool,
    ) -> RunSummary:
        """Persist a reviewed change-request revision and return the summary."""
        record.status = RunStatus.REVIEWED
        record.updated_at = utc_now()
        if not dry_run:
            dedup_key = build_review_revision_key(
                change_request_number=merge_request.change_request_number,
                head_sha=merge_request.head_sha,
            )
            self.state.reviews[dedup_key] = ChangeRequestReviewState(
                change_request_number=merge_request.change_request_number,
                head_sha=merge_request.head_sha,
                status=artifact.classification,
                last_run_id=record.run_id,
                findings_count=len(artifact.findings),
                summary=artifact.summary,
                follow_up_lines=list(artifact.follow_up_lines),
                findings=_build_prior_review_findings_from_artifact(artifact),
                note_id=note_id,
                note_url=note_url,
            )
            self._trim_prior_reviews_for_change_request(merge_request.change_request_number)
        self.state_store.save(self.state)
        summary_clause = _review_classification_summary(artifact)
        base_message = (
            f"Reviewed change request !{merge_request.change_request_number} "
            f"at {merge_request.head_sha}. "
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

    def mark_same_sha_reused(
        self,
        *,
        record: RunRecord,
        merge_request: ChangeRequestReviewCandidate,
        prior_classification: str | None,
    ) -> RunSummary:
        """Persist an operational same-SHA reuse outcome and return the summary."""
        record.status = RunStatus.REVIEWED
        record.updated_at = utc_now()
        self.state_store.save(self.state)
        message = (
            f"Reviewed change request !{merge_request.change_request_number} "
            f"at {merge_request.head_sha}. "
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

    def _trim_prior_reviews_for_change_request(self, change_request_number: int) -> None:
        """Keep only the most recent bounded review passes for one change request."""
        if self.max_prior_review_passes <= 0:
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
        if len(matching_reviews) <= self.max_prior_review_passes:
            return

        matching_reviews.sort(
            key=lambda pair: (pair[1].updated_at, pair[1].head_sha),
            reverse=True,
        )
        for key, _value in matching_reviews[self.max_prior_review_passes :]:
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

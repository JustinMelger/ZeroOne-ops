"""Review state orchestration service."""

from __future__ import annotations

import logging

from ai_sonar_bot.models.review import (
    MergeRequestReviewCandidate,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    ReviewResult,
)
from ai_sonar_bot.models.state import (
    AppState,
    FailureDetails,
    MergeRequestReviewState,
    PriorReviewFindingState,
    RunRecord,
    RunStatus,
    utc_now,
)
from ai_sonar_bot.services.mr_selector import build_review_revision_key
from ai_sonar_bot.services.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)
from ai_sonar_bot.services.run_state_service import RunSummary
from ai_sonar_bot.services.state_store import StateStore

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
        merge_request: MergeRequestReviewCandidate,
        review_result: ReviewResult,
        note_url: str | None,
        dry_run: bool,
    ) -> RunSummary:
        """Persist a reviewed merge request revision and return the summary."""
        record.status = RunStatus.REVIEWED
        record.updated_at = utc_now()
        if not dry_run:
            dedup_key = build_review_revision_key(
                mr_iid=merge_request.iid,
                head_sha=merge_request.head_sha,
            )
            self.state.reviews[dedup_key] = MergeRequestReviewState(
                mr_iid=merge_request.iid,
                head_sha=merge_request.head_sha,
                status=review_result.classification,
                last_run_id=record.run_id,
                findings_count=len(review_result.findings),
                summary=review_result.summary,
                findings=_build_prior_review_findings(review_result),
                note_url=note_url,
            )
            self._trim_prior_reviews_for_merge_request(merge_request.iid)
        self.state_store.save(self.state)
        summary_clause = _review_classification_summary(review_result)
        base_message = (
            f"Reviewed merge request !{merge_request.iid} at {merge_request.head_sha}. "
            f"Classification: {review_result.classification}. {summary_clause}"
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

    def _trim_prior_reviews_for_merge_request(self, mr_iid: int) -> None:
        """Keep only the most recent bounded review passes for one MR."""
        if self.max_prior_review_passes <= 0:
            review_keys_to_remove = [
                key for key, value in self.state.reviews.items() if value.mr_iid == mr_iid
            ]
            for key in review_keys_to_remove:
                self.state.reviews.pop(key, None)
            return

        matching_reviews = [
            (key, value) for key, value in self.state.reviews.items() if value.mr_iid == mr_iid
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
        mr_iid: int,
        current_head_sha: str,
    ) -> PriorReviewContext | None:
        """Return bounded persisted prior review context for one MR."""
        matching_reviews = [
            review_state
            for review_state in self.state.reviews.values()
            if review_state.mr_iid == mr_iid and review_state.head_sha != current_head_sha
        ]
        if not matching_reviews:
            return None
        matching_reviews.sort(
            key=lambda review_state: (review_state.updated_at, review_state.head_sha),
            reverse=True,
        )
        return PriorReviewContext(
            merge_request_iid=mr_iid,
            passes=[
                PriorReviewPass(
                    reviewed_head_sha=review_state.head_sha,
                    classification=review_state.status,
                    findings_count=review_state.findings_count,
                    summary=review_state.summary,
                    note_url=review_state.note_url,
                    findings=[
                        PriorReviewFinding(
                            identity=finding.identity,
                            legacy_identity=finding.legacy_identity,
                            summary=finding.summary,
                            severity=finding.severity,
                            symbol=finding.symbol,
                            issue_kind=finding.issue_kind,
                            region_hint=finding.region_hint,
                        )
                        for finding in review_state.findings
                    ],
                )
                for review_state in matching_reviews[: self.max_prior_review_passes]
            ],
        )


def _build_prior_review_findings(
    review_result: ReviewResult,
) -> list[PriorReviewFindingState]:
    """Normalize bounded persisted prior-review finding summaries."""
    normalized_findings: list[PriorReviewFindingState] = []
    for finding in review_result.findings:
        normalized_findings.append(
            PriorReviewFindingState(
                identity=build_review_finding_identity(finding),
                legacy_identity=build_legacy_review_finding_identity(finding),
                summary=f"{finding.file_path}: {finding.title}",
                severity=finding.severity,
                symbol=finding.symbol,
                issue_kind=finding.issue_kind,
                region_hint=finding.region_hint,
            )
        )
    return normalized_findings


def _review_classification_summary(review_result: ReviewResult) -> str:
    """Return one operator-facing review outcome summary."""
    if review_result.classification == "manual_review_only":
        return (
            "Bot assessment was insufficient for a trustworthy review decision. "
            f"{review_result.summary}"
        )
    return review_result.summary

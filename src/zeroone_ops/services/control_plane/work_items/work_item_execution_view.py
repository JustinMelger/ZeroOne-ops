"""Recognize current execution evidence for display, without changing workflow state."""

from zeroone_ops.models.batch_execution import BatchAnalysisRejectionView
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.remediation.batch_analysis_rejection_presentation import (
    build_batch_analysis_rejection_view,
)


def has_current_revision_failure(work_item: WorkItemState) -> bool:
    """Preserve existing SHA and command-time correlation for the failed-revision notice."""
    failure, revision, review = (
        work_item.execution_failure,
        work_item.last_revision_command,
        work_item.projected_review,
    )
    return (
        work_item.status == "review_feedback_required"
        and failure is not None
        and revision is not None
        and review is not None
        and revision.reviewed_sha == review.reviewed_sha
        and failure.occurred_at.tzinfo is not None
        and revision.occurred_at.tzinfo is not None
        and failure.occurred_at >= revision.occurred_at
    )


def current_batch_rejection_view(work_item: WorkItemState) -> BatchAnalysisRejectionView | None:
    """Show a pre-edit rejection only while its blocked or correlated revision state is current."""
    failure = work_item.execution_failure
    if (
        work_item.batch is None
        or failure is None
        or failure.stage != "analysis"
        or failure.batch_rejection is None
        or not (work_item.status == "blocked" or has_current_revision_failure(work_item))
    ):
        return None
    return build_batch_analysis_rejection_view(
        failure.batch_rejection,
        attempt=work_item.batch_attempt,
        file_path=work_item.batch.group.file_path,
        rule_id=work_item.batch.group.rule_id,
    )

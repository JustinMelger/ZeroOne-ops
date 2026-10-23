"""Adapters into the shared remediation execution contract."""

from __future__ import annotations

from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import WorkItemState


def control_plane_work_item_to_execution_target(
    work_item: WorkItemState,
    *,
    work_item_url: str | None = None,
) -> RemediationExecutionTarget:
    """Adapt one authoritative work item into the shared execution target shape."""
    if work_item.file_path is None:
        raise ValueError("Work item is missing a target file path.")
    requirements = (
        work_item.batch_attempt.members[0].remediation_context
        if work_item.batch is not None and work_item.batch_attempt is not None
        else work_item.remediation_context
    )
    review_feedback = None
    revision_branch = None
    reviewed_sha = None
    if work_item.status == "review_revision_queued" and work_item.projected_review is not None:
        feedback = work_item.projected_review.feedback
        if feedback is not None:
            review_feedback = feedback
        reviewed_sha = work_item.projected_review.reviewed_sha
    return RemediationExecutionTarget(
        item_id=work_item.work_item_id,
        source_type=work_item.source.source,
        source_ref=work_item.source.source_item_key,
        work_item_url=work_item_url,
        title=work_item.summary,
        status=work_item.status,
        message=work_item.detail or work_item.summary,
        file_path=work_item.file_path,
        line=work_item.line,
        rule_id=requirements.diagnostic_code,
        severity=work_item.severity,
        remediation_category=requirements.category,
        validation_commands=list(requirements.validation_commands),
        expected_change=requirements.expected_change,
        constraints=requirements.constraints,
        acceptance_criteria=list(requirements.acceptance_criteria),
        review_feedback=review_feedback,
        revision_branch=revision_branch,
        reviewed_sha=reviewed_sha,
        batch=work_item.batch,
        batch_attempt=work_item.batch_attempt,
    )

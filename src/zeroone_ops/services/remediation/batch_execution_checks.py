"""Pure complete-context and analysis-accounting checks for batch execution."""

from zeroone_ops.models.analysis import BatchIssueAnalysis, IssueAnalysis, IssueContext
from zeroone_ops.models.batch_execution import (
    BatchAnalysisRejection,
    BatchAnalysisRejectionReason,
    BatchAttemptEvidence,
    BatchRejectedMember,
)
from zeroone_ops.models.remediation import RemediationExecutionTarget


class BatchAnalysisRejected(ValueError):
    """Carry bounded rejection evidence without authorizing an edit."""

    def __init__(self, rejection: BatchAnalysisRejection) -> None:
        """Retain the display-only evidence for blocked execution projection."""
        super().__init__("Batch analysis cannot safely address the complete scope.")
        self.rejection = rejection


def has_complete_batch_context(target: RemediationExecutionTarget, context: IssueContext) -> bool:
    """Require frozen scope and a single excerpt covering every targeted location."""
    batch, attempt = target.batch, target.batch_attempt
    if (
        batch is None
        or attempt is None
        or context.batch_attempt != attempt
        or context.batch != batch
    ):
        return False
    if attempt.batch_id != target.item_id or batch.group.file_path != target.file_path:
        return False
    originals = {member.finding_id for member in batch.members}
    for member in attempt.members:
        if (
            member.finding_id not in originals
            or member.repository_path != target.file_path
            or member.source_id != batch.group.source_id
            or member.remediation_context.diagnostic_code != batch.group.rule_id
        ):
            return False
        if member.line_start is None:
            if not context.full_file_included:
                return False
        elif not (target.revision_branch is not None and context.full_file_included) and (
            member.line_start < context.snippet.start_line
            or (member.line_end or member.line_start) > context.snippet.end_line
        ):
            return False
    return context.file_path == target.file_path


def accept_batch_analysis(
    attempt: BatchAttemptEvidence | None, analysis: IssueAnalysis
) -> BatchAttemptEvidence:
    """Validate a complete addressability claim's shape, never its correctness."""
    if (
        attempt is None
        or not isinstance(analysis, BatchIssueAnalysis)
        or analysis.batch_coverage is None
    ):
        raise BatchAnalysisRejected(_batch_rejection(attempt, analysis, "missing_coverage"))

    try:
        accepted = BatchAttemptEvidence.model_validate(
            attempt.model_dump() | {"coverage": analysis.batch_coverage}
        )
    except ValueError as error:
        raise BatchAnalysisRejected(
            _batch_rejection(attempt, analysis, "invalid_coverage")
        ) from error

    if analysis.batch_coverage.unaddressable:
        raise BatchAnalysisRejected(_batch_rejection(attempt, analysis, "unaddressable_members"))
    if analysis.classification.value == "manual":
        raise BatchAnalysisRejected(_batch_rejection(attempt, analysis, "manual_classification"))
    return accepted


def _batch_rejection(
    attempt: BatchAttemptEvidence | None,
    analysis: IssueAnalysis,
    reason: BatchAnalysisRejectionReason,
) -> BatchAnalysisRejection:
    """Record targeted references only; malformed model IDs never acquire authority."""
    explanations = (
        {member.finding_id: member.reason for member in analysis.batch_coverage.unaddressable}
        if reason == "unaddressable_members"
        and isinstance(analysis, BatchIssueAnalysis)
        and analysis.batch_coverage is not None
        else {}
    )
    members = (
        [
            member
            for member in attempt.members
            if not explanations or member.finding_id in explanations
        ]
        if attempt is not None
        else []
    )
    fallback = (
        analysis.summary.strip() or analysis.proposed_strategy.strip() or "Manual work required."
        if reason == "manual_classification"
        else "Analysis must provide valid, complete accounting for the targeted members."
    )
    return BatchAnalysisRejection(
        reason=reason,
        members=tuple(
            BatchRejectedMember(
                finding_reference=_bounded_reference(member.finding_id, 300),
                reason=_bounded_reference(explanations.get(member.finding_id, fallback), 600),
            )
            for member in members[:10]
        ),
        omitted_member_count=max(0, len(members) - 10),
    )


def _bounded_reference(value: str, limit: int) -> str:
    """Keep display evidence bounded without pretending truncated references are identities."""
    return value if len(value) <= limit else value[: limit - 3] + "..."

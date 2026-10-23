"""Provider-neutral remediation context builder."""

from __future__ import annotations

from pathlib import Path

from zeroone_ops.models.analysis import (
    IssueContext,
    PriorReviewFeedback,
    PriorReviewFeedbackFinding,
)
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.services.shared.context_builder import build_issue_context
from zeroone_ops.services.shared.repository_guidance import load_repository_guidance


class RemediationContextBuilder:
    """Build repository context for a normalized remediation work item."""

    def __init__(self, repo_root: Path, config: AppConfig) -> None:
        """Initialize the remediation context builder."""
        self.repo_root = repo_root
        self.config = config

    def build(self, work_item: RemediationExecutionTarget) -> IssueContext | None:
        """Build source context for one remediation work item."""
        if work_item.batch is not None and work_item.batch_attempt is None:
            return None
        attempt = work_item.batch_attempt
        context = build_issue_context(
            repo_root=self.repo_root,
            config=self.config,
            issue_key=work_item.source_ref,
            file_path=work_item.file_path,
            issue_line=work_item.line,
            required_locations=(
                tuple((member.line_start, member.line_end) for member in attempt.members)
                if attempt is not None
                else None
            ),
            allow_historical_locations=work_item.revision_branch is not None,
        )
        if context is None:
            return None
        context = context.model_copy(
            update={
                "repository_guidance": load_repository_guidance(
                    self.repo_root,
                    configured_paths=self.config.repository_guidance_paths,
                ),
                "batch_attempt": attempt,
                "batch": work_item.batch,
            }
        )
        prior_review_feedback = _build_prior_review_feedback(work_item)
        if prior_review_feedback is None:
            return context
        return context.model_copy(update={"prior_review_feedback": prior_review_feedback})


def _build_prior_review_feedback(
    work_item: RemediationExecutionTarget,
) -> PriorReviewFeedback | None:
    """Return typed projected feedback for a verified same-request revision."""
    feedback = work_item.review_feedback
    if feedback is None:
        return None
    return PriorReviewFeedback(
        review_status="findings_present",
        review_findings_count=feedback.finding_count,
        review_feedback_summary=feedback.summary,
        reviewed_head_sha=work_item.reviewed_sha,
        findings=[
            PriorReviewFeedbackFinding(**finding.model_dump()) for finding in feedback.findings
        ],
    )

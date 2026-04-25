"""Provider-neutral remediation context builder."""

from __future__ import annotations

from pathlib import Path

from ai_sonar_bot.models.analysis import IssueContext, PriorReviewFeedback
from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.remediation import RemediationWorkItem
from ai_sonar_bot.services.shared.context_builder import build_issue_context


class RemediationContextBuilder:
    """Build repository context for a normalized remediation work item."""

    def __init__(self, repo_root: Path, config: AppConfig) -> None:
        """Initialize the remediation context builder."""
        self.repo_root = repo_root
        self.config = config

    def build(self, work_item: RemediationWorkItem) -> IssueContext | None:
        """Build source context for one remediation work item."""
        context = build_issue_context(
            repo_root=self.repo_root,
            config=self.config,
            issue_key=work_item.source_ref,
            file_path=work_item.file_path,
            issue_line=work_item.line,
        )
        if context is None:
            return None
        prior_review_feedback = _build_prior_review_feedback(work_item)
        if prior_review_feedback is None:
            return context
        return context.model_copy(update={"prior_review_feedback": prior_review_feedback})


def _build_prior_review_feedback(work_item: RemediationWorkItem) -> PriorReviewFeedback | None:
    """Return bounded prior review feedback for retry-eligible work items."""
    payload = work_item.source_payload
    if payload.get("retry_eligible") is not True:
        return None
    review_status = payload.get("review_status")
    if not isinstance(review_status, str) or not review_status:
        return None
    return PriorReviewFeedback(
        review_status=review_status,
        review_findings_count=_as_int(payload.get("review_findings_count")),
        review_feedback_summary=_as_str(payload.get("review_feedback_summary")),
        review_confidence=_as_float(payload.get("review_confidence")),
        review_confidence_reason=_as_str(payload.get("review_confidence_reason")),
        reviewed_head_sha=_as_str(payload.get("reviewed_head_sha")),
        retry_count=_as_int(payload.get("retry_count")),
    )


def _as_str(value: object) -> str | None:
    """Normalize one optional string field from source payload."""
    return value if isinstance(value, str) and value else None


def _as_int(value: object) -> int | None:
    """Normalize one optional integer field from source payload."""
    return value if isinstance(value, int) else None


def _as_float(value: object) -> float | None:
    """Normalize one optional float field from source payload."""
    if isinstance(value, (int, float)):
        return float(value)
    return None

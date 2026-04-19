"""Prompt rendering helpers for LLM-backed workflows."""

from __future__ import annotations

from functools import cache
from importlib import resources

from ai_sonar_bot.models.analysis import IssueContext
from ai_sonar_bot.models.remediation import (
    RemediationExecutionTarget,
    remediation_profile_for,
)
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    OverlapCandidate,
    OverlapPacket,
    PriorReviewFinding,
    RemediationReviewContext,
    ReviewFileContext,
    ReviewFinding,
)


class LLMPromptError(RuntimeError):
    """Raised when an LLM prompt cannot be loaded or rendered."""


_PROMPT_TEMPLATE_NAMES = frozenset(
    {
        "analyze_issue.txt",
        "generate_structured_edit.txt",
        "review_merge_request.txt",
        "review_overlap_reconciliation.txt",
    }
)


def build_analysis_prompt(issue: RemediationExecutionTarget, context: IssueContext) -> str:
    """Build the analysis prompt for one remediation target."""
    profile = remediation_profile_for(issue)
    return render_prompt_template(
        "analyze_issue.txt",
        target_display_name=profile.target_display_name,
        source_display_name=profile.source_display_name,
        item_reference_label=profile.item_reference_label,
        issue_key=issue.source_ref,
        rule=issue.rule_id or "unknown",
        severity=issue.severity,
        issue_type=issue.issue_type or issue.source_type,
        message=issue.message,
        file_path=context.file_path,
        issue_line=context.line,
        constraints=issue.constraints or "(none)",
        snippet_start_line=context.snippet.start_line,
        snippet_end_line=context.snippet.end_line,
        full_file_included=context.full_file_included,
        context_truncated=context.truncated,
        prior_review_feedback=_format_prior_review_feedback(context),
        code_snippet=context.snippet.content,
    )


def build_structured_edit_prompt(
    issue: RemediationExecutionTarget,
    context: IssueContext,
) -> str:
    """Build the structured-edit prompt for one remediation target."""
    profile = remediation_profile_for(issue)
    return render_prompt_template(
        "generate_structured_edit.txt",
        target_display_name=profile.target_display_name,
        source_display_name=profile.source_display_name,
        item_reference_label=profile.item_reference_label,
        issue_key=issue.source_ref,
        rule=issue.rule_id or "unknown",
        severity=issue.severity,
        issue_type=issue.issue_type or issue.source_type,
        message=issue.message,
        file_path=context.file_path,
        issue_line=context.line,
        constraints=issue.constraints or "(none)",
        snippet_start_line=context.snippet.start_line,
        snippet_end_line=context.snippet.end_line,
        prior_review_feedback=_format_prior_review_feedback(context),
        code_snippet=context.snippet.content,
    )


def _format_prior_review_feedback(context: IssueContext) -> str:
    """Render bounded prior review feedback for retry-aware remediation prompts."""
    if context.prior_review_feedback is None:
        return "(none)"
    feedback = context.prior_review_feedback
    return "\n".join(
        [
            f"Review status: {feedback.review_status}",
            "Findings count: "
            + (
                str(feedback.review_findings_count)
                if feedback.review_findings_count is not None
                else "(none)"
            ),
            f"Reviewed SHA: {feedback.reviewed_head_sha or '(none)'}",
            "Retry count already consumed: "
            + (str(feedback.retry_count) if feedback.retry_count is not None else "0"),
            f"Feedback summary: {feedback.review_feedback_summary or '(none)'}",
            "Review confidence: "
            + (
                str(feedback.review_confidence)
                if feedback.review_confidence is not None
                else "(none)"
            ),
            f"Review confidence reason: {feedback.review_confidence_reason or '(none)'}",
        ]
    )


def build_review_prompt(context: MergeRequestReviewContext) -> str:
    """Build the review prompt for one merge request."""
    changed_files = "\n\n".join(
        _format_changed_file_context(changed_file) for changed_file in context.changed_files
    )
    return render_prompt_template(
        "review_merge_request.txt",
        mr_iid=context.mr_iid,
        title=context.title,
        description=_format_untrusted_block(
            label="Merge request description",
            content=context.description or "(none)",
        ),
        source_branch=context.source_branch,
        target_branch=context.target_branch,
        head_sha=context.head_sha,
        remediation_context=_format_remediation_review_context(context.remediation_context),
        repository_guidance=_format_repository_guidance(context),
        changed_files=changed_files,
    )


def build_review_overlap_prompt(packet: OverlapPacket) -> str:
    """Build the bounded overlap reconciliation prompt for one MR run."""
    current_findings = (
        "\n".join(
            _format_current_overlap_finding(index, finding)
            for index, finding in enumerate(packet.current_findings, start=1)
        )
        if packet.current_findings
        else "- (none)"
    )
    prior_findings = (
        "\n".join(
            _format_prior_overlap_finding(index, finding)
            for index, finding in enumerate(packet.prior_findings, start=1)
        )
        if packet.prior_findings
        else "- (none)"
    )
    overlap_candidates = (
        "\n".join(_format_overlap_candidate(candidate) for candidate in packet.candidates)
        if packet.candidates
        else "- (none)"
    )
    return render_prompt_template(
        "review_overlap_reconciliation.txt",
        mr_iid=packet.merge_request_iid,
        current_head_sha=packet.current_head_sha,
        prior_head_sha=packet.prior_head_sha,
        current_findings=_format_untrusted_block(
            label="Current findings",
            content=current_findings,
        ),
        prior_findings=_format_untrusted_block(
            label="Prior findings",
            content=prior_findings,
        ),
        overlap_candidates=_format_untrusted_block(
            label="Overlap candidates",
            content=overlap_candidates,
        ),
    )


def _format_current_overlap_finding(index: int, finding: ReviewFinding) -> str:
    """Render one current finding for the overlap prompt."""
    structured_parts = [
        f"symbol={finding.symbol}" if finding.symbol else None,
        f"issue_kind={finding.issue_kind}" if finding.issue_kind else None,
        f"region_hint={finding.region_hint}" if finding.region_hint else None,
    ]
    visible_structured_parts = [part for part in structured_parts if part is not None]
    suffix = f" [{', '.join(visible_structured_parts)}]" if visible_structured_parts else ""
    return f"- current[{index}] {finding.file_path}: {finding.title}{suffix}"


def _format_prior_overlap_finding(index: int, finding: PriorReviewFinding) -> str:
    """Render one prior finding for the overlap prompt."""
    structured_parts = [
        f"symbol={finding.symbol}" if finding.symbol else None,
        f"issue_kind={finding.issue_kind}" if finding.issue_kind else None,
        f"region_hint={finding.region_hint}" if finding.region_hint else None,
    ]
    visible_structured_parts = [part for part in structured_parts if part is not None]
    suffix = f" [{', '.join(visible_structured_parts)}]" if visible_structured_parts else ""
    return f"- prior[{index}] {finding.summary}{suffix}"


def _format_overlap_candidate(candidate: OverlapCandidate) -> str:
    """Render one bounded overlap candidate pair."""
    return (
        f"- current[{candidate.current_finding_index + 1}] <-> "
        f"prior[{candidate.prior_finding_index + 1}] "
        f"reasons={', '.join(candidate.reasons) if candidate.reasons else '(none)'}"
    )


def _format_changed_file_context(changed_file: ReviewFileContext) -> str:
    """Render one changed file plus any supporting helper context."""
    content_parts = [
        f"Diff:\n{changed_file.diff or '(diff unavailable)'}",
        (
            f"Context lines {changed_file.start_line}-"
            f"{changed_file.end_line}:\n{changed_file.content}"
        ),
    ]
    if changed_file.helper_context:
        helper_blocks = "\n\n".join(
            _format_untrusted_block(
                label=f"Supporting helper: {helper.symbol}",
                content="\n".join(
                    [
                        f"File: {helper.file_path}",
                        f"Lines: {helper.start_line}-{helper.end_line}",
                        f"Code:\n{helper.content}",
                    ]
                ),
            )
            for helper in changed_file.helper_context
        )
        content_parts.append(f"Supporting helper context:\n{helper_blocks}")

    return _format_untrusted_block(
        label=f"Changed file: {changed_file.file_path}",
        content="\n".join(content_parts),
    )


def _format_remediation_review_context(
    context: RemediationReviewContext | None,
) -> str:
    """Render remediation-authored MR context for the review prompt."""
    if context is None:
        return "(none)"

    item_reference = (
        f"{context.item_reference_label or 'Item reference'}: {context.item_reference}"
        if context.item_reference
        else "Item reference: (none)"
    )
    return _format_untrusted_block(
        label="Remediation-authored context",
        content="\n".join(
            [
                f"Summary: {context.summary or '(none)'}",
                f"Source: {context.source or '(none)'}",
                item_reference,
                f"Rule: {context.rule_id or '(none)'}",
                f"Severity: {context.severity or '(none)'}",
                f"Type: {context.remediation_type or '(none)'}",
                f"File: {context.file_path or '(none)'}",
                f"Line: {context.line if context.line is not None else '(none)'}",
                f"Message: {context.message or '(none)'}",
                f"Validation: {context.validation_summary or '(none)'}",
                f"Notes: {context.notes or '(none)'}",
            ]
        ),
    )


def _format_repository_guidance(context: MergeRequestReviewContext) -> str:
    """Render bounded repository guidance for the review prompt."""
    if not context.repository_guidance:
        return "(none)"
    return "\n\n".join(
        "\n".join(
            [
                f"<<BEGIN REPOSITORY GUIDANCE {guidance.file_path}>>",
                guidance.summary,
                f"<<END REPOSITORY GUIDANCE {guidance.file_path}>>",
            ]
        )
        for guidance in context.repository_guidance
    )




def _format_prior_review_finding(finding: PriorReviewFinding) -> str:
    """Render one prior-review finding with optional structured continuity fields."""
    parts = [f"- {finding.summary} ({finding.severity or 'unknown'})"]
    structured_candidates = [
        f"symbol={finding.symbol}" if finding.symbol else None,
        f"issue_kind={finding.issue_kind}" if finding.issue_kind else None,
        f"region_hint={finding.region_hint}" if finding.region_hint else None,
    ]
    structured_parts = [part for part in structured_candidates if part is not None]
    if structured_parts:
        parts.append(f"[{', '.join(structured_parts)}]")
    return " ".join(parts)


def _format_untrusted_block(*, label: str, content: str) -> str:
    """Render one explicitly untrusted prompt block."""
    return "\n".join(
        [
            f"<<BEGIN UNTRUSTED {label}>>",
            content,
            f"<<END UNTRUSTED {label}>>",
        ]
    )


def render_prompt_template(name: str, **values: object) -> str:
    """Load and render one prompt template safely."""
    template = load_prompt_template(name)
    try:
        return template.format(**values)
    except KeyError as error:
        missing_key = error.args[0]
        raise LLMPromptError(
            f"Prompt template could not be rendered because `{missing_key}` is missing: {name}"
        ) from error
    except ValueError as error:
        raise LLMPromptError(
            f"Prompt template is invalid and could not be rendered: {name}"
        ) from error


@cache
def load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    if name not in _PROMPT_TEMPLATE_NAMES:
        raise LLMPromptError(f"Unsupported prompt template requested: {name}")
    try:
        prompts_dir = resources.files("ai_sonar_bot").joinpath("prompts")
        return prompts_dir.joinpath(name).read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError) as error:
        raise LLMPromptError(f"Prompt template file could not be read: {name}") from error

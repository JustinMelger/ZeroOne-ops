"""Review publisher."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    PriorReviewFinding,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.providers.gitlab_client import GitLabClientError
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)

_MIN_SHARED_TITLE_TOKENS = 2
_MIN_TITLE_TOKEN_OVERLAP = 0.6


@dataclass(frozen=True)
class ReviewPublishResult:
    """Capture the outcome of publishing a review note."""

    note: MergeRequestNote | None
    body: str
    error_message: str | None = None


@dataclass(frozen=True)
class FollowUpFindingStatus:
    """Represent one bounded follow-up comparison outcome."""

    identity: str | None
    legacy_identity: str | None
    summary: str
    file_path: str | None
    symbol: str | None
    issue_kind: str | None
    region_hint: str | None
    status: str


@dataclass(frozen=True)
class FollowUpReviewReconciliation:
    """Represent a conservative comparison against the latest prior pass."""

    prior_reviewed_head_sha: str
    still_unresolved: list[FollowUpFindingStatus] = field(default_factory=list)
    appears_resolved: list[FollowUpFindingStatus] = field(default_factory=list)
    new_findings: list[FollowUpFindingStatus] = field(default_factory=list)
    unable_to_verify_resolution: bool = False


class ReviewPublisher:
    """Render and publish deterministic merge-request review notes."""

    def __init__(self, review_client: GitLabReviewClient) -> None:
        """Initialize the review publisher."""
        self.review_client = review_client

    def publish(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        context: MergeRequestReviewContext,
        review_result: ReviewResult,
    ) -> ReviewPublishResult:
        """Publish one deterministic review summary note."""
        body = self.render_note(context=context, review_result=review_result)
        try:
            note = self.review_client.create_merge_request_note(
                project_id=project_id,
                merge_request_iid=merge_request_iid,
                body=body,
            )
        except GitLabClientError as error:
            return ReviewPublishResult(
                note=None,
                body=body,
                error_message=f"Review note publish failed: {error}",
            )
        return ReviewPublishResult(note=note, body=body)

    def render_note(
        self,
        *,
        context: MergeRequestReviewContext,
        review_result: ReviewResult,
    ) -> str:
        """Render one deterministic review note body."""
        if review_result.classification == "no_findings":
            summary_line = (
                "No new actionable findings since the last reviewed SHA."
                if _is_follow_up_review(context)
                else "No actionable findings in this review pass."
            )
            return "\n".join(
                [
                    "Hi,",
                    "",
                    "Here are your review notes.",
                    "",
                    summary_line,
                    *_render_follow_up_lines(context, review_result),
                    *_render_confidence_lines(review_result),
                    "",
                    "Scope:",
                    f"- Reviewed merge request: `!{context.mr_iid}`",
                    f"- Reviewed commit SHA: `{context.head_sha}`",
                    f"- Files reviewed: {len(context.changed_files)}",
                ]
            )
        if review_result.classification == "manual_review_only":
            return "\n".join(
                [
                    "Hi,",
                    "",
                    "Here are your review notes.",
                    "",
                    "Bot assessment was insufficient for a trustworthy review decision.",
                    *_render_follow_up_lines(context, review_result),
                    "",
                    review_result.summary,
                    *_render_confidence_lines(review_result),
                    "",
                    "What this means:",
                    (
                        "- The bot could not assess this merge request reliably "
                        "with the available context."
                    ),
                    "- This is not an actionable finding by itself.",
                    "- Human review is still needed to decide whether the change is safe.",
                    "",
                    "Scope:",
                    f"- Reviewed merge request: `!{context.mr_iid}`",
                    f"- Reviewed commit SHA: `{context.head_sha}`",
                    f"- Files reviewed: {len(context.changed_files)}",
                ]
            )

        finding_lines = ["Findings:"]
        for index, finding in enumerate(review_result.findings, start=1):
            finding_lines.extend(
                [
                    f"{index}. [{finding.severity}] {finding.title} (`{finding.file_path}`)",
                    f"   Evidence: {finding.evidence}",
                    f"   {finding.explanation}",
                    f"   Follow-up: {finding.suggested_follow_up}",
                ]
            )

        return "\n".join(
            [
                "Hi,",
                "",
                "Here are your review notes.",
                "",
                *_render_follow_up_lines(context, review_result),
                review_result.summary,
                *_render_confidence_lines(review_result),
                "",
                *finding_lines,
                "",
                "Scope:",
                f"- Reviewed merge request: `!{context.mr_iid}`",
                f"- Reviewed commit SHA: `{context.head_sha}`",
                f"- Files reviewed: {len(context.changed_files)}",
            ]
        )


def _render_confidence_lines(review_result: ReviewResult) -> list[str]:
    """Render advisory confidence lines when present."""
    if review_result.review_confidence is None:
        return []
    lines = [
        "",
        "Confidence:",
        f"- Review confidence: {review_result.review_confidence:.2f}",
    ]
    if review_result.review_confidence_reason:
        lines.append(f"- Reason: {review_result.review_confidence_reason}")
    return lines


def _render_follow_up_lines(
    context: MergeRequestReviewContext,
    review_result: ReviewResult,
) -> list[str]:
    """Render light follow-up framing for repeated reviews on the same MR."""
    reconciliation = _reconcile_follow_up_review(
        context=context,
        review_result=review_result,
    )
    if reconciliation is None:
        return []
    lines = [
        (
            f"Follow-up review after the earlier bot pass on "
            f"`{reconciliation.prior_reviewed_head_sha}`."
        )
    ]
    lines.extend(_render_reconciliation_summary_lines(reconciliation, review_result))
    return [*lines, ""]


def _is_follow_up_review(context: MergeRequestReviewContext) -> bool:
    """Return whether the current review has bounded prior review context."""
    return bool(context.prior_review_context and context.prior_review_context.passes)


def _reconcile_follow_up_review(
    *,
    context: MergeRequestReviewContext,
    review_result: ReviewResult,
) -> FollowUpReviewReconciliation | None:
    """Compare the current review result to the latest prior pass only."""
    prior_review_context = context.prior_review_context
    if not prior_review_context or not prior_review_context.passes:
        return None

    latest_prior_pass = prior_review_context.passes[0]
    unparsed_prior_finding_count = 0
    prior_findings: list[FollowUpFindingStatus] = []
    for prior_finding in latest_prior_pass.findings:
        follow_up_finding = _to_follow_up_finding_status(prior_finding)
        if follow_up_finding is not None:
            prior_findings.append(follow_up_finding)
    unparsed_prior_finding_count = len(latest_prior_pass.findings) - len(prior_findings)

    still_unresolved: list[FollowUpFindingStatus] = []
    new_findings: list[FollowUpFindingStatus] = []

    for current_finding in review_result.findings:
        finding_summary = f"{current_finding.file_path}: {current_finding.title}"
        finding_key = _current_finding_key(current_finding)
        finding_status = FollowUpFindingStatus(
            identity=_current_finding_identity(current_finding),
            legacy_identity=build_legacy_review_finding_identity(current_finding),
            summary=finding_summary,
            file_path=current_finding.file_path,
            symbol=current_finding.symbol,
            issue_kind=current_finding.issue_kind,
            region_hint=current_finding.region_hint,
            status="new",
        )
        # Prefer exact machine identity for new persisted entries. Only fall back
        # to legacy summary/title matching when older review state has no identity.
        matched_prior_finding = _match_prior_finding(
            current_finding=current_finding,
            current_identity=_current_finding_identity(current_finding),
            current_legacy_identity=build_legacy_review_finding_identity(current_finding),
            current_key=finding_key,
            prior_findings=prior_findings,
        )
        if matched_prior_finding is not None:
            still_unresolved.append(
                FollowUpFindingStatus(
                    identity=matched_prior_finding.identity,
                    legacy_identity=matched_prior_finding.legacy_identity,
                    summary=matched_prior_finding.summary,
                    file_path=matched_prior_finding.file_path,
                    symbol=matched_prior_finding.symbol,
                    issue_kind=matched_prior_finding.issue_kind,
                    region_hint=matched_prior_finding.region_hint,
                    status="still_unresolved",
                )
            )
            prior_findings.remove(matched_prior_finding)
        else:
            new_findings.append(finding_status)

    appears_resolved = list(prior_findings)
    return FollowUpReviewReconciliation(
        prior_reviewed_head_sha=latest_prior_pass.reviewed_head_sha,
        still_unresolved=still_unresolved,
        appears_resolved=appears_resolved,
        new_findings=new_findings,
        unable_to_verify_resolution=(
            latest_prior_pass.classification == "findings_present"
            and unparsed_prior_finding_count > 0
            and not still_unresolved
        ),
    )


def _current_finding_key(finding: ReviewFinding) -> tuple[str, str, str]:
    """Build a conservative key for one current finding."""
    summary = f"{finding.file_path}: {finding.title}"
    return (
        finding.file_path.strip().lower(),
        finding.title.strip().lower(),
        _normalize_finding_text(summary),
    )


def _current_finding_identity(finding: ReviewFinding) -> str:
    """Build the canonical machine-facing identity for one current finding."""
    return build_review_finding_identity(finding)


def _prior_finding_key(summary: str) -> tuple[str, str, str] | None:
    """Build a conservative key for one persisted prior finding summary."""
    parsed = _split_prior_summary(summary)
    if parsed is None:
        return None
    file_path, title = parsed
    return (
        file_path.strip().lower(),
        title.strip().lower(),
        _normalize_finding_text(summary),
    )


def _prior_finding_path(summary: str) -> str | None:
    """Return the file path from a persisted prior finding summary when available."""
    parsed = _split_prior_summary(summary)
    if parsed is None:
        return None
    return parsed[0]


def _split_prior_summary(summary: str) -> tuple[str, str] | None:
    """Split a persisted prior summary like `path: title` conservatively."""
    if ":" not in summary:
        return None
    file_path, title = summary.split(":", 1)
    if not file_path.strip() or not title.strip():
        return None
    return file_path.strip(), title.strip()


def _normalize_finding_text(text: str) -> str:
    """Normalize bounded finding text for conservative exact matching."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _render_reconciliation_summary_lines(
    reconciliation: FollowUpReviewReconciliation,
    review_result: ReviewResult,
) -> list[str]:
    """Render concise conversational summary lines for repeated review passes."""
    lines: list[str] = []

    if review_result.classification == "no_findings" and reconciliation.unable_to_verify_resolution:
        lines.append(
            "The current pass could not verify conclusively whether the earlier "
            "concern is fully resolved."
        )
        return lines

    if review_result.classification == "no_findings" and reconciliation.appears_resolved:
        lines.append(
            "The earlier concern about "
            f"{_humanize_finding_summary(reconciliation.appears_resolved[0].summary)} "
            "no longer appears present."
        )
        return lines

    if review_result.classification == "findings_present" and reconciliation.still_unresolved:
        lines.append(
            "The earlier concern about "
            f"{_humanize_finding_summary(reconciliation.still_unresolved[0].summary)} "
            "still appears unresolved."
        )
        if reconciliation.appears_resolved and reconciliation.new_findings:
            lines.append(
                "The earlier concern about "
                f"{_humanize_finding_summary(reconciliation.appears_resolved[0].summary)} "
                "no longer appears present, but a new issue now appears around "
                f"{_humanize_finding_summary(reconciliation.new_findings[0].summary)}."
            )
        elif reconciliation.appears_resolved:
            lines.append(
                "The earlier concern about "
                f"{_humanize_finding_summary(reconciliation.appears_resolved[0].summary)} "
                "no longer appears present."
            )
        elif reconciliation.new_findings:
            lines.append(
                "A new issue in this pass appears around "
                f"{_humanize_finding_summary(reconciliation.new_findings[0].summary)}."
            )
        return lines

    if review_result.classification == "findings_present" and reconciliation.appears_resolved:
        if reconciliation.new_findings:
            lines.append(
                "The earlier concern about "
                f"{_humanize_finding_summary(reconciliation.appears_resolved[0].summary)} "
                "no longer appears present, but a new issue now appears around "
                f"{_humanize_finding_summary(reconciliation.new_findings[0].summary)}."
            )
        return lines

    if (
        review_result.classification == "findings_present"
        and reconciliation.unable_to_verify_resolution
    ):
        lines.append(
            "The current pass could not verify conclusively whether the earlier "
            "concern is fully resolved."
        )
        if reconciliation.new_findings:
            lines.append(
                "A new issue in this pass appears around "
                f"{_humanize_finding_summary(reconciliation.new_findings[0].summary)}."
            )
        return lines

    return lines


def _humanize_finding_summary(summary: str) -> str:
    """Return a short operator-facing phrase for a normalized finding summary."""
    parsed = _split_prior_summary(summary)
    if parsed is None:
        return f"`{summary}`"
    _, title = parsed
    return f"`{title}`"


def _match_prior_finding(
    *,
    current_finding: ReviewFinding,
    current_identity: str,
    current_legacy_identity: str,
    current_key: tuple[str, str, str],
    prior_findings: list[FollowUpFindingStatus],
) -> FollowUpFindingStatus | None:
    """Match one current finding to one prior finding conservatively."""
    identity_match = next(
        (
            prior_finding
            for prior_finding in prior_findings
            if prior_finding.identity is not None and prior_finding.identity == current_identity
        ),
        None,
    )
    if identity_match is not None:
        return identity_match

    legacy_identity_match = next(
        (
            prior_finding
            for prior_finding in prior_findings
            if current_legacy_identity
            in {
                prior_finding.identity,
                prior_finding.legacy_identity,
            }
        ),
        None,
    )
    if legacy_identity_match is not None:
        return legacy_identity_match

    exact_match = next(
        (
            prior_finding
            for prior_finding in prior_findings
            if prior_finding.legacy_identity is None
            and _prior_finding_key(prior_finding.summary) == current_key
        ),
        None,
    )
    if exact_match is not None:
        return exact_match

    current_path = current_finding.file_path.strip().lower()
    current_title = current_finding.title
    for prior_finding in prior_findings:
        if prior_finding.legacy_identity is not None:
            continue
        parsed_prior_summary = _split_prior_summary(prior_finding.summary)
        if parsed_prior_summary is None:
            continue
        prior_path, prior_title = parsed_prior_summary
        if prior_path.strip().lower() != current_path:
            continue
        if _titles_look_like_same_finding(current_title, prior_title):
            return prior_finding
    return None


def _titles_look_like_same_finding(current_title: str, prior_title: str) -> bool:
    """Return whether two titles likely describe the same finding in the same file."""
    current_tokens = _title_tokens(current_title)
    prior_tokens = _title_tokens(prior_title)
    if not current_tokens or not prior_tokens:
        return False

    shared_tokens = current_tokens & prior_tokens
    if len(shared_tokens) < _MIN_SHARED_TITLE_TOKENS:
        return False

    smaller_token_count = min(len(current_tokens), len(prior_tokens))
    return len(shared_tokens) / smaller_token_count >= _MIN_TITLE_TOKEN_OVERLAP


def _title_tokens(title: str) -> set[str]:
    """Extract lightly normalized title tokens for conservative fuzzy matching."""
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9_]+", title.lower()):
        normalized = _normalize_title_token(token)
        if len(normalized) >= 4:
            tokens.add(normalized)
    return tokens


def _normalize_title_token(token: str) -> str:
    """Lightly normalize title tokens so small wording drift still matches."""
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("ion") and len(token) > 5:
        return token[:-3]
    return token


def _to_follow_up_finding_status(finding: PriorReviewFinding) -> FollowUpFindingStatus | None:
    """Convert one prior finding into reconciliation state when it is parseable."""
    if finding.identity is not None:
        parsed_summary = _split_prior_summary(finding.summary)
        return FollowUpFindingStatus(
            identity=finding.identity,
            legacy_identity=finding.legacy_identity,
            summary=finding.summary,
            file_path=parsed_summary[0] if parsed_summary is not None else None,
            symbol=finding.symbol,
            issue_kind=finding.issue_kind,
            region_hint=finding.region_hint,
            status="appears_resolved",
        )
    if _prior_finding_key(finding.summary) is None:
        return None
    return FollowUpFindingStatus(
        identity=None,
        legacy_identity=finding.legacy_identity,
        summary=finding.summary,
        file_path=_prior_finding_path(finding.summary),
        symbol=finding.symbol,
        issue_kind=finding.issue_kind,
        region_hint=finding.region_hint,
        status="appears_resolved",
    )

"""Parse machine-safe provider review comments into prior review models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from zeroone_ops.models.review import (
    PriorReviewFinding,
    PriorReviewInlineComment,
    PriorReviewPass,
    ReviewComment,
    ReviewFinding,
)
from zeroone_ops.services.review.continuity.review_prior_comment_loader import (
    extract_machine_safe_review_note_payload,
)
from zeroone_ops.utils.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)

_VALID_CLASSIFICATIONS = frozenset({"no_findings", "findings_present", "manual_review_only"})
_VALID_SEVERITIES = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class PriorReviewNoteParseResult:
    """Capture one bounded prior-review note parse attempt."""

    prior_review_pass: PriorReviewPass | None
    message: str


class ChangeRequestPriorCommentParser:
    """Rebuild one prior review pass from one machine-safe provider comment."""

    def parse_note(
        self,
        *,
        note: ReviewComment,
        expected_change_request_number: int,
    ) -> PriorReviewNoteParseResult:
        """Parse one machine-safe review note into a bounded prior review pass."""
        payload = extract_machine_safe_review_note_payload(note.body)
        if payload is None:
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note does not contain a valid machine-safe review payload.",
            )

        reviewed_change_request_number = payload.get("reviewed_change_request_number")
        if reviewed_change_request_number != expected_change_request_number:
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note machine-safe payload targets a different change request.",
            )

        reviewed_head_sha = payload.get("reviewed_head_sha")
        classification = payload.get("classification")
        findings_count = payload.get("findings_count")
        summary = payload.get("summary")
        findings_payload = payload.get("findings")

        if not isinstance(reviewed_head_sha, str):
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note machine-safe payload is missing a valid reviewed head SHA.",
            )
        if classification not in _VALID_CLASSIFICATIONS:
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note machine-safe payload has an invalid classification.",
            )
        if not isinstance(findings_count, int):
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note machine-safe payload is missing a valid findings count.",
            )
        if summary is not None and not isinstance(summary, str):
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note machine-safe payload has an invalid summary.",
            )
        if not isinstance(findings_payload, list):
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note machine-safe payload has an invalid findings list.",
            )

        findings: list[PriorReviewFinding] = []
        for finding_payload in findings_payload:
            finding = _parse_prior_review_finding(finding_payload)
            if finding is None:
                return PriorReviewNoteParseResult(
                    prior_review_pass=None,
                    message="Selected note machine-safe payload has an invalid finding entry.",
                )
            findings.append(finding)

        if findings_count != len(findings):
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message=(
                    "Selected note machine-safe payload findings count does not match findings."
                ),
            )

        return PriorReviewNoteParseResult(
            prior_review_pass=PriorReviewPass(
                reviewed_head_sha=reviewed_head_sha,
                classification=cast(
                    Literal["no_findings", "findings_present", "manual_review_only"],
                    classification,
                ),
                findings_count=findings_count,
                summary=summary,
                note_id=note.id,
                note_url=note.web_url,
                findings=findings,
            ),
            message="Parsed machine-safe prior review note successfully.",
        )


def _parse_prior_review_finding(payload: object) -> PriorReviewFinding | None:
    """Parse one machine-safe finding payload into a prior-review finding."""
    if not isinstance(payload, dict):
        return None

    summary = payload.get("summary")
    severity = payload.get("severity")
    file_path = payload.get("file_path")
    line_start = payload.get("line_start")
    line_end = payload.get("line_end")
    title = payload.get("title")
    symbol = payload.get("symbol")
    issue_kind = payload.get("issue_kind")
    region_hint = payload.get("region_hint")
    identity = payload.get("identity")
    legacy_identity = payload.get("legacy_identity")
    inline_comment_payload = payload.get("inline_comment")

    if not isinstance(summary, str) or not isinstance(file_path, str) or not isinstance(title, str):
        return None
    if severity is not None and severity not in _VALID_SEVERITIES:
        return None
    if not _is_optional_int(line_start):
        return None
    if not _is_optional_int(line_end):
        return None
    if not _is_optional_string(symbol):
        return None
    if not _is_optional_string(issue_kind):
        return None
    if not _is_optional_string(region_hint):
        return None
    if not _is_optional_string(identity):
        return None
    if not _is_optional_string(legacy_identity):
        return None
    inline_comment = _parse_inline_comment(inline_comment_payload)
    if inline_comment_payload is not None and inline_comment is None:
        return None

    synthetic_finding = ReviewFinding(
        severity=_coerce_severity(severity),
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        symbol=symbol,
        issue_kind=issue_kind,
        region_hint=region_hint,
        title=title,
        evidence="machine-safe prior review payload",
        explanation="machine-safe prior review payload",
        suggested_follow_up="machine-safe prior review payload",
    )
    expected_identity = build_review_finding_identity(synthetic_finding)
    expected_legacy_identity = build_legacy_review_finding_identity(synthetic_finding)
    if identity is not None and identity != expected_identity:
        return None
    if legacy_identity is not None and legacy_identity != expected_legacy_identity:
        return None
    return PriorReviewFinding(
        identity=identity if identity is not None else expected_identity,
        legacy_identity=(
            legacy_identity if legacy_identity is not None else expected_legacy_identity
        ),
        summary=summary,
        severity=severity,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        title=title,
        symbol=symbol,
        issue_kind=issue_kind,
        region_hint=region_hint,
        inline_comment=inline_comment,
    )


def _coerce_severity(severity: str | None) -> Literal["high", "medium", "low"]:
    """Return one valid severity for identity reconstruction scaffolding."""
    if severity in _VALID_SEVERITIES:
        return cast(Literal["high", "medium", "low"], severity)
    return "medium"


def _is_optional_string(value: object) -> bool:
    """Return whether one optional payload field is either null or a string."""
    return value is None or isinstance(value, str)


def _is_optional_int(value: object) -> bool:
    """Return whether one optional payload field is either null or an integer."""
    return value is None or isinstance(value, int)


def _parse_inline_comment(payload: object) -> PriorReviewInlineComment | None:
    """Parse one inline-comment payload into bounded continuity metadata."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None

    comment_id = payload.get("comment_id")
    comment_url = payload.get("comment_url")
    status = payload.get("status")
    anchor_file_path = payload.get("anchor_file_path")
    anchor_line_start = payload.get("anchor_line_start")
    anchor_line_end = payload.get("anchor_line_end")

    if not isinstance(comment_id, str):
        return None
    if not _is_optional_string(comment_url):
        return None
    if status not in {"published", "shadow", "superseded"}:
        return None
    if not isinstance(anchor_file_path, str):
        return None
    if not _is_optional_int(anchor_line_start):
        return None
    if not _is_optional_int(anchor_line_end):
        return None

    return PriorReviewInlineComment(
        comment_id=comment_id,
        comment_url=cast(str | None, comment_url),
        status=cast(Literal["published", "shadow", "superseded"], status),
        anchor_file_path=anchor_file_path,
        anchor_line_start=cast(int | None, anchor_line_start),
        anchor_line_end=cast(int | None, anchor_line_end),
    )

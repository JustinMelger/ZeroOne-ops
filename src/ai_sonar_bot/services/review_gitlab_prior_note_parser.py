"""Parse machine-safe GitLab review notes into prior review models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import PriorReviewFinding, PriorReviewPass, ReviewFinding
from ai_sonar_bot.services.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)
from ai_sonar_bot.services.review_gitlab_prior_context_service import (
    extract_machine_safe_review_note_payload,
)

_VALID_CLASSIFICATIONS = frozenset({"no_findings", "findings_present", "manual_review_only"})
_VALID_SEVERITIES = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class PriorReviewNoteParseResult:
    """Capture one bounded prior-review note parse attempt."""

    prior_review_pass: PriorReviewPass | None
    message: str


class ReviewGitLabPriorNoteParser:
    """Rebuild one prior review pass from a machine-safe GitLab MR note."""

    def parse_note(
        self,
        *,
        note: MergeRequestNote,
        expected_merge_request_iid: int,
    ) -> PriorReviewNoteParseResult:
        """Parse one machine-safe review note into a bounded prior review pass."""
        payload = extract_machine_safe_review_note_payload(note.body)
        if payload is None:
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note does not contain a valid machine-safe review payload.",
            )

        reviewed_merge_request_iid = payload.get("reviewed_merge_request_iid")
        if reviewed_merge_request_iid != expected_merge_request_iid:
            return PriorReviewNoteParseResult(
                prior_review_pass=None,
                message="Selected note machine-safe payload targets a different merge request.",
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
    title = payload.get("title")
    symbol = payload.get("symbol")
    issue_kind = payload.get("issue_kind")
    region_hint = payload.get("region_hint")

    if not isinstance(summary, str) or not isinstance(file_path, str) or not isinstance(title, str):
        return None
    if severity is not None and severity not in _VALID_SEVERITIES:
        return None
    if not _is_optional_string(symbol):
        return None
    if not _is_optional_string(issue_kind):
        return None
    if not _is_optional_string(region_hint):
        return None

    synthetic_finding = ReviewFinding(
        severity=_coerce_severity(severity),
        file_path=file_path,
        symbol=symbol,
        issue_kind=issue_kind,
        region_hint=region_hint,
        title=title,
        evidence="machine-safe prior review payload",
        explanation="machine-safe prior review payload",
        suggested_follow_up="machine-safe prior review payload",
    )
    return PriorReviewFinding(
        identity=build_review_finding_identity(synthetic_finding),
        legacy_identity=build_legacy_review_finding_identity(synthetic_finding),
        summary=summary,
        severity=severity,
        symbol=symbol,
        issue_kind=issue_kind,
        region_hint=region_hint,
    )


def _coerce_severity(severity: str | None) -> Literal["high", "medium", "low"]:
    """Return one valid severity for identity reconstruction scaffolding."""
    if severity in _VALID_SEVERITIES:
        return cast(Literal["high", "medium", "low"], severity)
    return "medium"


def _is_optional_string(value: object) -> bool:
    """Return whether one optional payload field is either null or a string."""
    return value is None or isinstance(value, str)

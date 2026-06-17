import json

from zeroone_ops.models.gitlab import MergeRequestNote
from zeroone_ops.services.review.review_gitlab_prior_note_parser import (
    GitLabChangeRequestPriorNoteParser,
)

START_MARKER = "<!-- ai-sonar-bot:review-note:v1\n"
END_MARKER = "\n-->"


def build_note(payload: dict[str, object], *, note_id: int = 55) -> MergeRequestNote:
    return MergeRequestNote(
        id=note_id,
        web_url=f"https://gitlab.example.com/group/project/-/merge_requests/17#note_{note_id}",
        author_username="ai-sonar-bot",
        body=(
            "Hi,\n\nHere are your review notes.\n\n"
            + START_MARKER
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
            + END_MARKER
        ),
    )


def build_payload(
    *,
    classification: str = "findings_present",
    findings: list[dict[str, object]] | None = None,
    findings_count: int | None = None,
) -> dict[str, object]:
    normalized_findings = findings or []
    return {
        "schema": "ai-sonar-bot/review-note/v1",
        "reviewed_change_request_number": 17,
        "reviewed_head_sha": "abc123",
        "classification": classification,
        "summary": "One earlier concern still needs attention.",
        "findings_count": len(normalized_findings) if findings_count is None else findings_count,
        "findings": normalized_findings,
    }


def build_finding_payload() -> dict[str, object]:
    return {
        "identity": "src/service.py::coverage_gap::service-run::changed-branch",
        "legacy_identity": "src/service.py::coverage-miss-test",
        "summary": "src/service.py: Missing test coverage",
        "severity": "medium",
        "file_path": "src/service.py",
        "line_start": 12,
        "line_end": 13,
        "title": "Missing test coverage",
        "symbol": "Service.run",
        "issue_kind": "coverage_gap",
        "region_hint": "changed-branch",
        "inline_comment": {
            "comment_id": "789",
            "comment_url": "https://gitlab.example.com/comment/789",
            "status": "published",
            "anchor_file_path": "src/service.py",
            "anchor_line_start": 12,
            "anchor_line_end": 13,
        },
    }


def test_parse_note_rebuilds_findings_present_pass() -> None:
    parser = GitLabChangeRequestPriorNoteParser()

    result = parser.parse_note(
        note=build_note(build_payload(findings=[build_finding_payload()])),
        expected_change_request_number=17,
    )

    assert result.prior_review_pass is not None
    assert result.prior_review_pass.reviewed_head_sha == "abc123"
    assert result.prior_review_pass.classification == "findings_present"
    assert result.prior_review_pass.findings_count == 1
    assert result.prior_review_pass.note_id == 55
    assert result.prior_review_pass.note_url is not None
    assert result.prior_review_pass.findings[0].summary == "src/service.py: Missing test coverage"
    assert result.prior_review_pass.findings[0].severity == "medium"
    assert result.prior_review_pass.findings[0].file_path == "src/service.py"
    assert result.prior_review_pass.findings[0].line_start == 12
    assert result.prior_review_pass.findings[0].line_end == 13
    assert result.prior_review_pass.findings[0].title == "Missing test coverage"
    assert result.prior_review_pass.findings[0].identity == (
        "src/service.py::coverage_gap::service-run::changed-branch"
    )
    assert result.prior_review_pass.findings[0].legacy_identity == (
        "src/service.py::coverage-miss-test"
    )
    assert result.prior_review_pass.findings[0].inline_comment is not None
    assert result.prior_review_pass.findings[0].inline_comment.comment_id == "789"
    assert result.prior_review_pass.findings[0].inline_comment.anchor_line_start == 12


def test_parse_note_rebuilds_no_findings_pass() -> None:
    parser = GitLabChangeRequestPriorNoteParser()

    result = parser.parse_note(
        note=build_note(build_payload(classification="no_findings", findings=[])),
        expected_change_request_number=17,
    )

    assert result.prior_review_pass is not None
    assert result.prior_review_pass.classification == "no_findings"
    assert result.prior_review_pass.findings_count == 0
    assert result.prior_review_pass.findings == []


def test_parse_note_rebuilds_manual_review_only_pass() -> None:
    parser = GitLabChangeRequestPriorNoteParser()

    result = parser.parse_note(
        note=build_note(build_payload(classification="manual_review_only", findings=[])),
        expected_change_request_number=17,
    )

    assert result.prior_review_pass is not None
    assert result.prior_review_pass.classification == "manual_review_only"
    assert result.prior_review_pass.findings_count == 0


def test_parse_note_rejects_different_merge_request_iid() -> None:
    parser = GitLabChangeRequestPriorNoteParser()

    result = parser.parse_note(
        note=build_note(build_payload()),
        expected_change_request_number=99,
    )

    assert result.prior_review_pass is None
    assert (
        result.message == "Selected note machine-safe payload targets a different change request."
    )


def test_parse_note_rejects_mismatched_findings_count() -> None:
    parser = GitLabChangeRequestPriorNoteParser()

    result = parser.parse_note(
        note=build_note(build_payload(findings=[build_finding_payload()], findings_count=2)),
        expected_change_request_number=17,
    )

    assert result.prior_review_pass is None
    assert result.message == (
        "Selected note machine-safe payload findings count does not match findings."
    )


def test_parse_note_rejects_mismatched_supplied_identity() -> None:
    parser = GitLabChangeRequestPriorNoteParser()
    finding = build_finding_payload()
    finding["identity"] = "src/service.py::different-identity"

    result = parser.parse_note(
        note=build_note(build_payload(findings=[finding])),
        expected_change_request_number=17,
    )

    assert result.prior_review_pass is None
    assert result.message == "Selected note machine-safe payload has an invalid finding entry."

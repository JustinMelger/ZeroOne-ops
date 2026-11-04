"""Keep optional descriptive output bounded without weakening finding validation."""

import json

import pytest
from pydantic import ValidationError

from zeroone_ops.models.review import PublishableReviewArtifact, ReviewResult
from zeroone_ops.models.review_change_summary import ReviewChangeSummary


@pytest.mark.parametrize("count", [1, 2, 3])
def test_summary_normalizes_whitespace_and_is_immutable(count: int) -> None:
    summary = ReviewChangeSummary(bullets=["  Adds\t bounded\nreview metadata.  "] * count)
    assert summary.bullets == ("Adds bounded review metadata.",) * count
    with pytest.raises(ValidationError, match="frozen"):
        summary.bullets = ("A replacement",)


def test_summary_accepts_exact_character_bounds_and_round_trips_unicode() -> None:
    summary = ReviewChangeSummary(bullets=["\u6771" * 300] * 3)
    assert sum(map(len, summary.bullets)) == 900
    assert ReviewChangeSummary.model_validate_json(summary.model_dump_json()) == summary


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"bullets": []},
        {"bullets": [""]},
        {"bullets": [" \t\n"]},
        {"bullets": ["Valid", ""]},
        {"bullets": ["x" * 301]},
        {"bullets": ["One", "Two", "Three", "Four"]},
        {"bullets": "Not an array"},
        {"bullets": [7]},
        {"bullets": [True]},
        {"bullets": [None]},
        {"bullets": [{"text": "Nested"}]},
        {"bullets": ["Valid"], "review_scope_limited": False},
        "Text",
        7,
        [],
    ],
)
def test_invalid_optional_summary_is_omitted_without_altering_findings(invalid: object) -> None:
    payload = {
        "classification": "findings_present",
        "summary": "One finding.",
        "change_summary": invalid,
        "findings": [
            {
                "severity": "medium",
                "file_path": "src/service.py",
                "title": "Missing guard",
                "evidence": "The changed function indexes an empty list.",
                "explanation": "Valid input raises IndexError.",
                "suggested_follow_up": "Add a guard.",
            }
        ],
    }
    expected = ReviewResult.model_validate({**payload, "change_summary": None})
    result = ReviewResult.model_validate_json(json.dumps(payload))
    assert result == expected
    assert result.change_summary is None


@pytest.mark.parametrize("summary", [None, {"bullets": ["A valid description"]}, {"bullets": []}])
def test_summary_never_masks_invalid_review_fields(summary: object) -> None:
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(
            {"classification": "invalid", "summary": "Outcome", "change_summary": summary}
        )
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(
            {
                "classification": "findings_present",
                "summary": "Outcome",
                "change_summary": summary,
                "findings": [{"severity": "invalid"}],
            }
        )


def test_optional_summary_defaults_do_not_manufacture_historical_descriptions() -> None:
    assert ReviewResult(classification="no_findings", summary="Clear").change_summary is None
    artifact = PublishableReviewArtifact(classification="no_findings", summary="Clear")
    assert artifact.change_summary is None
    assert artifact.review_scope_limited
    valid = ReviewResult.model_validate(
        {
            "classification": "no_findings",
            "summary": "Clear",
            "change_summary": {"bullets": ["Adds a guard."]},
            "review_scope_limited": False,
        }
    )
    assert valid.change_summary == ReviewChangeSummary(bullets=["Adds a guard."])
    assert "review_scope_limited" not in valid.model_dump()


def test_undecodable_json_is_not_treated_as_optional_summary_failure() -> None:
    with pytest.raises(ValidationError):
        ReviewResult.model_validate_json('{"classification": "no_findings", "change_summary":')

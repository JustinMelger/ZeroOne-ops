"""Render representative review note examples for UX calibration."""

from __future__ import annotations

from typing import NoReturn

from zeroone_ops.models.review import (
    ChangeRequestDiffRefs,
    ChangeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewFileContext,
)
from zeroone_ops.services.review.publish.review_publisher import ReviewPublisher

_MACHINE_BLOCK_MARKER = "\n<!-- ai-sonar-bot:review-note:v1\n"


class _UnusedReviewClient:
    """Satisfy the publisher constructor for render-only example output."""

    def create_change_request_comment(self, **_: object) -> NoReturn:
        raise NotImplementedError

    def update_change_request_comment(self, **_: object) -> NoReturn:
        raise NotImplementedError

    def create_change_request_inline_comment(self, **_: object) -> NoReturn:
        raise NotImplementedError


def build_context() -> ChangeRequestReviewContext:
    """Create one small change-request context for example rendering."""
    return ChangeRequestReviewContext(
        change_request_number=209,
        title="refactor: tighten review note UX",
        description="Improve conversational tone in the review summary note.",
        source_branch="feature/review-ux",
        target_branch="main",
        web_url="https://github.com/example/zeroone-ops/pull/209",
        head_sha="abc123def456",
        diff_refs=ChangeRequestDiffRefs(
            base_sha="base123",
            start_sha="start123",
            head_sha="abc123def456",
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=4,
                content="1: value = compute_value(input_data)",
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_follow_up_context() -> ChangeRequestReviewContext:
    """Create one context with bounded prior-review history."""
    return build_context().model_copy(
        update={
            "head_sha": "def456ghi789",
            "prior_review_context": PriorReviewContext(
                change_request_number=209,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123def456",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                identity="src/service.py::missing-coverage",
                                summary="src/service.py: Missing regression coverage",
                                severity="medium",
                            )
                        ],
                    )
                ],
            ),
        }
    )


def build_clear_follow_up_context() -> ChangeRequestReviewContext:
    """Create one context whose prior pass was clear."""
    return build_context().model_copy(
        update={
            "head_sha": "clearfollowup123",
            "prior_review_context": PriorReviewContext(
                change_request_number=209,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123def456",
                        classification="no_findings",
                        findings_count=0,
                        summary="No actionable findings in the earlier pass.",
                        findings=[],
                    )
                ],
            ),
        }
    )


def build_manual_follow_up_context() -> ChangeRequestReviewContext:
    """Create one context whose prior pass needed manual review."""
    return build_context().model_copy(
        update={
            "head_sha": "manualfollowup123",
            "prior_review_context": PriorReviewContext(
                change_request_number=209,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123def456",
                        classification="manual_review_only",
                        findings_count=0,
                        summary="The earlier pass could not assess the diff reliably.",
                        findings=[],
                    )
                ],
            ),
        }
    )


def build_examples() -> list[tuple[str, ChangeRequestReviewContext, PublishableReviewArtifact]]:
    """Return representative note examples for UX review."""
    return [
        (
            "clear",
            build_context(),
            PublishableReviewArtifact(
                classification="no_findings",
                summary="No actionable findings in this review pass.",
                review_confidence=0.91,
                review_confidence_reason="The reviewed change is narrow and well supported.",
                findings=[],
            ),
        ),
        (
            "clear_follow_up",
            build_follow_up_context(),
            PublishableReviewArtifact(
                classification="no_findings",
                summary="The earlier concern is no longer present in the updated changes.",
                review_confidence=0.91,
                review_confidence_reason="The reviewed change is narrow and well supported.",
                findings=[],
                follow_up_lines=["Follow-up review after the earlier bot pass on `abc123def456`."],
            ),
        ),
        (
            "concern_runtime_failure",
            build_context(),
            PublishableReviewArtifact(
                classification="findings_present",
                summary="One medium-risk finding.",
                review_confidence=0.84,
                review_confidence_reason="The failure mode is directly visible in the diff.",
                findings=[
                    PublishableReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        line_start=12,
                        line_end=12,
                        stable_identity="src/service.py::unchecked-types-index",
                        legacy_identity="src/service.py::unchecked-types-index",
                        title="Unchecked access to `vehicle.types[0]` can raise `IndexError`.",
                        evidence="The change reads the first element without guarding empty input.",
                        explanation="Supported empty-list input now fails at runtime.",
                        suggested_follow_up="Guard empty `vehicle.types` input before indexing.",
                        issue_kind="runtime_error",
                    )
                ],
            ),
        ),
        (
            "concern_after_clear",
            build_clear_follow_up_context(),
            PublishableReviewArtifact(
                classification="findings_present",
                summary="One medium-risk finding.",
                review_confidence=0.84,
                review_confidence_reason="The failure mode is directly visible in the diff.",
                follow_up_lines=[
                    "Follow-up review after the earlier bot pass on `abc123def456`.",
                    "This pass introduces a new concern in the updated changes.",
                    "",
                ],
                findings=[
                    PublishableReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        line_start=12,
                        line_end=12,
                        stable_identity="src/service.py::unchecked-types-index",
                        legacy_identity="src/service.py::unchecked-types-index",
                        title="Unchecked access to `vehicle.types[0]` can raise `IndexError`.",
                        evidence="The change reads the first element without guarding empty input.",
                        explanation="Supported empty-list input now fails at runtime.",
                        suggested_follow_up="Guard empty `vehicle.types` input before indexing.",
                        issue_kind="runtime_error",
                    )
                ],
            ),
        ),
        (
            "block_behavioral_regression",
            build_context(),
            PublishableReviewArtifact(
                classification="findings_present",
                summary="Two high-risk findings.",
                review_confidence=0.88,
                review_confidence_reason="The behavior change is explicit in the diff.",
                findings=[
                    PublishableReviewFinding(
                        severity="high",
                        file_path="src/config.py",
                        line_start=22,
                        line_end=25,
                        stable_identity="src/config.py::silent-fallback-country-map",
                        legacy_identity="src/config.py::silent-fallback-country-map",
                        title="Missing lookup-country config now defaults silently to `{}`.",
                        evidence=(
                            "The new path replaces a required config failure with an empty dict."
                        ),
                        explanation=(
                            "This turns a configuration error into silent misconfiguration, "
                            "which is harder to detect in production."
                        ),
                        suggested_follow_up="Fail fast when the configuration is missing.",
                        issue_kind="behavioral_regression",
                    ),
                    PublishableReviewFinding(
                        severity="high",
                        file_path="src/router/articles.py",
                        line_start=48,
                        line_end=50,
                        stable_identity="src/router/articles.py::identifier-normalization-regression",
                        legacy_identity="src/router/articles.py::identifier-normalization-regression",
                        title=(
                            "Article lookup no longer normalizes the VLAPI identifier before "
                            "resolution."
                        ),
                        evidence="The normalization call was removed from the updated lookup path.",
                        explanation=(
                            "Equivalent requests can now return different results depending on "
                            "input shape."
                        ),
                        suggested_follow_up="Normalize the identifier before lookup again.",
                        issue_kind="behavioral_regression",
                    ),
                ],
            ),
        ),
        (
            "manual_review_after_clear",
            build_clear_follow_up_context(),
            PublishableReviewArtifact(
                classification="manual_review_only",
                summary="The diff is too broad to assess reliably in this pass.",
                review_confidence=0.58,
                review_confidence_reason="The change set is broad and cross-cutting.",
                follow_up_lines=[
                    "Follow-up review after the earlier bot pass on `abc123def456`.",
                    (
                        "This pass broadened enough that the current review was not "
                        "confident enough to assess it reliably."
                    ),
                    "",
                ],
                findings=[],
            ),
        ),
        (
            "concern_repeated",
            build_follow_up_context(),
            PublishableReviewArtifact(
                classification="findings_present",
                summary="One medium-risk finding.",
                review_confidence=0.82,
                review_confidence_reason=(
                    "The issue is still directly visible in the changed branch."
                ),
                follow_up_lines=[
                    "Follow-up review after the earlier bot pass on `abc123def456`.",
                    "An earlier concern from the last pass still appears unresolved.",
                    "",
                ],
                findings=[
                    PublishableReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        line_start=30,
                        line_end=32,
                        stable_identity="src/service.py::missing-coverage",
                        legacy_identity="src/service.py::missing-coverage",
                        title="The changed branch still has no regression coverage.",
                        evidence=(
                            "The diff still alters branch behavior without adding a matching test."
                        ),
                        explanation=(
                            "That leaves the repeated behavior change unguarded in future edits."
                        ),
                        suggested_follow_up="Add a regression test for the changed branch.",
                        issue_kind="coverage_regression",
                    )
                ],
            ),
        ),
        (
            "concern_after_manual_review",
            build_manual_follow_up_context(),
            PublishableReviewArtifact(
                classification="findings_present",
                summary="One medium-risk finding.",
                review_confidence=0.82,
                review_confidence_reason=(
                    "The issue is visible once the narrowed change is isolated."
                ),
                follow_up_lines=[
                    "Follow-up review after the earlier bot pass on `abc123def456`.",
                    "This pass introduces a new concern in the updated changes.",
                    "",
                ],
                findings=[
                    PublishableReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        line_start=30,
                        line_end=32,
                        stable_identity="src/service.py::missing-coverage",
                        legacy_identity="src/service.py::missing-coverage",
                        title="The changed branch still has no regression coverage.",
                        evidence=(
                            "The diff still alters branch behavior without adding a matching test."
                        ),
                        explanation=(
                            "That leaves the repeated behavior change unguarded in future edits."
                        ),
                        suggested_follow_up="Add a regression test for the changed branch.",
                        issue_kind="coverage_regression",
                    )
                ],
            ),
        ),
        (
            "manual_review_only",
            build_follow_up_context(),
            PublishableReviewArtifact(
                classification="manual_review_only",
                summary="The diff is too broad to assess reliably in this pass.",
                review_confidence=0.58,
                review_confidence_reason="The change set is broad and cross-cutting.",
                follow_up_lines=[
                    "Follow-up review after the earlier bot pass on `abc123def456`.",
                    (
                        "This pass may still relate to an earlier concern, but the current review "
                        "was not confident enough to verify continuity fully."
                    ),
                    "",
                ],
                findings=[],
            ),
        ),
    ]


def strip_machine_safe_block(note_body: str) -> str:
    """Return only the human-facing note content."""
    marker_index = note_body.find(_MACHINE_BLOCK_MARKER)
    if marker_index == -1:
        return note_body.strip()
    return note_body[:marker_index].rstrip()


def main() -> None:
    """Render the example notes to stdout."""
    publisher = ReviewPublisher(_UnusedReviewClient())
    for name, context, artifact in build_examples():
        note = publisher.render_artifact(context=context, artifact=artifact)
        human_note = strip_machine_safe_block(note)
        print(f"\n=== {name} ===\n")
        print(human_note)


if __name__ == "__main__":
    main()

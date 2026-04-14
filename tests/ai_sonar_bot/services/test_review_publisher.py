from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.services.review_publisher import (
    ReviewPublisher,
    _reconcile_follow_up_review,
)


def build_context() -> MergeRequestReviewContext:
    return MergeRequestReviewContext(
        mr_iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                identity="src/service.py::coverage-miss-test",
                                summary="src/service.py: Missing test coverage",
                                severity="medium",
                            )
                        ],
                    )
                ],
            ),
        }
    )


def build_ambiguous_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                summary="Earlier concern around helper behavior",
                                severity="medium",
                            )
                        ],
                    )
                ],
            ),
        }
    )


def build_mixed_ambiguity_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=2,
                        summary="Two earlier concerns still need attention.",
                        findings=[
                            PriorReviewFinding(
                                identity="src/service.py::coverage-miss-test",
                                summary="src/service.py: Missing test coverage",
                                severity="medium",
                            ),
                            PriorReviewFinding(
                                summary="Earlier concern around helper behavior",
                                severity="medium",
                            ),
                        ],
                    )
                ],
            ),
        }
    )


def build_variant_title_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "ghi789",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="def456",
                        classification="findings_present",
                        findings_count=2,
                        summary="Two earlier concerns still need attention.",
                        findings=[
                            PriorReviewFinding(
                                identity=(
                                    "bnl_app/functions/vehicle_articles_functions.py::"
                                    "cylinder-except-fail-helper-lookup-unconditional"
                                ),
                                summary=(
                                    "bnl_app/functions/vehicle_articles_functions.py: "
                                    "Unconditional exception breaks cylinder lookup helper"
                                ),
                                severity="high",
                            ),
                            PriorReviewFinding(
                                identity=(
                                    "bnl_app/functions/vehicle_functions.py::"
                                    "detail-except-fail-lookup-unconditional-vehicle"
                                ),
                                summary=(
                                    "bnl_app/functions/vehicle_functions.py: "
                                    "Unconditional exception breaks vehicle detail retrieval"
                                ),
                                severity="high",
                            ),
                        ],
                    )
                ],
            ),
        }
    )


class FakeGitLabReviewClient:
    def __init__(self) -> None:
        self.published_body: str | None = None

    def create_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
    ) -> MergeRequestNote:
        del project_id, merge_request_iid
        self.published_body = body
        return MergeRequestNote(
            id=55,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        )


def test_render_note_formats_findings_present() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            review_confidence=0.82,
            review_confidence_reason="The diff is small and the evidence is specific.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    evidence=(
                        "The diff changes `value = 1` to `value = 2` without any test updates."
                    ),
                    explanation="The change alters branch behavior without test updates.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                )
            ],
        ),
    )

    assert "## AI Review Summary" in body
    assert "One medium-risk finding." in body
    assert "Review confidence: 0.82" in body
    assert "Reason: The diff is small and the evidence is specific." in body
    assert "1. [medium] Missing test coverage (`src/service.py`)" in body
    assert (
        "Evidence: The diff changes `value = 1` to `value = 2` without any test updates."
    ) in body
    assert "- Reviewed merge request: `!17`" in body
    assert "- Reviewed commit SHA: `abc123`" in body
    assert "- Files reviewed: 1" in body


def test_render_note_formats_no_findings() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_context(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            review_confidence=0.91,
            review_confidence_reason="The reviewed change is narrow and well supported.",
            findings=[],
        ),
    )

    assert "No actionable findings in this review pass." in body
    assert "Review confidence: 0.91" in body
    assert "- Reviewed merge request: `!17`" in body
    assert "- Files reviewed: 1" in body
    assert "Notes:" not in body


def test_render_note_uses_follow_up_language_for_no_findings_when_prior_review_exists() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_follow_up_context(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
    )

    assert "No new actionable findings since the last reviewed SHA." in body
    assert "Follow-up review after the earlier bot pass on `abc123`." in body
    assert "The earlier concern about `Missing test coverage` no longer appears present." in body


def test_render_note_formats_manual_review_only() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_context(),
        review_result=ReviewResult(
            classification="manual_review_only",
            summary="The diff is too broad to assess reliably in this pass.",
            review_confidence=0.34,
            review_confidence_reason=(
                "The available context is too broad for a reliable review pass."
            ),
            findings=[],
        ),
    )

    assert "Bot assessment was insufficient for a trustworthy review decision." in body
    assert "Review confidence: 0.34" in body
    assert "The diff is too broad to assess reliably in this pass." in body
    assert "This is not an actionable finding by itself." in body
    assert "- Reviewed merge request: `!17`" in body


def test_render_note_uses_follow_up_language_for_repeated_findings() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_follow_up_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    evidence=(
                        "The diff changes `value = 1` to `value = 2` without any test updates."
                    ),
                    explanation="The change alters branch behavior without test updates.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                )
            ],
        ),
    )

    assert "Follow-up review after the earlier bot pass on `abc123`." in body
    assert "The earlier concern about `Missing test coverage` still appears unresolved." in body


def test_render_note_mentions_resolved_and_new_concern_in_same_follow_up_pass() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_follow_up_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing null guard",
                    evidence="The diff removes the `if value is None` guard.",
                    explanation="The change can now dereference a nullable value.",
                    suggested_follow_up="Restore the null guard or add validation.",
                )
            ],
        ),
    )

    assert "Follow-up review after the earlier bot pass on `abc123`." in body
    assert (
        "The earlier concern about `Missing test coverage` no longer appears present, "
        "but a new issue now appears around `Missing null guard`." in body
    )


def test_render_note_handles_same_follow_up_finding_when_title_wording_drifts() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_variant_title_follow_up_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=[
                ReviewFinding(
                    severity="high",
                    file_path="bnl_app/functions/vehicle_functions.py",
                    title="Unconditional exception makes vehicle detail lookup always fail",
                    evidence=(
                        "The patch inserts `raise ValueError` at the top of "
                        "`get_vehicle_details_short(...)`."
                    ),
                    explanation=(
                        "The function now raises before any existing vehicle detail "
                        "lookup logic can execute."
                    ),
                    suggested_follow_up=(
                        "Remove the debug raise or gate it behind a test-only path."
                    ),
                )
            ],
        ),
    )

    assert "Follow-up review after the earlier bot pass on `def456`." in body
    assert (
        "The earlier concern about `Unconditional exception breaks vehicle detail retrieval` "
        "still appears unresolved." in body
    )
    assert (
        "The earlier concern about `Unconditional exception breaks cylinder lookup helper` "
        "no longer appears present." in body
    )


def test_render_note_uses_unable_to_verify_language_for_ambiguous_resolved_follow_up() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_ambiguous_follow_up_context(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
    )

    assert "Follow-up review after the earlier bot pass on `abc123`." in body
    assert (
        "The current pass could not verify conclusively whether the earlier concern "
        "is fully resolved." in body
    )


def test_render_note_prefers_unable_to_verify_over_resolved_when_prior_state_is_mixed() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_mixed_ambiguity_follow_up_context(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
    )

    assert "Follow-up review after the earlier bot pass on `abc123`." in body
    assert (
        "The current pass could not verify conclusively whether the earlier concern "
        "is fully resolved." in body
    )
    assert "no longer appears present" not in body


def test_render_note_uses_unable_to_verify_language_for_ambiguous_mixed_follow_up() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_ambiguous_follow_up_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing null guard",
                    evidence="The diff removes the `if value is None` guard.",
                    explanation="The change can now dereference a nullable value.",
                    suggested_follow_up="Restore the null guard or add validation.",
                )
            ],
        ),
    )

    assert "Follow-up review after the earlier bot pass on `abc123`." in body
    assert (
        "The current pass could not verify conclusively whether the earlier concern "
        "is fully resolved." in body
    )
    assert "A new issue in this pass appears around `Missing null guard`." in body


def test_reconcile_follow_up_review_marks_repeated_findings_as_still_unresolved() -> None:
    reconciliation = _reconcile_follow_up_review(
        context=build_follow_up_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    evidence="The diff changes `value = 1` to `value = 2`.",
                    explanation="The change alters branch behavior without test updates.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                )
            ],
        ),
    )

    assert reconciliation is not None
    assert reconciliation.prior_reviewed_head_sha == "abc123"
    assert [item.summary for item in reconciliation.still_unresolved] == [
        "src/service.py: Missing test coverage"
    ]
    assert [item.identity for item in reconciliation.still_unresolved] == [
        "src/service.py::coverage-miss-test"
    ]
    assert reconciliation.appears_resolved == []
    assert reconciliation.new_findings == []


def test_reconcile_follow_up_review_marks_missing_prior_finding_as_resolved() -> None:
    reconciliation = _reconcile_follow_up_review(
        context=build_follow_up_context(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
    )

    assert reconciliation is not None
    assert reconciliation.still_unresolved == []
    assert [item.summary for item in reconciliation.appears_resolved] == [
        "src/service.py: Missing test coverage"
    ]
    assert [item.identity for item in reconciliation.appears_resolved] == [
        "src/service.py::coverage-miss-test"
    ]
    assert reconciliation.new_findings == []


def test_reconcile_follow_up_review_marks_different_current_finding_as_new() -> None:
    reconciliation = _reconcile_follow_up_review(
        context=build_follow_up_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing null guard",
                    evidence="The diff removes the `if value is None` guard.",
                    explanation="The change can now dereference a nullable value.",
                    suggested_follow_up="Restore the null guard or add validation.",
                )
            ],
        ),
    )

    assert reconciliation is not None
    assert reconciliation.still_unresolved == []
    assert [item.summary for item in reconciliation.appears_resolved] == [
        "src/service.py: Missing test coverage"
    ]
    assert [item.summary for item in reconciliation.new_findings] == [
        "src/service.py: Missing null guard"
    ]


def test_reconcile_follow_up_review_prefers_identity_for_wording_drift() -> None:
    reconciliation = _reconcile_follow_up_review(
        context=build_variant_title_follow_up_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=[
                ReviewFinding(
                    severity="high",
                    file_path="bnl_app/functions/vehicle_functions.py",
                    title="Unconditional exception makes vehicle detail lookup always fail",
                    evidence="The patch inserts `raise ValueError` at the top of the helper.",
                    explanation="The helper raises before any existing lookup logic can run.",
                    suggested_follow_up=(
                        "Remove the debug raise or gate it behind a test-only path."
                    ),
                )
            ],
        ),
    )

    assert reconciliation is not None
    assert [item.summary for item in reconciliation.still_unresolved] == [
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional exception breaks vehicle detail retrieval"
    ]
    assert [item.identity for item in reconciliation.still_unresolved] == [
        "bnl_app/functions/vehicle_functions.py::"
        "detail-except-fail-lookup-unconditional-vehicle"
    ]
    assert [item.summary for item in reconciliation.appears_resolved] == [
        "bnl_app/functions/vehicle_articles_functions.py: "
        "Unconditional exception breaks cylinder lookup helper"
    ]


def test_reconcile_follow_up_review_keeps_legacy_fallback_without_identity() -> None:
    legacy_context = build_variant_title_follow_up_context().model_copy(
        update={
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="def456",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                summary=(
                                    "bnl_app/functions/vehicle_functions.py: "
                                    "Unconditional exception breaks vehicle detail retrieval"
                                ),
                                severity="high",
                            )
                        ],
                    )
                ],
            )
        }
    )

    reconciliation = _reconcile_follow_up_review(
        context=legacy_context,
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=[
                ReviewFinding(
                    severity="high",
                    file_path="bnl_app/functions/vehicle_functions.py",
                    title="Unconditional exception makes vehicle detail lookup always fail",
                    evidence="The patch inserts `raise ValueError` at the top of the helper.",
                    explanation="The helper raises before any existing lookup logic can run.",
                    suggested_follow_up=(
                        "Remove the debug raise or gate it behind a test-only path."
                    ),
                )
            ],
        ),
    )

    assert reconciliation is not None
    assert [item.summary for item in reconciliation.still_unresolved] == [
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional exception breaks vehicle detail retrieval"
    ]


def test_reconcile_follow_up_review_marks_unstructured_prior_finding_as_ambiguous() -> None:
    reconciliation = _reconcile_follow_up_review(
        context=build_ambiguous_follow_up_context(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
    )

    assert reconciliation is not None
    assert reconciliation.still_unresolved == []
    assert reconciliation.appears_resolved == []
    assert reconciliation.new_findings == []
    assert reconciliation.unable_to_verify_resolution is True


def test_publish_sends_rendered_note_body() -> None:
    review_client = FakeGitLabReviewClient()
    publisher = ReviewPublisher(review_client)

    result = publisher.publish(
        project_id="123",
        merge_request_iid=17,
        context=build_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            review_confidence=0.82,
            review_confidence_reason="The diff is small and the evidence is specific.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    evidence=(
                        "The diff changes `value = 1` to `value = 2` without any test updates."
                    ),
                    explanation="The change alters branch behavior without test updates.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                )
            ],
        ),
    )

    assert result.note is not None
    assert result.note.id == 55
    assert review_client.published_body is not None
    assert "Missing test coverage" in review_client.published_body

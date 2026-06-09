from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewInlineComment,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewFileContext,
)
from zeroone_ops.services.review.review_inline_comment_continuity_service import (
    ReviewInlineCommentContinuityService,
)


def build_context(
    *,
    prior_passes: list[PriorReviewPass] | None = None,
) -> MergeRequestReviewContext:
    return MergeRequestReviewContext(
        mr_iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="def456",
        prior_review_context=(
            None
            if prior_passes is None
            else PriorReviewContext(merge_request_iid=17, passes=prior_passes)
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -10,1 +12,2 @@",
                start_line=10,
                end_line=14,
                content="  12: value = transform(value)",
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_artifact() -> PublishableReviewArtifact:
    return PublishableReviewArtifact(
        classification="findings_present",
        summary="One medium-risk finding.",
        findings=[
            PublishableReviewFinding(
                severity="medium",
                file_path="src/service.py",
                line_start=12,
                line_end=13,
                stable_identity="src/service.py::coverage_gap::service-run::changed-branch",
                legacy_identity="src/service.py::coverage-miss-test",
                symbol="Service.run",
                issue_kind="coverage_gap",
                region_hint="changed-branch",
                title="Missing regression coverage",
                evidence="The diff changes a branch without matching test updates.",
                explanation="The branch behavior changes without regression coverage.",
                suggested_follow_up="Add a regression test.",
            )
        ],
    )


def build_prior_finding(
    *,
    identity: str,
    inline_comment: PriorReviewInlineComment | None,
) -> PriorReviewFinding:
    return PriorReviewFinding(
        identity=identity,
        legacy_identity="src/service.py::coverage-miss-test",
        summary="src/service.py: Missing regression coverage",
        severity="medium",
        file_path="src/service.py",
        line_start=12,
        line_end=13,
        title="Missing regression coverage",
        symbol="Service.run",
        issue_kind="coverage_gap",
        region_hint="changed-branch",
        inline_comment=inline_comment,
    )


def test_apply_reuses_published_inline_comment_from_latest_prior_pass() -> None:
    result = ReviewInlineCommentContinuityService().apply(
        context=build_context(
            prior_passes=[
                PriorReviewPass(
                    reviewed_head_sha="abc123",
                    classification="findings_present",
                    findings_count=1,
                    findings=[
                        build_prior_finding(
                            identity="src/service.py::coverage_gap::service-run::changed-branch",
                            inline_comment=PriorReviewInlineComment(
                                comment_id="789",
                                comment_url="https://gitlab.example.com/comment/789",
                                status="published",
                                anchor_file_path="src/service.py",
                                anchor_line_start=12,
                                anchor_line_end=13,
                            ),
                        )
                    ],
                )
            ]
        ),
        artifact=build_artifact(),
    )

    assert result.reused_inline_comment_count == 1
    assert result.artifact.findings[0].inline_comment is not None
    assert result.artifact.findings[0].inline_comment.comment_id == "789"


def test_apply_uses_latest_prior_pass_only_for_duplicate_comment_reuse() -> None:
    result = ReviewInlineCommentContinuityService().apply(
        context=build_context(
            prior_passes=[
                PriorReviewPass(
                    reviewed_head_sha="def123",
                    classification="findings_present",
                    findings_count=1,
                    findings=[
                        build_prior_finding(
                            identity="src/service.py::different::identity",
                            inline_comment=PriorReviewInlineComment(
                                comment_id="latest",
                                comment_url=None,
                                status="published",
                                anchor_file_path="src/service.py",
                                anchor_line_start=20,
                                anchor_line_end=20,
                            ),
                        )
                    ],
                ),
                PriorReviewPass(
                    reviewed_head_sha="abc123",
                    classification="findings_present",
                    findings_count=1,
                    findings=[
                        build_prior_finding(
                            identity="src/service.py::coverage_gap::service-run::changed-branch",
                            inline_comment=PriorReviewInlineComment(
                                comment_id="older",
                                comment_url=None,
                                status="published",
                                anchor_file_path="src/service.py",
                                anchor_line_start=12,
                                anchor_line_end=13,
                            ),
                        )
                    ],
                ),
            ]
        ),
        artifact=build_artifact(),
    )

    assert result.reused_inline_comment_count == 0
    assert result.artifact.findings[0].inline_comment is None


def test_apply_does_not_reuse_superseded_or_override_existing_inline_comment() -> None:
    artifact = build_artifact().model_copy(
        update={
            "findings": [
                build_artifact()
                .findings[0]
                .model_copy(
                    update={
                        "inline_comment": PriorReviewInlineComment(
                            comment_id="current",
                            comment_url=None,
                            status="published",
                            anchor_file_path="src/service.py",
                            anchor_line_start=12,
                            anchor_line_end=13,
                        )
                    }
                )
            ]
        }
    )
    result = ReviewInlineCommentContinuityService().apply(
        context=build_context(
            prior_passes=[
                PriorReviewPass(
                    reviewed_head_sha="abc123",
                    classification="findings_present",
                    findings_count=1,
                    findings=[
                        build_prior_finding(
                            identity="src/service.py::coverage_gap::service-run::changed-branch",
                            inline_comment=PriorReviewInlineComment(
                                comment_id="superseded",
                                comment_url=None,
                                status="superseded",
                                anchor_file_path="src/service.py",
                                anchor_line_start=12,
                                anchor_line_end=13,
                            ),
                        )
                    ],
                )
            ]
        ),
        artifact=artifact,
    )

    assert result.reused_inline_comment_count == 0
    assert result.artifact.findings[0].inline_comment is not None
    assert result.artifact.findings[0].inline_comment.comment_id == "current"

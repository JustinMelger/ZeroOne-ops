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
                content=(
                    "  12: changed_branch = transform(value)\n"
                    "  13: return changed_branch  # Service.run"
                ),
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
                evidence=(
                    "The diff changes `changed_branch = transform(value)` without "
                    "matching test updates."
                ),
                explanation="The branch behavior changes without regression coverage.",
                suggested_follow_up="Add a regression test.",
            )
        ],
    )


def build_inline_comment() -> PriorReviewInlineComment:
    return PriorReviewInlineComment(
        comment_id="789",
        comment_url="https://gitlab.example.com/comment/789",
        status="published",
        anchor_file_path="src/service.py",
        anchor_line_start=12,
        anchor_line_end=13,
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
                            inline_comment=build_inline_comment(),
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
                            inline_comment=build_inline_comment().model_copy(
                                update={
                                    "comment_id": "latest",
                                    "comment_url": None,
                                    "anchor_line_start": 20,
                                    "anchor_line_end": 20,
                                }
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
                            inline_comment=build_inline_comment().model_copy(
                                update={"comment_id": "older", "comment_url": None}
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


def test_apply_does_not_reuse_inline_comment_for_low_severity_finding() -> None:
    artifact = build_artifact().model_copy(
        update={"findings": [build_artifact().findings[0].model_copy(update={"severity": "low"})]}
    )
    finding_identity = artifact.findings[0].stable_identity or ""

    result = ReviewInlineCommentContinuityService().apply(
        context=build_context(
            prior_passes=[
                PriorReviewPass(
                    reviewed_head_sha="abc123",
                    classification="findings_present",
                    findings_count=1,
                    findings=[
                        build_prior_finding(
                            identity=finding_identity,
                            inline_comment=build_inline_comment(),
                        )
                    ],
                )
            ]
        ),
        artifact=artifact,
    )

    assert result.reused_inline_comment_count == 0
    assert result.artifact.findings[0].inline_comment is None


def test_apply_does_not_reuse_inline_comment_for_weak_location() -> None:
    artifact = build_artifact().model_copy(
        update={
            "findings": [
                build_artifact().findings[0].model_copy(update={"line_start": 40, "line_end": 41})
            ]
        }
    )
    finding_identity = artifact.findings[0].stable_identity or ""

    result = ReviewInlineCommentContinuityService().apply(
        context=build_context(
            prior_passes=[
                PriorReviewPass(
                    reviewed_head_sha="abc123",
                    classification="findings_present",
                    findings_count=1,
                    findings=[
                        build_prior_finding(
                            identity=finding_identity,
                            inline_comment=build_inline_comment(),
                        )
                    ],
                )
            ]
        ),
        artifact=artifact,
    )

    assert result.reused_inline_comment_count == 0
    assert result.artifact.findings[0].inline_comment is None


def test_apply_does_not_reuse_inline_comment_when_anchor_drift_is_too_large() -> None:
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
                            inline_comment=build_inline_comment().model_copy(
                                update={"anchor_line_start": 30, "anchor_line_end": 31}
                            ),
                        )
                    ],
                )
            ]
        ),
        artifact=build_artifact(),
    )

    assert result.reused_inline_comment_count == 0
    assert result.artifact.findings[0].inline_comment is None


def test_apply_does_not_reuse_inline_comment_when_local_region_differs() -> None:
    artifact = build_artifact().model_copy(
        update={
            "findings": [
                build_artifact().findings[0].model_copy(
                    update={
                        "region_hint": "different-branch",
                        "symbol": "Service.other",
                        "title": "Different branch regression",
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
                            inline_comment=build_inline_comment(),
                        )
                    ],
                )
            ]
        ),
        artifact=artifact,
    )

    assert result.reused_inline_comment_count == 0
    assert result.artifact.findings[0].inline_comment is None


def test_apply_does_not_reuse_inline_comment_when_multiple_nearby_hunks_compete() -> None:
    ambiguous_context = build_context().model_copy(
        update={
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=1,
                        findings=[
                            build_prior_finding(
                                identity="src/service.py::coverage_gap::service-run::changed-branch",
                                inline_comment=build_inline_comment(),
                            )
                        ],
                    )
                ],
            ),
            "changed_files": [
                ReviewFileContext(
                    file_path="src/service.py",
                    diff="@@ -10,1 +12,1 @@\n@@ -20,1 +14,1 @@",
                    start_line=10,
                    end_line=14,
                    content=(
                        "  12: changed_branch = transform(value)\n"
                        "  13: return changed_branch  # Service.run"
                    ),
                    full_file_included=True,
                    truncated=False,
                )
            ]
        }
    )

    result = ReviewInlineCommentContinuityService().apply(
        context=ambiguous_context,
        artifact=build_artifact(),
    )

    assert result.reused_inline_comment_count == 0
    assert result.artifact.findings[0].inline_comment is None

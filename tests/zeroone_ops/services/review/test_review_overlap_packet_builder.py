from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.services.review.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)
from zeroone_ops.services.review.review_overlap_packet_builder import (
    OverlapPacketBuilder,
)


def _build_context(*, prior_pass: PriorReviewPass | None = None) -> MergeRequestReviewContext:
    return MergeRequestReviewContext(
        mr_iid=122,
        title="test: overlap packet",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/122",
        head_sha="current-sha",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="raise ValueError",
                full_file_included=True,
                truncated=False,
            )
        ],
        prior_review_context=(
            None
            if prior_pass is None
            else PriorReviewContext(
                merge_request_iid=122,
                passes=[prior_pass],
            )
        ),
    )


def _build_prior_pass(*, findings: list[ReviewFinding]) -> PriorReviewPass:
    return PriorReviewPass(
        reviewed_head_sha="prior-sha",
        classification="findings_present",
        findings_count=len(findings),
        summary="Earlier review state.",
        findings=[
            PriorReviewFinding(
                identity=build_review_finding_identity(finding),
                legacy_identity=build_legacy_review_finding_identity(finding),
                summary=f"{finding.file_path}: {finding.title}",
                severity=finding.severity,
                symbol=finding.symbol,
                issue_kind=finding.issue_kind,
                region_hint=finding.region_hint,
            )
            for finding in findings
        ],
    )


def _vehicle_details_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/service.py",
        symbol="get_vehicle_details_long",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Vehicle details helper now always raises",
        evidence="The function raises before any helper logic runs.",
        explanation="All callers now fail before details are built.",
        suggested_follow_up="Remove the unconditional raise.",
    )


def _payload_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/service.py",
        symbol="build_payload",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Payload helper now always raises",
        evidence="The helper raises before payload construction.",
        explanation="Payload callers now fail immediately.",
        suggested_follow_up="Remove the unconditional raise.",
    )


def _grouped_payload_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/service.py",
        symbol="build_grouped_payload",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Grouped payload helper now always raises",
        evidence="The helper raises before grouped payload construction.",
        explanation="Grouped payload callers now fail immediately.",
        suggested_follow_up="Remove the unconditional raise.",
    )


def _unstructured_vehicle_variant() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/service.py",
        title="Vehicle details path now always fails before lookup",
        evidence="The helper raises before the body executes.",
        explanation="The lookup path now fails before any existing logic runs.",
        suggested_follow_up="Remove the unconditional raise.",
    )


def test_build_overlap_packet_returns_none_without_prior_pass() -> None:
    packet = OverlapPacketBuilder().build(
        context=_build_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One finding.",
            findings=[_vehicle_details_finding()],
        ),
    )

    assert packet is None


def test_build_overlap_packet_uses_canonical_identity_candidate() -> None:
    prior_finding = _vehicle_details_finding()
    packet = OverlapPacketBuilder().build(
        context=_build_context(prior_pass=_build_prior_pass(findings=[prior_finding])),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One finding.",
            findings=[_vehicle_details_finding()],
        ),
    )

    assert packet is not None
    assert packet.current_head_sha == "current-sha"
    assert packet.prior_head_sha == "prior-sha"
    assert [candidate.model_dump() for candidate in packet.candidates] == [
        {
            "current_finding_index": 0,
            "prior_finding_index": 0,
            "reasons": ["canonical_identity"],
        }
    ]


def test_build_overlap_packet_narrows_same_file_candidates_by_structured_fields() -> None:
    packet = OverlapPacketBuilder().build(
        context=_build_context(
            prior_pass=_build_prior_pass(findings=[_payload_finding(), _vehicle_details_finding()])
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One finding.",
            findings=[_vehicle_details_finding()],
        ),
    )

    assert packet is not None
    assert [candidate.model_dump() for candidate in packet.candidates] == [
        {
            "current_finding_index": 0,
            "prior_finding_index": 1,
            "reasons": ["canonical_identity"],
        }
    ]


def test_build_overlap_packet_preserves_ambiguous_same_file_candidates() -> None:
    packet = OverlapPacketBuilder().build(
        context=_build_context(
            prior_pass=_build_prior_pass(findings=[_payload_finding(), _grouped_payload_finding()])
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One finding.",
            findings=[_unstructured_vehicle_variant()],
        ),
    )

    assert packet is not None
    assert [candidate.model_dump() for candidate in packet.candidates] == [
        {
            "current_finding_index": 0,
            "prior_finding_index": 0,
            "reasons": ["same_file"],
        },
        {
            "current_finding_index": 0,
            "prior_finding_index": 1,
            "reasons": ["same_file"],
        },
    ]


def test_build_overlap_packet_uses_structured_prior_fields_without_summary_parsing() -> None:
    prior_finding = _vehicle_details_finding()
    prior_pass = PriorReviewPass(
        reviewed_head_sha="prior-sha",
        classification="findings_present",
        findings_count=1,
        summary="Earlier review state.",
        findings=[
            PriorReviewFinding(
                identity=build_review_finding_identity(prior_finding),
                legacy_identity=build_legacy_review_finding_identity(prior_finding),
                summary="non parseable prior summary",
                severity=prior_finding.severity,
                file_path=prior_finding.file_path,
                title=prior_finding.title,
                symbol=prior_finding.symbol,
                issue_kind=prior_finding.issue_kind,
                region_hint=prior_finding.region_hint,
            )
        ],
    )
    packet = OverlapPacketBuilder().build(
        context=_build_context(prior_pass=prior_pass),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One finding.",
            findings=[_vehicle_details_finding()],
        ),
    )

    assert packet is not None
    assert [candidate.model_dump() for candidate in packet.candidates] == [
        {
            "current_finding_index": 0,
            "prior_finding_index": 0,
            "reasons": ["canonical_identity"],
        }
    ]

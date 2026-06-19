from zeroone_ops.models.review import (
    OverlapCandidate,
    OverlapPacket,
    PriorReviewFinding,
    ReviewFinding,
)
from zeroone_ops.services.review.continuity.review_overlap_reconciliation import (
    OverlapReconciliationService,
)


def _current_finding(title: str) -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/service.py",
        title=title,
        evidence="evidence",
        explanation="explanation",
        suggested_follow_up="follow up",
    )


def _prior_finding(title: str) -> PriorReviewFinding:
    return PriorReviewFinding(summary=f"src/service.py: {title}")


def test_reconcile_overlap_packet_marks_new_finding_without_candidates() -> None:
    result = OverlapReconciliationService().reconcile(
        packet=OverlapPacket(
            change_request_number=122,
            current_head_sha="current",
            prior_head_sha="prior",
            current_findings=[_current_finding("Current issue")],
            prior_findings=[],
            candidates=[],
        )
    )

    assert result.prior_reviewed_head_sha == "prior"
    assert [resolution.model_dump() for resolution in result.resolutions] == [
        {
            "outcome": "new_in_this_pass",
            "current_finding_index": 0,
            "prior_finding_index": None,
            "related_prior_finding_indices": [],
        }
    ]


def test_reconcile_overlap_packet_marks_single_candidate_as_still_unresolved() -> None:
    result = OverlapReconciliationService().reconcile(
        packet=OverlapPacket(
            change_request_number=122,
            current_head_sha="current",
            prior_head_sha="prior",
            current_findings=[_current_finding("Current issue")],
            prior_findings=[_prior_finding("Prior issue")],
            candidates=[
                OverlapCandidate(
                    current_finding_index=0,
                    prior_finding_index=0,
                    reasons=["canonical_identity"],
                )
            ],
        )
    )

    assert [resolution.model_dump() for resolution in result.resolutions] == [
        {
            "outcome": "still_unresolved",
            "current_finding_index": 0,
            "prior_finding_index": 0,
            "related_prior_finding_indices": [0],
        }
    ]


def test_reconcile_overlap_packet_marks_missing_prior_as_no_longer_present() -> None:
    result = OverlapReconciliationService().reconcile(
        packet=OverlapPacket(
            change_request_number=122,
            current_head_sha="current",
            prior_head_sha="prior",
            current_findings=[],
            prior_findings=[_prior_finding("Prior issue")],
            candidates=[],
        )
    )

    assert [resolution.model_dump() for resolution in result.resolutions] == [
        {
            "outcome": "no_longer_present",
            "current_finding_index": None,
            "prior_finding_index": 0,
            "related_prior_finding_indices": [0],
        }
    ]


def test_reconcile_overlap_packet_marks_multiple_candidates_as_ambiguous() -> None:
    result = OverlapReconciliationService().reconcile(
        packet=OverlapPacket(
            change_request_number=122,
            current_head_sha="current",
            prior_head_sha="prior",
            current_findings=[_current_finding("Current issue")],
            prior_findings=[_prior_finding("Prior A"), _prior_finding("Prior B")],
            candidates=[
                OverlapCandidate(
                    current_finding_index=0,
                    prior_finding_index=0,
                    reasons=["same_file"],
                ),
                OverlapCandidate(
                    current_finding_index=0,
                    prior_finding_index=1,
                    reasons=["same_file"],
                ),
            ],
        )
    )

    assert [resolution.model_dump() for resolution in result.resolutions] == [
        {
            "outcome": "overlap_ambiguous",
            "current_finding_index": 0,
            "prior_finding_index": None,
            "related_prior_finding_indices": [0, 1],
        }
    ]


def test_reconcile_overlap_packet_deduplicates_repeated_single_prior_candidate() -> None:
    result = OverlapReconciliationService().reconcile(
        packet=OverlapPacket(
            change_request_number=122,
            current_head_sha="current",
            prior_head_sha="prior",
            current_findings=[_current_finding("Current issue")],
            prior_findings=[_prior_finding("Prior issue")],
            candidates=[
                OverlapCandidate(
                    current_finding_index=0,
                    prior_finding_index=0,
                    reasons=["same_file", "symbol"],
                ),
                OverlapCandidate(
                    current_finding_index=0,
                    prior_finding_index=0,
                    reasons=["issue_kind", "title_overlap"],
                ),
            ],
        )
    )

    assert [resolution.model_dump() for resolution in result.resolutions] == [
        {
            "outcome": "still_unresolved",
            "current_finding_index": 0,
            "prior_finding_index": 0,
            "related_prior_finding_indices": [0],
        }
    ]

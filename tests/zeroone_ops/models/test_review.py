from datetime import datetime

from zeroone_ops.models.review import (
    ArtifactValidationIssue,
    ArtifactValidationResult,
    CandidateReviewFinding,
    CandidateReviewResult,
    DroppedCandidate,
    PublishableReviewArtifact,
    ReconciledReviewDecision,
    ReviewFinding,
    ReviewResult,
)


def build_review_result() -> ReviewResult:
    return ReviewResult(
        classification="findings_present",
        summary="One medium-risk finding.",
        review_confidence=0.84,
        review_confidence_reason="The finding is grounded in the reviewed diff.",
        findings=[
            ReviewFinding(
                severity="medium",
                file_path="src/service.py",
                symbol="Service.run",
                issue_kind="coverage_gap",
                region_hint="branch-return",
                title="Missing regression coverage",
                evidence="The diff changes `value = 1` to `value = 2` without test updates.",
                explanation="The branch behavior changes without regression coverage.",
                suggested_follow_up="Add a regression test for the changed branch.",
            )
        ],
    )


def test_candidate_review_result_preserves_non_authoritative_provenance() -> None:
    candidate_result = CandidateReviewResult(
        findings=[
            CandidateReviewFinding(
                candidate_id="cand-1",
                severity="medium",
                file_path="src/service.py",
                title="Missing regression coverage",
                evidence="The diff changes `value = 1` to `value = 2` without test updates.",
                explanation="The branch behavior changes without regression coverage.",
                suggested_follow_up="Add a regression test for the changed branch.",
                evidence_summary="Changed branch lacks matching tests.",
                uncertainty_summary="Could still be acceptable if covered elsewhere.",
            )
        ]
    )

    assert candidate_result.findings[0].candidate_id == "cand-1"
    assert candidate_result.findings[0].evidence_summary == ("Changed branch lacks matching tests.")
    assert candidate_result.findings[0].uncertainty_summary == (
        "Could still be acceptable if covered elsewhere."
    )


def test_reconciled_review_decision_from_review_result_preserves_review_meaning() -> None:
    review_result = build_review_result()

    decision = ReconciledReviewDecision.from_review_result(
        review_result,
        prior_review_context_used=True,
        same_sha_review=False,
        repair_allowed=True,
        reconciled_at=datetime(2026, 5, 1, 10, 0, 0),
        pipeline_version="review-staged-v1",
    )

    assert decision.review_classification == "findings_present"
    assert decision.decision_summary == "One medium-risk finding."
    assert decision.decision_rationale == "The finding is grounded in the reviewed diff."
    assert decision.confidence_level == 0.84
    assert decision.prior_review_context_used is True
    assert decision.repair_allowed is True
    assert decision.pipeline_version == "review-staged-v1"
    assert len(decision.accepted_findings) == 1
    assert decision.accepted_findings[0].title == "Missing regression coverage"
    assert decision.accepted_findings[0].why_it_matters == (
        "The branch behavior changes without regression coverage."
    )
    assert decision.accepted_findings[0].source_candidate_ids == []
    assert decision.dropped_candidates == []


def test_publishable_review_artifact_from_reconciled_decision_preserves_boundaries() -> None:
    decision = ReconciledReviewDecision.from_review_result(
        build_review_result(),
        prior_review_context_used=False,
        same_sha_review=True,
        repair_allowed=False,
        reconciled_at=datetime(2026, 5, 1, 11, 0, 0),
        pipeline_version="review-staged-v1",
    )
    decision.dropped_candidates.append(
        DroppedCandidate(
            candidate_id="cand-2",
            drop_reason="duplicate",
            notes="Matched the accepted coverage finding.",
        )
    )

    artifact = PublishableReviewArtifact.from_reconciled_decision(
        decision,
        follow_up_lines=["Follow-up review after an earlier pass."],
    )

    assert artifact.classification == decision.review_classification
    assert artifact.summary == decision.decision_summary
    assert artifact.review_confidence == decision.confidence_level
    assert artifact.review_confidence_reason == decision.decision_rationale
    assert artifact.follow_up_lines == ["Follow-up review after an earlier pass."]
    assert len(artifact.findings) == 1
    assert artifact.findings[0].title == "Missing regression coverage"
    assert artifact.findings[0].evidence == (
        "The diff changes `value = 1` to `value = 2` without test updates."
    )
    assert artifact.findings[0].explanation == (
        "The branch behavior changes without regression coverage."
    )
    assert decision.dropped_candidates[0].drop_reason == "duplicate"


def test_artifact_validation_result_can_capture_repair_or_rejection_outcomes() -> None:
    artifact = PublishableReviewArtifact.from_reconciled_decision(
        ReconciledReviewDecision.from_review_result(
            build_review_result(),
            prior_review_context_used=False,
            same_sha_review=False,
            repair_allowed=True,
            reconciled_at=datetime(2026, 5, 1, 12, 0, 0),
            pipeline_version="review-staged-v1",
        )
    )

    validation_result = ArtifactValidationResult(
        status="repaired",
        issues=[
            ArtifactValidationIssue(
                rule_id="summary_contradicts_verdict",
                message="Summary wording was narrowed to match the final verdict.",
            )
        ],
        artifact=artifact,
    )

    assert validation_result.status == "repaired"
    assert validation_result.issues[0].rule_id == "summary_contradicts_verdict"
    assert validation_result.artifact is artifact

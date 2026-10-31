"""Offline review scenarios preserve final meaning across both provider paths."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from zeroone_ops.models.review import PrecisionReviewDecision
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.review.continuity.review_prior_comment_loader import (
    extract_machine_safe_review_note_payload,
)
from zeroone_ops.services.review.pipeline.review_artifact_builder import ReviewArtifactBuilder

from .provider_api import Platform, ScenarioProviderAPI
from .review_cases import REVIEW_PATH, ReviewCase, create_review_case
from .review_harness import ReviewHarness, compose_review_harness
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("scenario", ["retained-defect", "dropped-candidate", "request-isolation"])
def test_review_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform, scenario: str
) -> None:
    first = create_review_case(
        tmp_path, number=11, name="mr24" if scenario == "dropped-candidate" else "annotation"
    )
    cases = [first]
    if scenario == "request-isolation":
        cases.append(create_review_case(tmp_path, number=12, name="mr24"))
    api = ReviewProviderAPI(
        ScenarioProviderAPI(platform), cases={case.number: case for case in cases}
    )
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "review-state.json", monkeypatch)
        for case in cases:
            linked = harness.seed_link(case) if case.name == "annotation" else None
            sdk = ScriptedReviewSDK(
                case,
                linked_work_item=linked,
                forbidden_markers=tuple(other.marker for other in cases if other != case),
            )
            summary = harness.run(case, sdk)
            assert summary.status == RunStatus.REVIEWED, summary.message
            assert "warning" not in summary.message.lower(), summary.message
            assert_review_outputs(harness, case, sdk)
        state = harness.state_service.state_store.load()
        assert set(state.reviews) == {f"{case.number}:{case.head_sha}" for case in cases}
        assert len(state.runs) == len(cases)
        assert all(len(comments) == 1 for comments in api.comments.values())


def assert_review_outputs(harness: ReviewHarness, case: ReviewCase, sdk: ScriptedReviewSDK) -> None:
    """Compare actual native publication, serialized state, lineage, and projection."""
    state = harness.state_service.state_store.load()
    persisted = state.reviews[f"{case.number}:{case.head_sha}"]
    artifact = persisted.projection_artifact
    assert artifact is not None
    assert not persisted.projection_retry_pending
    assert persisted.projection_retry_warning is None
    note = next(iter(harness.api.comments[case.number].values()))
    payload = extract_machine_safe_review_note_payload(str(note["body"]))
    assert payload is not None
    assert payload["reviewed_change_request_number"] == case.number
    assert payload["reviewed_head_sha"] == case.head_sha
    assert payload["classification"] == persisted.status == artifact.classification
    assert persisted.note_id == note["id"]
    diagnostics = state.runs[-1].review_diagnostics
    assert diagnostics is not None and diagnostics.reviewed_head_sha == case.head_sha
    assert tuple(diagnostics.forwarded_candidate_ids) == sdk.candidate_ids
    assert [candidate.candidate_id for candidate in diagnostics.candidate_findings] == list(
        sdk.candidate_ids
    )
    assert diagnostics.final_classification == artifact.classification
    assert len(sdk.calls) == 2
    if case.name == "mr24":
        assert artifact.classification == "no_findings"
        assert not artifact.findings and persisted.findings_count == 0
        assert payload["findings_count"] == 0 and payload["findings"] == []
        assert not harness.api.inline_comments.get(case.number)
        assert not diagnostics.precision_accepted_candidate_ids
        assert not diagnostics.inline_comment_decisions
        assert not diagnostics.final_published_finding_summaries
        assert [
            candidate.candidate_id for candidate in diagnostics.precision_dropped_candidates
        ] == list(sdk.candidate_ids)
        assert diagnostics.precision_dropped_candidates[0].drop_reason == "unsupported_scope"
        assert case.finding.title not in str(note["body"])
    else:
        assert artifact.classification == "findings_present" and len(artifact.findings) == 1
        finding = artifact.findings[0]
        precision = sdk.calls[1].output
        assert isinstance(precision, PrecisionReviewDecision)
        expected = precision.accepted_findings[0]
        assert finding.severity == expected.severity
        assert finding.title == expected.title
        assert finding.file_path == expected.file_path == REVIEW_PATH
        assert finding.line_start == expected.line_start
        assert finding.line_end == expected.line_end
        assert finding.symbol == expected.symbol
        assert finding.issue_kind == expected.issue_kind
        assert finding.region_hint == expected.region_hint
        assert finding.evidence == expected.evidence[0]
        assert finding.explanation == expected.why_it_matters
        assert finding.suggested_follow_up == (expected.recommended_follow_up or "")
        assert payload["findings"][0]["severity"] == expected.severity
        assert payload["findings"][0]["identity"] == finding.stable_identity
        assert diagnostics.precision_accepted_candidate_ids == list(sdk.candidate_ids)
        assert not diagnostics.precision_dropped_candidates
        assert len(harness.api.inline_comments[case.number]) == 1
        inline = harness.api.inline_comments[case.number][0]
        assert case.finding.title in str(inline["body"])
        assert finding.inline_comment is not None and finding.inline_comment.status == "published"
        assert finding.inline_comment.comment_id == str(inline["id"])
        assert payload["findings"][0]["inline_comment"]["comment_id"] == str(inline["id"])
        assert len(diagnostics.inline_comment_decisions) == 1
        assert diagnostics.inline_comment_decisions[0].new_comment_id == str(inline["id"])
        assert case.finding.title in str(note["body"])
        assert expected.why_it_matters in str(note["body"])
        assert expected.recommended_follow_up in str(note["body"])
        assert "/zeroone remediation requeue" in str(note["body"])
        native = next(iter(harness.api.work_items.issues.values()))
        if harness.api.work_items.platform == "github":
            work_item = GitHubWorkItemParser().parse_work_item_state(str(native["body"]))
        else:
            work_item = GitLabWorkItemParser().parse_work_item_state(str(native["description"]))
        assert work_item.status == "review_feedback_required"
        projected = work_item.projected_review
        assert (
            projected.reviewed_sha == case.head_sha
            and projected.classification == artifact.classification
        )
        assert projected.feedback.finding_count == len(artifact.findings)
        assert projected.feedback.findings[0].title == finding.title
        assert projected.feedback.findings[0].file_path == finding.file_path
        assert projected.feedback.findings[0].line_start == finding.line_start
        assert projected.feedback.findings[0].line_end == finding.line_end
        assert projected.feedback.findings[0].evidence == finding.evidence
        assert projected.feedback.findings[0].explanation == finding.explanation
        assert projected.feedback.findings[0].suggested_follow_up == finding.suggested_follow_up
        assert projected.review_note_url == persisted.note_url
        assert work_item.batch_attempt == sdk.linked_work_item.batch_attempt


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("severity", "medium"),
        ("evidence", "Corrupted evidence"),
        ("explanation", "Corrupted impact"),
        ("suggested_follow_up", "Corrupted recommendation"),
    ],
)
def test_review_assertions_reject_changed_final_meaning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: Platform,
    field: str,
    replacement: str,
) -> None:
    original_build = ReviewArtifactBuilder.build

    def corrupt_artifact(self, **arguments):
        built = original_build(self, **arguments)
        return replace(
            built,
            artifact=built.artifact.model_copy(
                update={
                    "findings": [
                        finding.model_copy(update={field: replacement})
                        for finding in built.artifact.findings
                    ]
                }
            ),
        )

    monkeypatch.setattr(ReviewArtifactBuilder, "build", corrupt_artifact)
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        summary = harness.run(case, sdk)
        assert summary.status == RunStatus.REVIEWED
        with pytest.raises(AssertionError):
            assert_review_outputs(harness, case, sdk)

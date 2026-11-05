"""Overview-only evidence survives publication and recovery without becoming active."""

from pathlib import Path

import httpx
import pytest

from zeroone_ops.models.review import (
    DroppedCandidate,
    OverlapReconciliationResult,
    OverlapResolution,
    PrecisionReviewDecision,
)
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.review.publish.review_overview_codec import decode_overview

from .provider_api import Platform, ScenarioProviderAPI
from .review_cases import advance_review_case, create_review_case
from .review_harness import compose_review_harness
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "recovery",
    [
        "reuse",
        "fresh",
        "repair",
        "restore",
        "failure",
        "restore-new-head",
        "restore-new-head-no-cache",
    ],
)
def test_overview_only_concern_survives_unreported_pass_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform, recovery: str
) -> None:
    first = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={first.number: first})
    projection_unavailable = False

    def respond(request: httpx.Request) -> httpx.Response:
        if (
            projection_unavailable
            and request.method in {"PATCH", "PUT"}
            and request.url.path.endswith("/issues/1")
        ):
            return httpx.Response(503, json={"message": "Projection unavailable"})
        return api.respond(request)

    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        harness.inline_comments_enabled = False
        linked = harness.seed_link(first)
        first_sdk = ScriptedReviewSDK(first, linked_work_item=linked)
        assert harness.run(first, first_sdk).status == RunStatus.REVIEWED
        assert not api.inline_comments

        second = advance_review_case(
            first, after=first.after + "\n# Another reviewed change.\n", finding=first.finding
        )
        api.cases[second.number] = second
        second_sdk = ScriptedReviewSDK(
            second,
            linked_work_item=linked,
            prior_case=first,
            precision_result=PrecisionReviewDecision(
                review_classification="no_findings",
                decision_summary="No finding retained.",
                decision_rationale="This pass does not retain the earlier candidate.",
                dropped_candidates=[
                    DroppedCandidate(candidate_id="candidate-1", drop_reason="weak_evidence")
                ],
            ),
            overlap_result=OverlapReconciliationResult(
                prior_reviewed_head_sha=first.head_sha,
                resolutions=[OverlapResolution(outcome="no_longer_present", prior_finding_index=0)],
            ),
        )
        projection_unavailable = recovery == "repair"
        assert harness.run(second, second_sdk).status == RunStatus.REVIEWED
        note = next(iter(api.comments[second.number].values()))
        overview = decode_overview(str(note["body"]))
        archive = overview.earlier_findings
        assert len(archive.concerns) == 1
        earlier = archive.concerns[0]
        assert earlier.head_sha == first.head_sha
        assert earlier.finding.evidence == first.finding.evidence
        assert earlier.finding.title == first.finding.title
        assert overview.complete_passes[0].artifact.findings == []
        assert overview.complete_passes[0].artifact.classification == "no_findings"
        assert "**Active findings:** 0" in str(note["body"])
        assert "<summary>Earlier Findings</summary>" in str(note["body"])
        assert "Resolution not verified" in str(note["body"])
        key = f"{second.number}:{second.head_sha}"
        saved = harness.state_service.state_store.load().reviews[key]
        assert saved.earlier_findings == archive
        assert saved.findings == [] and saved.projection_artifact.findings == []
        assert saved.projection_retry_pending is (recovery == "repair")
        assert len(first_sdk.calls) == 2 and len(second_sdk.calls) == 3

        projection_unavailable = False
        if recovery.startswith("restore-new-head"):
            api.comments[second.number].clear()
            if recovery == "restore-new-head-no-cache":
                harness = compose_review_harness(api, http, tmp_path / "empty.json", monkeypatch)
            third = advance_review_case(
                second,
                after=second.after + "\n# New head after deletion.\n",
                finding=second.finding,
            )
            api.cases[third.number] = third
            third_sdk = ScriptedReviewSDK(
                third, linked_work_item=linked, precision_result=second_sdk.precision_result
            )
            assert harness.run(third, third_sdk).status == RunStatus.REVIEWED
            body = str(next(iter(api.comments[third.number].values()))["body"])
            recreated = decode_overview(body)
            if recovery == "restore-new-head":
                assert recreated.earlier_findings == archive
                assert recreated.history[0].sequence == 3
                assert recreated.complete_passes[1] == overview.complete_passes[0]
            else:
                assert recreated.earlier_findings.concerns == ()
                assert recreated.earlier_findings.history_unavailable
                assert "Deleted history, if any" in body
            assert recreated.complete_passes[0].head_sha == third.head_sha
            assert recreated.complete_passes[0].artifact.findings == []
            saved = harness.state_service.state_store.load().reviews[
                f"{third.number}:{third.head_sha}"
            ]
            assert saved.earlier_findings == recreated.earlier_findings
            assert len(third_sdk.calls) == 2
            assert len(api.comments[third.number]) == 1
            assert not api.inline_comments
            return
        if recovery in {"fresh", "repair"}:
            harness = compose_review_harness(api, http, tmp_path / "fresh.json", monkeypatch)
        elif recovery == "restore":
            api.comments[second.number].clear()
        elif recovery == "failure":
            third = advance_review_case(
                second, after=second.after + "\n# Failed review.\n", finding=second.finding
            )
            api.cases[third.number] = third
            failed_sdk = ScriptedReviewSDK(third, linked_work_item=linked, fail_candidate=True)
            assert harness.run(third, failed_sdk).status == RunStatus.FAILED
            assert len(failed_sdk.calls) == 1

        if recovery != "failure":
            assert harness.run(second, second_sdk).status == RunStatus.REVIEWED
            saved = harness.state_service.state_store.load().reviews[key]
            assert saved.earlier_findings == archive
            assert not saved.projection_retry_pending
        final = decode_overview(str(next(iter(api.comments[second.number].values()))["body"]))
        assert final.earlier_findings == archive
        assert final.complete_passes[0].artifact == overview.complete_passes[0].artifact
        assert len(api.comments[second.number]) == 1
        assert not api.inline_comments
        assert len(first_sdk.calls) == 2 and len(second_sdk.calls) == 3

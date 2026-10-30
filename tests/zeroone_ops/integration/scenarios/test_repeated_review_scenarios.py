"""Repeated reviews use the latest published pass without conflating new defects."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from zeroone_ops.models.review import (
    OverlapReconciliationResult,
    OverlapResolution,
    PrecisionReviewDecision,
)
from zeroone_ops.models.state import ChangeRequestReviewState, RunStatus
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers import llm_client
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.review.continuity.review_prior_comment_loader import (
    extract_machine_safe_review_note_payload,
)

from .provider_api import Platform, ScenarioProviderAPI
from .repository import git
from .review_cases import REVIEW_PATH, ReviewCase, advance_review_case, create_review_case
from .review_harness import ReviewHarness, compose_review_harness
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_repeated_review_tracks_unresolved_resolved_and_new_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    first = create_review_case(tmp_path, number=11, name="annotation")
    first = replace(
        first,
        finding=first.finding.model_copy(
            update={
                "symbol": "present",
                "issue_kind": "undefined_annotation",
                "region_hint": "function signature",
            }
        ),
    )
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={first.number: first})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        linked = harness.seed_link(first)
        first_sdk = ScriptedReviewSDK(first, linked_work_item=linked)
        assert harness.run(first, first_sdk).status == RunStatus.REVIEWED
        first_review = harness.state_service.state_store.load().reviews[
            f"{first.number}:{first.head_sha}"
        ]

        second = _shift_unresolved_case(first)
        api.cases[first.number] = second
        unresolved = OverlapReconciliationResult(
            prior_reviewed_head_sha=first.head_sha,
            resolutions=[
                OverlapResolution(
                    outcome="still_unresolved", current_finding_index=0, prior_finding_index=0
                )
            ],
        )
        second_sdk = ScriptedReviewSDK(
            second, linked_work_item=linked, prior_case=first, overlap_result=unresolved
        )
        summary = harness.run(second, second_sdk)
        assert summary.status == RunStatus.REVIEWED and "warning" not in summary.message.lower()
        second_review = harness.state_service.state_store.load().reviews[
            f"{second.number}:{second.head_sha}"
        ]

        third = _replace_defect_case(second)
        api.cases[first.number] = third
        replaced = OverlapReconciliationResult(
            prior_reviewed_head_sha=second.head_sha,
            resolutions=[
                OverlapResolution(outcome="new_in_this_pass", current_finding_index=0),
                OverlapResolution(outcome="no_longer_present", prior_finding_index=0),
            ],
        )
        third_sdk = ScriptedReviewSDK(
            third, linked_work_item=linked, prior_case=second, overlap_result=replaced
        )
        summary = harness.run(third, third_sdk)
        assert summary.status == RunStatus.REVIEWED and "warning" not in summary.message.lower()

        assert git(third.root, "rev-parse", "HEAD^") == second.head_sha
        assert git(third.root, "rev-parse", "HEAD^^") == first.head_sha
        state = harness.state_service.state_store.load()
        cases = (first, second, third)
        reviews = [first_review, second_review, state.reviews[f"{third.number}:{third.head_sha}"]]
        assert set(state.reviews) == {f"{case.number}:{case.head_sha}" for case in (second, third)}
        assert len(state.runs) == len(api.comments[first.number]) == 3
        assert len({run.run_id for run in state.runs}) == 3
        for case, sdk, review in zip(
            cases, (first_sdk, second_sdk, third_sdk), reviews, strict=True
        ):
            _assert_published_pass(api, case, sdk, review)
        _assert_continuity(api, cases, reviews)
        _assert_latest_projection(harness, third, reviews[-1], linked)
        diagnostics = [run.review_diagnostics for run in state.runs]
        assert [diagnostic.reviewed_head_sha for diagnostic in diagnostics] == [
            case.head_sha for case in cases
        ]


def _shift_unresolved_case(first: ReviewCase) -> ReviewCase:
    return advance_review_case(
        first,
        after=first.after.replace("def present", "# Keep the public entry point.\ndef present"),
        finding=first.finding.model_copy(
            update={
                "title": "Missing annotation type still prevents import",
                "line_start": first.finding.line_start + 1,
                "line_end": first.finding.line_end + 1,
            }
        ),
    )


def _replace_defect_case(previous: ReviewCase) -> ReviewCase:
    return advance_review_case(
        previous,
        after=(
            f"# {previous.marker}\n"
            "def present(value: int):\n    return value\n\n\n"
            "def render(value: OtherType):\n    return value\n"
        ),
        finding=previous.finding.model_copy(
            update={
                "symbol": "render",
                "title": "New render annotation prevents import",
                "line_start": 6,
                "line_end": 6,
                "evidence": previous.finding.evidence.replace("MissingType", "OtherType"),
            }
        ),
    )


def _assert_published_pass(
    api: ReviewProviderAPI,
    case: ReviewCase,
    sdk: ScriptedReviewSDK,
    review: ChangeRequestReviewState,
) -> None:
    """Check each persisted artifact against its independent precision response and native note."""
    assert not review.projection_retry_pending and review.projection_retry_warning is None
    artifact = review.projection_artifact
    assert artifact is not None and len(artifact.findings) == 1
    finding = artifact.findings[0]
    precision = sdk.calls[1].output
    assert isinstance(precision, PrecisionReviewDecision)
    expected = precision.accepted_findings[0]
    assert finding.title == expected.title == case.finding.title
    assert finding.evidence == expected.evidence[0] == case.finding.evidence
    assert finding.severity == expected.severity
    assert finding.explanation == expected.why_it_matters
    assert finding.suggested_follow_up == expected.recommended_follow_up
    assert (finding.line_start, finding.line_end) == (expected.line_start, expected.line_end)
    note = api.comments[case.number][review.note_id]
    payload = extract_machine_safe_review_note_payload(str(note["body"]))
    assert payload["reviewed_head_sha"] == case.head_sha
    assert payload["findings"][0]["identity"] == finding.stable_identity
    assert payload["findings"][0]["title"] == case.finding.title
    assert (
        payload["findings"][0]["inline_comment"]["comment_id"] == finding.inline_comment.comment_id
    )
    assert finding.title in str(note["body"])
    assert len(sdk.calls) == sdk.expected_call_count


def _assert_continuity(
    api: ReviewProviderAPI, cases: tuple[ReviewCase, ...], reviews: list[ChangeRequestReviewState]
) -> None:
    """Preserve one unresolved concern while distinguishing the later replacement defect."""
    artifacts = [review.projection_artifact for review in reviews]
    findings = [artifact.findings[0] for artifact in artifacts]
    assert [finding.continuity_status for finding in findings] == [None, "unresolved", "new"]
    assert findings[0].stable_identity == findings[1].stable_identity
    assert findings[2].stable_identity != findings[1].stable_identity
    assert findings[1].line_start != findings[0].line_start
    assert findings[1].title != findings[0].title
    assert findings[1].inline_comment.comment_id == findings[0].inline_comment.comment_id
    assert findings[2].inline_comment.comment_id != findings[1].inline_comment.comment_id
    assert len(api.inline_comments[cases[0].number]) == 2
    assert cases[0].head_sha in " ".join(artifacts[1].follow_up_lines)
    assert cases[1].head_sha in " ".join(artifacts[2].follow_up_lines)
    assert any("unresolved" in line for line in artifacts[1].follow_up_lines)
    assert any("no longer" in line for line in artifacts[2].follow_up_lines)
    assert any("new" in line.lower() for line in artifacts[2].follow_up_lines)
    latest_body = str(api.comments[cases[0].number][reviews[-1].note_id]["body"])
    assert "1 new finding, 1 resolved finding" in latest_body


def _assert_latest_projection(
    harness: ReviewHarness,
    case: ReviewCase,
    review: ChangeRequestReviewState,
    linked: WorkItemState,
) -> None:
    native = next(iter(harness.api.work_items.issues.values()))
    github = harness.api.work_items.platform == "github"
    parser = GitHubWorkItemParser() if github else GitLabWorkItemParser()
    projected = parser.parse_work_item_state(
        str(native["body"] if github else native["description"])
    )
    assert projected.status == "review_feedback_required"
    assert projected.projected_review.reviewed_sha == case.head_sha
    assert projected.projected_review.feedback.findings[0].title == case.finding.title
    assert projected.projected_review.feedback.findings[0].file_path == REVIEW_PATH
    assert projected.projected_review.review_note_url == review.note_url
    assert projected.batch_attempt == linked.batch_attempt


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_repeated_review_rejects_missing_precision_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    first = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={first.number: first})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        assert harness.run(first, ScriptedReviewSDK(first)).status == RunStatus.REVIEWED
        original_notes = {key: dict(value) for key, value in api.comments[first.number].items()}
        second = _shift_unresolved_case(first)
        api.cases[first.number] = second
        original_prompt = llm_client.build_review_precision_prompt

        def omit_history(context, **arguments):
            return original_prompt(
                context.model_copy(update={"prior_review_context": None}), **arguments
            )

        monkeypatch.setattr(llm_client, "build_review_precision_prompt", omit_history)
        sdk = ScriptedReviewSDK(second, prior_case=first)
        with pytest.raises(pytest.fail.Exception, match="Latest prior review pass"):
            harness.run(second, sdk)
        assert len(sdk.calls) == 1
        assert api.comments[first.number] == original_notes
        assert len(api.inline_comments[first.number]) == 1
        assert set(harness.state_service.state_store.load().reviews) == {
            f"{first.number}:{first.head_sha}"
        }

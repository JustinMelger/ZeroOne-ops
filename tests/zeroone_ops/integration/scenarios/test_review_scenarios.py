"""Offline review scenarios preserve final meaning across both provider paths."""

import json
from copy import deepcopy
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
from zeroone_ops.services.review.pipeline.review_artifact_builder import ReviewArtifactBuilder
from zeroone_ops.services.review.publish.review_overview_codec import decode_overview

from .provider_api import Platform, ScenarioProviderAPI
from .repository import git
from .review_cases import REVIEW_PATH, ReviewCase, advance_review_case, create_review_case
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


def test_github_installation_identity_supports_review_publication_and_same_sha_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI("github"), cases={case.number: case})
    identity_calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "provider.invalid"
        if request.url.path == "/user":
            assert request.method == "GET"
            identity_calls.append(("GET", "/user"))
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        if request.url.path == "/graphql":
            assert request.method == "POST"
            assert json.loads(request.content) == {"query": "query { viewer { login } }"}
            identity_calls.append(("POST", "/graphql"))
            return httpx.Response(200, json={"data": {"viewer": {"login": "offline-bot"}}})
        return api.respond(request)

    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        summary = harness.run(case, sdk)
        assert summary.status == RunStatus.REVIEWED, summary.message
        assert_review_outputs(harness, case, sdk)
        comments = deepcopy(api.comments)
        inline = deepcopy(api.inline_comments)
        writes_before = len(api.work_items.issue_writes)

        repeated = harness.run(case, sdk)

        assert repeated.status == RunStatus.REVIEWED
        assert "No new changes after the last review" in repeated.message
        assert len(sdk.calls) == 2
        assert api.comments == comments and api.inline_comments == inline
        assert len(api.work_items.issue_writes) == writes_before
        assert len(identity_calls) >= 4 and len(identity_calls) % 2 == 0
        assert identity_calls == [("GET", "/user"), ("POST", "/graphql")] * (
            len(identity_calls) // 2
        )


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_commit_metadata_outage_preserves_review_and_does_not_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(
        ScenarioProviderAPI(platform), cases={case.number: case}, commit_status=503
    )
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "review-state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))

        result = harness.run(case, sdk)

        assert result.status == RunStatus.REVIEWED, result.message
        note = next(iter(api.comments[case.number].values()))
        overview = decode_overview(str(note["body"]))
        assert overview.complete_passes[0].reviewed_commit is None
        assert len(overview.complete_passes[0].artifact.findings) == 1
        assert api.commit_calls == [(case.number, case.head_sha)]
        assert len(sdk.calls) == 2
        comments = deepcopy(api.comments)
        inline = deepcopy(api.inline_comments)
        api.commit_status = 200

        repeated = harness.run(case, sdk)

        assert repeated.status == RunStatus.REVIEWED
        assert api.commit_calls == [(case.number, case.head_sha)]
        assert api.comments == comments and api.inline_comments == inline
        assert len(sdk.calls) == 2


def assert_review_outputs(harness: ReviewHarness, case: ReviewCase, sdk: ScriptedReviewSDK) -> None:
    """Compare actual native publication, serialized state, lineage, and projection."""
    state = harness.state_service.state_store.load()
    persisted = state.reviews[f"{case.number}:{case.head_sha}"]
    artifact = persisted.projection_artifact
    assert artifact is not None
    assert not persisted.projection_retry_pending
    assert persisted.projection_retry_warning is None
    note = next(iter(harness.api.comments[case.number].values()))
    overview = decode_overview(str(note["body"]))
    assert overview is not None
    assert overview.change_request_number == case.number
    completed = overview.complete_passes[0]
    assert completed.head_sha == case.head_sha
    assert harness.api.commit_calls.count((case.number, case.head_sha)) == 1
    assert completed.reviewed_commit is not None
    assert completed.reviewed_commit.head_sha == case.head_sha
    assert completed.reviewed_commit.title == git(
        case.root, "show", "-s", "--format=%s", case.head_sha
    )
    assert persisted.overview_pass.reviewed_commit == completed.reviewed_commit
    assert all(completed.reviewed_commit.title not in call.prompt for call in sdk.calls)
    assert completed.artifact == artifact
    assert not completed.projection_pending
    assert len(overview.history) == len(overview.complete_passes) == 1
    assert completed.pass_id == persisted.review_pass_id
    assert completed.artifact.classification == persisted.status == artifact.classification
    writes = [decode_overview(body) for body in harness.api.overview_writes]
    writes = [entry for entry in writes if entry.change_request_number == case.number]
    assert all(
        entry.complete_passes[0].reviewed_commit == completed.reviewed_commit for entry in writes
    )
    assert len(writes) >= 2
    assert all(entry.history == overview.history for entry in writes)
    assert writes[0].complete_passes[0].projection_pending
    assert not writes[-1].complete_passes[0].projection_pending
    if artifact.findings:
        assert writes[0].complete_passes[0].artifact.findings[0].inline_comment is None
        assert any(
            entry.complete_passes[0].artifact.findings[0].inline_comment is not None
            and entry.complete_passes[0].artifact.findings[0].inline_comment.comment_id
            for entry in writes[1:]
        )
        github = harness.api.work_items.platform == "github"
        overview_path = (
            f"/issues/{case.number}/comments" if github else f"/merge_requests/{case.number}/notes"
        )
        inline_path = (
            f"/pulls/{case.number}/comments"
            if github
            else f"/merge_requests/{case.number}/discussions"
        )
        publications = [path for method, path in harness.api.calls if method == "POST"]
        overview_index = next(
            index for index, path in enumerate(publications) if path.endswith(overview_path)
        )
        inline_index = next(
            index for index, path in enumerate(publications) if path.endswith(inline_path)
        )
        assert overview_index < inline_index
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
        assert not completed.artifact.findings
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
        assert completed.artifact.findings[0].severity == expected.severity
        assert completed.artifact.findings[0].stable_identity == finding.stable_identity
        assert diagnostics.precision_accepted_candidate_ids == list(sdk.candidate_ids)
        assert not diagnostics.precision_dropped_candidates
        assert len(harness.api.inline_comments[case.number]) == 1
        inline = harness.api.inline_comments[case.number][0]
        assert case.finding.title in str(inline["body"])
        assert finding.inline_comment is not None and finding.inline_comment.status == "published"
        assert finding.inline_comment.comment_id == str(inline["id"])
        assert completed.artifact.findings[0].inline_comment.comment_id == str(inline["id"])
        assert len(diagnostics.inline_comment_decisions) == 1
        assert diagnostics.inline_comment_decisions[0].new_comment_id == str(inline["id"])
        assert case.finding.title in str(note["body"])
        assert expected.why_it_matters in str(note["body"])
        assert expected.recommended_follow_up in str(note["body"])
        assert "Address the active findings and rerun review." in str(note["body"])
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


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("completed_review", [False, True])
def test_handled_review_failure_only_updates_existing_execution_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform, completed_review: bool
) -> None:
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        original = None
        linked = harness.seed_link(case)
        if completed_review:
            assert harness.run(case, ScriptedReviewSDK(case, linked_work_item=linked)).status == (
                RunStatus.REVIEWED
            )
            original_note = next(iter(api.comments[case.number].values()))
            original = decode_overview(str(original_note["body"]))
            assert original is not None
            case = advance_review_case(
                case,
                after=f"{case.after}\n# Attempt another review.\n",
                finding=case.finding.model_copy(deep=True),
            )
            api.cases[case.number] = case
        reviews_before = deepcopy(harness.state_service.state_store.load().reviews)
        inline_before = deepcopy(api.inline_comments)
        issues_before = deepcopy(api.work_items.issues)
        writes_before = len(api.work_items.issue_writes)
        overview_writes_before = len(api.overview_writes)
        sdk = ScriptedReviewSDK(case, linked_work_item=linked, fail_candidate=True)

        summary = harness.run(case, sdk)

        assert summary.status == RunStatus.FAILED
        assert len(sdk.calls) == sdk.expected_call_count == 1
        assert sdk.calls[0].output is None
        saved = harness.state_service.state_store.load()
        assert saved.runs[-1].status == RunStatus.FAILED
        assert saved.reviews == reviews_before
        assert api.inline_comments == inline_before
        assert api.work_items.issues == issues_before
        assert len(api.work_items.issue_writes) == writes_before
        if original is None:
            assert not any(api.comments.values())
            assert len(api.overview_writes) == overview_writes_before
        else:
            assert len(api.comments[case.number]) == 1
            note = next(iter(api.comments[case.number].values()))
            overview = decode_overview(str(note["body"]))
            assert overview is not None
            assert note["id"] == original_note["id"]
            assert overview.complete_passes == original.complete_passes
            assert overview.history == original.history
            assert overview.execution_notice is not None
            assert case.head_sha in overview.execution_notice
            assert "failed during review_analysis" in overview.execution_notice
            assert "Scripted offline review SDK outage" not in overview.execution_notice
            assert original.complete_passes[0].head_sha in str(note["body"])
            assert len(api.overview_writes) == overview_writes_before + 1

"""Exercise same-SHA reuse and recoverable projection over native offline HTTP."""

from copy import deepcopy

import httpx
import pytest

from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.review.publish.review_overview_codec import (
    decode_overview,
    encode_overview,
)

from .provider_api import Platform, ScenarioProviderAPI
from .review_cases import advance_review_case, create_review_case
from .review_harness import compose_review_harness
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("conflict", ["duplicate", "malformed", "scope", "unavailable", "identity"])
def test_unverified_overview_withholds_pending_projection_until_authority_recovers(
    tmp_path, monkeypatch, platform: Platform, conflict: str
):
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    fail_projection = True
    unavailable = False
    identity_unavailable = False

    def respond(request: httpx.Request) -> httpx.Response:
        if (
            fail_projection
            and request.method in {"PATCH", "PUT"}
            and request.url.path.endswith("/issues/1")
        ):
            return httpx.Response(503, json={"message": "Projection unavailable"})
        if (
            unavailable
            and request.method == "GET"
            and request.url.path.endswith(("/comments", "/notes"))
        ):
            return httpx.Response(503, json={"message": "Overview unavailable"})
        if identity_unavailable and request.url.path.endswith("/user"):
            return httpx.Response(503, json={"message": "Identity unavailable"})
        return api.respond(request)

    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        assert harness.run(case, sdk).status.value == "reviewed"
        key = f"{case.number}:{case.head_sha}"
        assert harness.state_service.state.reviews[key].projection_retry_pending
        healthy_comments = deepcopy(api.comments)
        note = next(iter(api.comments[case.number].values()))
        if conflict == "duplicate":
            duplicate = deepcopy(note)
            duplicate["id"] = int(note["id"]) + 100
            api.comments[case.number][duplicate["id"]] = duplicate
        elif conflict == "malformed":
            note["body"] = "<!-- zeroone:review-overview:v1\ninvalid -->"
        elif conflict == "scope":
            overview = decode_overview(str(note["body"]))
            note["body"] = encode_overview(
                overview.model_copy(update={"repository_id": "other/repo"})
            )
        unavailable = conflict == "unavailable"
        identity_unavailable = conflict == "identity"
        fail_projection = False
        comments = deepcopy(api.comments)
        issues = deepcopy(api.work_items.issues)
        inline = deepcopy(api.inline_comments)
        writes_before = len(api.work_items.issue_writes)
        calls_before = len(api.calls)

        blocked = harness.run(case, sdk)

        assert blocked.status.value == "failed"
        assert "Review overview unavailable" in blocked.message
        assert len(sdk.calls) == 2
        assert api.comments == comments and api.inline_comments == inline
        assert api.work_items.issues == issues
        assert len(api.work_items.issue_writes) == writes_before
        assert all(method == "GET" for method, _ in api.calls[calls_before:])
        saved = harness.state_service.state_store.load().reviews[key]
        assert saved.projection_retry_pending
        assert (
            saved.projection_artifact
            == harness.state_service.state.reviews[key].projection_artifact
        )

        api.comments = healthy_comments
        unavailable = identity_unavailable = False
        recovered = harness.run(case, sdk)

        assert recovered.status.value == "reviewed"
        assert "Repaired pending review projection" in recovered.message
        assert len(sdk.calls) == 2
        assert not harness.state_service.state_store.load().reviews[key].projection_retry_pending
        assert len(api.work_items.issue_writes) == writes_before + 1


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_authority_conflict_while_loading_prior_context_stops_before_model_calls(
    tmp_path, monkeypatch, platform: Platform
):
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    conflict_enabled = False
    comment_reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal comment_reads
        response = api.respond(request)
        if (
            conflict_enabled
            and request.method == "GET"
            and request.url.path.endswith(("/comments", "/notes"))
        ):
            comment_reads += 1
            if comment_reads >= 3:
                notes = response.json()
                duplicate = deepcopy(notes[0])
                duplicate["id"] += 100
                return httpx.Response(200, json=[*notes, duplicate])
        return response

    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        assert harness.run(case, sdk).status.value == "reviewed"
        following = advance_review_case(
            case, after=case.after + "\n# Next pinned review head.\n", finding=case.finding
        )
        api.cases[case.number] = following
        conflict_enabled = True
        comments = deepcopy(api.comments)
        issues = deepcopy(api.work_items.issues)
        inline = deepcopy(api.inline_comments)

        blocked = harness.run(following, sdk)

        assert blocked.status.value == "failed"
        assert "Multiple verified review overviews" in blocked.message
        assert comment_reads >= 3 and len(sdk.calls) == 2
        assert api.comments == comments and api.inline_comments == inline
        assert api.work_items.issues == issues


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "reference", ["state", "comment", "fresh", "stale", "repair", "fresh-repair"]
)
def test_same_sha_review_reuses_publication_and_repairs_only_projection(
    tmp_path, monkeypatch, platform: Platform, reference: str
):
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    fail_projection = reference in {"repair", "fresh-repair"}
    failed_updates = []

    def respond(request: httpx.Request) -> httpx.Response:
        if (
            fail_projection
            and request.method in {"PATCH", "PUT"}
            and request.url.path.endswith("/issues/1")
        ):
            failed_updates.append(request.url.path)
            return httpx.Response(503, json={"message": "Temporary projection outage"})
        return api.respond(request)

    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        linked = harness.seed_link(case)
        sdk = ScriptedReviewSDK(case, linked_work_item=linked)
        first = harness.run(case, sdk)
        key = f"{case.number}:{case.head_sha}"
        published = deepcopy(api.comments)
        overview = decode_overview(str(next(iter(published[case.number].values()))["body"]))
        assert overview is not None
        inline = deepcopy(api.inline_comments)
        assert api.commit_calls == [(case.number, case.head_sha)]
        commit_metadata = overview.complete_passes[0].reviewed_commit
        assert commit_metadata is not None
        change_summary = overview.complete_passes[0].artifact.change_summary
        assert change_summary == sdk.change_summary
        assert change_summary is not None
        artifact = harness.state_service.state.reviews[key].projection_artifact.model_copy(
            deep=True
        )
        assert first.status.value == "reviewed"
        if reference == "comment":
            harness.state_service.state.reviews.clear()
            harness.state_service.state_store.save(harness.state_service.state)
        if reference == "stale":
            review = harness.state_service.state.reviews[key]
            harness.state_service.state.reviews[key] = review.model_copy(
                update={
                    "note_id": -1,
                    "note_url": "https://provider.invalid/stale",
                    "projection_artifact": artifact.model_copy(
                        update={"summary": "Stale local review summary"}
                    ),
                }
            )
            harness.state_service.state_store.save(harness.state_service.state)
        if reference in {"fresh", "fresh-repair"}:
            harness = compose_review_harness(api, http, tmp_path / "fresh-state.json", monkeypatch)
        if reference in {"repair", "fresh-repair"}:
            assert failed_updates
            assert overview.complete_passes[0].projection_pending
            repeated = harness.run(case, sdk)
            assert "Review projection warning:" in repeated.message
            assert harness.state_service.state_store.load().reviews[key].projection_retry_pending
            fail_projection = False

        writes_before = len(api.work_items.issue_writes)
        calls_before = len(api.calls)
        summary = harness.run(case, sdk)

        assert summary.status.value == "reviewed"
        assert "No new changes after the last review" in summary.message
        assert len(sdk.calls) == 2
        repaired_overview = decode_overview(
            str(next(iter(api.comments[case.number].values()))["body"])
        )
        assert repaired_overview is not None
        assert api.commit_calls == [(case.number, case.head_sha)]
        assert repaired_overview.complete_passes[0].reviewed_commit == commit_metadata
        assert repaired_overview.complete_passes[0].artifact.change_summary == change_summary
        assert (
            repaired_overview.complete_passes[0].artifact.review_scope_limited
            == overview.complete_passes[0].artifact.review_scope_limited
        )
        assert repaired_overview.history == overview.history
        assert repaired_overview.complete_passes[0].pass_id == overview.complete_passes[0].pass_id
        assert len(api.comments[case.number]) == 1
        if reference not in {"repair", "fresh-repair"}:
            assert api.comments == published
        assert api.inline_comments == inline
        assert all(method == "GET" for method, _ in api.calls[calls_before:]) or reference in {
            "repair",
            "fresh-repair",
        }
        saved = harness.state_service.state_store.load()
        assert saved.runs[-1].status.value == "reviewed"
        mirrored = saved.reviews[key]
        assert mirrored.note_id == next(iter(api.comments[case.number]))
        assert mirrored.review_pass_id == overview.complete_passes[0].pass_id
        assert mirrored.overview_pass.reviewed_commit == commit_metadata
        assert mirrored.overview_pass.artifact.change_summary == change_summary
        assert mirrored.projection_artifact == artifact
        if reference in {"repair", "fresh-repair"}:
            assert "Repaired pending review projection." in summary.message
            repaired = saved.reviews[key]
            assert not repaired.projection_retry_pending
            assert repaired.projection_retry_warning is None
            assert repaired.projection_artifact == artifact
            assert not repaired_overview.complete_passes[0].projection_pending
            assert len(api.work_items.issue_writes) == writes_before + 1
            body = str(
                api.work_items.issues[1].get("body", api.work_items.issues[1].get("description"))
            )
            assert case.head_sha in body
            assert "review_feedback_required" in body
        else:
            assert len(api.work_items.issue_writes) == writes_before


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_deleted_overview_restores_receipt_without_restarting_review_action(
    tmp_path, monkeypatch, platform: Platform
):
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        state_path = tmp_path / "state.json"
        harness = compose_review_harness(api, http, state_path, monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        assert harness.run(case, sdk).status.value == "reviewed"
        original_note = next(iter(api.comments[case.number].values()))
        original = decode_overview(str(original_note["body"]))
        assert original is not None
        assert original.complete_passes[0].reviewed_commit is not None
        assert api.commit_calls == [(case.number, case.head_sha)]
        parser = GitHubWorkItemParser() if platform == "github" else GitLabWorkItemParser()
        body_field = "body" if platform == "github" else "description"
        before = parser.parse_work_item_state(str(api.work_items.issues[1][body_field]))
        assert before.review_action_required_at is not None
        inline = deepcopy(api.inline_comments)
        writes_before = len(api.work_items.issue_writes)
        overview_writes_before = len(api.overview_writes)
        api.comments[case.number].clear()

        harness = compose_review_harness(api, http, state_path, monkeypatch)
        summary = harness.run(case, sdk)

        assert summary.status.value == "reviewed", summary.message
        assert "No new changes after the last review" in summary.message
        assert "Repaired pending review projection." in summary.message
        assert "warning" not in summary.message.lower()
        assert len(sdk.calls) == 2
        assert api.inline_comments == inline
        assert len(api.comments[case.number]) == 1
        note = next(iter(api.comments[case.number].values()))
        assert note["id"] != original_note["id"]
        restored = decode_overview(str(note["body"]))
        assert restored == original
        assert api.commit_calls == [(case.number, case.head_sha)]
        staged = decode_overview(api.overview_writes[overview_writes_before])
        assert staged.complete_passes[0].projection_pending
        assert staged.history == original.history
        saved = harness.state_service.state_store.load().reviews[f"{case.number}:{case.head_sha}"]
        assert saved.note_id == note["id"]
        assert saved.review_pass_id == original.complete_passes[0].pass_id
        assert saved.overview_pass.reviewed_commit == original.complete_passes[0].reviewed_commit
        assert not saved.projection_retry_pending
        after = parser.parse_work_item_state(str(api.work_items.issues[1][body_field]))
        assert after.status == before.status
        assert after.review_action_required_at == before.review_action_required_at
        assert after.review_revision_request == before.review_revision_request
        assert after.batch_attempt == before.batch_attempt
        assert after.projected_review == before.projected_review.model_copy(
            update={"review_note_url": saved.note_url}
        )
        assert len(api.work_items.issue_writes) == writes_before + 1
        writes_after_repair = len(api.overview_writes)
        assert harness.run(case, sdk).status.value == "reviewed"
        assert len(api.overview_writes) == writes_after_repair
        assert len(api.work_items.issue_writes) == writes_before + 1
        assert api.inline_comments == inline and len(sdk.calls) == 2

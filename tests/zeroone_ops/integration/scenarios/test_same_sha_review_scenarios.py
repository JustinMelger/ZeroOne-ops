"""Exercise same-SHA reuse and recoverable projection over native offline HTTP."""

from copy import deepcopy

import httpx
import pytest

from .provider_api import Platform, ScenarioProviderAPI
from .review_cases import create_review_case
from .review_harness import compose_review_harness
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("reference", ["state", "comment", "repair"])
def test_same_sha_review_reuses_publication_and_repairs_only_projection(
    tmp_path, monkeypatch, platform: Platform, reference: str
):
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    fail_projection = reference == "repair"
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
        inline = deepcopy(api.inline_comments)
        artifact = harness.state_service.state.reviews[key].projection_artifact.model_copy(
            deep=True
        )
        assert first.status.value == "reviewed"
        if reference == "comment":
            harness.state_service.state.reviews.clear()
            harness.state_service.state_store.save(harness.state_service.state)
        if reference == "repair":
            assert failed_updates
            assert harness.state_service.state_store.load().reviews[key].projection_retry_pending
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
        assert api.comments == published
        assert api.inline_comments == inline
        assert (
            all(method == "GET" for method, _ in api.calls[calls_before:]) or reference == "repair"
        )
        saved = harness.state_service.state_store.load()
        assert saved.runs[-1].status.value == "reviewed"
        if reference == "repair":
            assert "Repaired pending review projection." in summary.message
            repaired = saved.reviews[key]
            assert not repaired.projection_retry_pending
            assert repaired.projection_retry_warning is None
            assert repaired.projection_artifact == artifact
            assert len(api.work_items.issue_writes) == writes_before + 1
            body = str(
                api.work_items.issues[1].get("body", api.work_items.issues[1].get("description"))
            )
            assert case.head_sha in body
            assert "review_feedback_required" in body
        else:
            assert len(api.work_items.issue_writes) == writes_before

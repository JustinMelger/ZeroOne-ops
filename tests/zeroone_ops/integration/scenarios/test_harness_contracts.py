"""Prove the offline harness rejects corrupted model and publication inputs."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Literal

import httpx
import pytest

from zeroone_ops.models.analysis import IssueContext
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.services.remediation.publication_request_builder import (
    RemediationPublicationRequestBuilder,
)

from .harness import RUN_ID, compose_scenario
from .provider_api import Platform, ScenarioProviderAPI
from .repository import create_repository
from .scripted_model import ScriptedModel


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("stage", ["analysis", "initial-edit", "correction"])
@pytest.mark.parametrize("damage", ["empty-source", "missing-member"])
def test_model_boundary_rejects_incomplete_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: Platform,
    stage: str,
    damage: str,
) -> None:
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(platform)
    method_name = "analyze_issue" if stage == "analysis" else "generate_structured_edit"
    original_method = getattr(ScriptedModel, method_name)

    def corrupt_request(
        model: ScriptedModel, issue: RemediationExecutionTarget, context: IssueContext
    ) -> object:
        edit_index = len(model.edit_contexts)
        if stage != "correction" or edit_index == 1:
            if damage == "empty-source":
                context = context.model_copy(
                    update={"snippet": context.snippet.model_copy(update={"content": ""})}
                )
            else:
                assert context.batch_attempt is not None
                context = context.model_copy(
                    update={
                        "batch_attempt": context.batch_attempt.model_copy(
                            update={"members": context.batch_attempt.members[:-1]}
                        )
                    }
                )
        return original_method(model, issue, context)

    monkeypatch.setattr(ScriptedModel, method_name, corrupt_request)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_scenario(
            repository, api, http, ("value: MissingType = 1", "value: int = 1"), monkeypatch
        )
        harness.sync("scenario-promotion")
        expected = "Missing source context" if damage == "empty-source" else "member evidence"
        with pytest.raises(AssertionError, match=expected):
            harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        assert not api.requests


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_workflow_rejects_incorrect_publication_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(platform)
    original_build = RemediationPublicationRequestBuilder.build

    def build_with_wrong_target(self, **arguments):
        return replace(original_build(self, **arguments), target_branch="nonexistent-target")

    monkeypatch.setattr(RemediationPublicationRequestBuilder, "build", build_with_wrong_target)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_scenario(repository, api, http, (None,), monkeypatch)
        harness.sync("scenario-promotion")
        with pytest.raises(AssertionError, match="Unexpected request target branch"):
            harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        assert not api.requests


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("destination", ["wrong-origin", "wrong-scope", "wrong-platform"])
def test_transport_rejects_incorrect_destination(
    platform: Platform, destination: Literal["wrong-origin", "wrong-scope", "wrong-platform"]
) -> None:
    api = ScenarioProviderAPI(platform)
    prefix = (
        f"/repos/{api.repository_scope}"
        if platform == "github"
        else f"/api/v4/projects/{api.repository_scope}"
    )
    host = "provider.invalid"
    if destination == "wrong-origin":
        host = "unexpected.invalid"
    elif destination == "wrong-scope":
        prefix = prefix.replace(api.repository_scope, "another/application")
    else:
        prefix = (
            f"/api/v4/projects/{api.repository_scope}"
            if platform == "github"
            else f"/repos/{api.repository_scope}"
        )
    with pytest.raises(AssertionError, match="Unexpected provider origin|scope"):
        api.respond(httpx.Request("GET", f"https://{host}{prefix}/issues"))
    assert not api.issues and not api.requests and not api.issue_writes


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_transport_rejects_wrong_target_before_request_creation(platform: Platform) -> None:
    api = ScenarioProviderAPI(platform)
    if platform == "github":
        request = httpx.Request(
            "POST",
            f"https://provider.invalid/repos/{api.repository_scope}/pulls",
            json={"base": "nonexistent-target"},
        )
    else:
        request = httpx.Request(
            "POST",
            f"https://provider.invalid/api/v4/projects/{api.repository_scope}/merge_requests",
            data={"target_branch": "nonexistent-target"},
        )
    with pytest.raises(AssertionError, match="Unexpected request target branch"):
        api.respond(request)
    assert not api.requests


@pytest.fixture
def issue_transport(platform: Platform) -> tuple[ScenarioProviderAPI, str]:
    """Provide one native issue snapshot for transport-only contract checks."""
    api = ScenarioProviderAPI(platform)
    api.issues[1] = {
        "state": "open" if platform == "github" else "opened",
        "title": "Preserve this issue",
        "labels": ["zeroone"],
    }
    prefix = (
        f"/repos/{api.repository_scope}"
        if platform == "github"
        else f"/api/v4/projects/{api.repository_scope}"
    )
    return api, f"https://provider.invalid{prefix}/issues/1"


def _issue_update_request(
    api: ScenarioProviderAPI, url: str, method: str, fields: dict[str, str]
) -> httpx.Request:
    """Encode each provider's real transport format without sending a request."""
    if api.platform == "github":
        return httpx.Request(method, url, json=fields)
    return httpx.Request(method, url, data=fields)


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_issue_transport_rejects_swapped_update_methods(platform, issue_transport):
    api, url = issue_transport
    before = deepcopy(api.issues)
    method = "PUT" if platform == "github" else "PATCH"
    fields = {"state": "closed"} if platform == "github" else {"state_event": "close"}
    with pytest.raises(AssertionError, match="Unexpected issue update method"):
        api.respond(_issue_update_request(api, url, method, fields))
    assert api.issues == before and not api.issue_writes


@pytest.mark.parametrize(
    ("platform", "fields", "message"),
    [
        ("github", {"state_event": "close"}, "Unexpected GitHub state_event"),
        ("github", {"state": "opened"}, "Unexpected GitHub state"),
        (
            "github",
            {"state": "closed", "state_event": "close"},
            "Unexpected GitHub state_event",
        ),
        ("gitlab", {"state": "closed"}, "GitLab issue state requires state_event"),
        ("gitlab", {"state": "opened"}, "GitLab issue state requires state_event"),
        (
            "gitlab",
            {"state": "closed", "state_event": "close"},
            "GitLab issue state requires state_event",
        ),
        ("gitlab", {"state_event": "closed"}, "Unexpected GitLab state_event"),
    ],
)
def test_issue_transport_rejects_invalid_state_payloads(platform, fields, message, issue_transport):
    api, url = issue_transport
    before = deepcopy(api.issues)
    method = "PATCH" if platform == "github" else "PUT"
    with pytest.raises(AssertionError, match=message):
        api.respond(_issue_update_request(api, url, method, fields))
    assert api.issues == before and not api.issue_writes


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("event", ["close", "reopen"])
def test_issue_transport_accepts_native_close_and_reopen(platform, event, issue_transport):
    api, url = issue_transport
    api.issues[1]["state"] = "open" if platform == "github" else "opened"
    if event == "reopen":
        api.issues[1]["state"] = "closed"
    expected = "closed" if event == "close" else ("open" if platform == "github" else "opened")
    fields = {"state": expected} if platform == "github" else {"state_event": event}
    method = "PATCH" if platform == "github" else "PUT"
    response = api.respond(_issue_update_request(api, url, method, fields))
    assert response.status_code == 200 and response.json()["state"] == expected
    assert api.issues[1]["state"] == expected
    assert api.issues[1]["title"] == "Preserve this issue"
    assert api.issues[1]["labels"] == ["zeroone"]
    assert api.issue_writes == [api.issues[1]]
    assert "state_event" not in api.issues[1]

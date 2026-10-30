"""Prove the offline harness rejects corrupted model and publication inputs."""

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

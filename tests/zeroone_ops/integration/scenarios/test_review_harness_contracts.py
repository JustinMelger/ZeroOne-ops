"""Reject missing prompt evidence and wrong destinations instead of scripted success."""

from pathlib import Path

import httpx
import pytest

from zeroone_ops.models.review import ChangeRequestReviewContext, ReviewResult
from zeroone_ops.providers import llm_client
from zeroone_ops.providers.llm_client import OpenAILLMClient
from zeroone_ops.providers.review.github import GitHubReviewClient
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.services.review.context.review_context_builder import ReviewContextBuilder

from .provider_api import Platform, ScenarioProviderAPI
from .review_cases import create_review_case
from .review_harness import compose_review_harness
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_review_sdk_rejects_candidate_mutation_without_changing_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    original_review = OpenAILLMClient.review_merge_request

    def mutate_candidate(self, context):
        result = original_review(self, context)
        result.findings[0].severity = "medium"
        return result

    monkeypatch.setattr(OpenAILLMClient, "review_merge_request", mutate_candidate)
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        with pytest.raises(pytest.fail.Exception, match="forwarded candidate evidence"):
            harness.run(case, sdk)
        assert case.finding.severity == "high"
        assert isinstance(sdk.calls[0].output, ReviewResult)
        assert sdk.calls[0].output.findings[0].severity == "high"
        assert not any(api.comments.values()) and not api.inline_comments


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_review_sdk_records_independent_response_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    original_parse = ScriptedReviewSDK.parse
    emitted = []

    def capture_response(self, **arguments):
        response = original_parse(self, **arguments)
        emitted.append(response.output_parsed)
        return response

    monkeypatch.setattr(ScriptedReviewSDK, "parse", capture_response)
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        harness.run(case, sdk)
        snapshots = [call.output.model_copy(deep=True) for call in sdk.calls]
        emitted[0].findings[0].severity = "medium"
        emitted[1].accepted_findings[0].severity = "medium"
        emitted[1].accepted_findings[0].evidence.append("Later mutation")
        assert [call.output for call in sdk.calls] == snapshots
        assert case.finding.severity == "high"


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "damage", ["candidate-source", "precision-source", "precision-batch", "precision-candidate"]
)
def test_review_sdk_rejects_missing_prompt_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform, damage: str
) -> None:
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    builder_name = (
        "build_candidate_review_prompt"
        if damage == "candidate-source"
        else "build_review_precision_prompt"
    )
    original_builder = getattr(llm_client, builder_name)

    def damaged_prompt(context: ChangeRequestReviewContext, **arguments) -> str:
        if damage == "precision-candidate":
            arguments["candidates"] = [
                candidate.model_copy(update={"evidence": "Incorrect forwarded evidence"})
                for candidate in arguments["candidates"]
            ]
        elif damage == "precision-batch":
            assert context.remediation_context is not None
            context = context.model_copy(
                update={
                    "remediation_context": context.remediation_context.model_copy(
                        update={"batch_attempt": None}
                    )
                }
            )
        else:
            context = context.model_copy(
                update={
                    "changed_files": [
                        file.model_copy(update={"content": ""}) for file in context.changed_files
                    ]
                }
            )
        return original_builder(context, **arguments)

    monkeypatch.setattr(llm_client, builder_name, damaged_prompt)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(case, linked_work_item=harness.seed_link(case))
        expected = {
            "candidate-source": "source context",
            "precision-source": "source context",
            "precision-batch": "Verified linked batch attempt evidence",
            "precision-candidate": "forwarded candidate evidence",
        }[damage]
        with pytest.raises(pytest.fail.Exception, match=expected):
            harness.run(case, sdk)
        assert not any(api.comments.values()) and not api.inline_comments


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_review_sdk_rejects_another_checkout_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    current = create_review_case(tmp_path, number=11, name="annotation")
    other = create_review_case(tmp_path, number=12, name="mr24")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={11: current, 12: other})
    original_build = ReviewContextBuilder.build

    def wrong_checkout(self, change_request):
        return original_build(ReviewContextBuilder(other.root, self.config), change_request)

    monkeypatch.setattr(ReviewContextBuilder, "build", wrong_checkout)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(
            current, linked_work_item=harness.seed_link(current), forbidden_markers=(other.marker,)
        )
        with pytest.raises(pytest.fail.Exception, match="Cross-request model context"):
            harness.run(current, sdk)
        assert not any(api.comments.values()) and not api.inline_comments


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_review_transport_rejects_publication_on_another_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    current = create_review_case(tmp_path, number=11, name="annotation")
    other = create_review_case(tmp_path, number=12, name="mr24")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={11: current, 12: other})
    client_type = GitHubReviewClient if platform == "github" else GitLabReviewClient
    original_publish = client_type.create_change_request_comment

    def publish_elsewhere(self, *, repository_id, change_request_number, body):
        return original_publish(
            self, repository_id=repository_id, change_request_number=other.number, body=body
        )

    monkeypatch.setattr(client_type, "create_change_request_comment", publish_elsewhere)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        sdk = ScriptedReviewSDK(current, linked_work_item=harness.seed_link(current))
        with pytest.raises(pytest.fail.Exception, match="Cross-request"):
            harness.run(current, sdk)
        assert len(sdk.calls) == 2
        assert not any(api.comments.values()) and not api.inline_comments


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("destination", ["host", "scope", "unknown-request"])
def test_review_transport_rejects_wrong_destination(
    tmp_path: Path, platform: Platform, destination: str
) -> None:
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={11: case}, active_number=11)
    prefix = (
        "/repos/offline/application"
        if platform == "github"
        else "/api/v4/projects/offline/application"
    )
    collection = "pulls" if platform == "github" else "merge_requests"
    host, number = "provider.invalid", 11
    if destination == "host":
        host = "another.invalid"
    elif destination == "scope":
        prefix = prefix.replace("offline/application", "another/application")
    else:
        number = 12
    with pytest.raises(pytest.fail.Exception, match="Wrong review|Unknown review"):
        api.respond(httpx.Request("GET", f"https://{host}{prefix}/{collection}/{number}"))
    assert not api.comments and not api.inline_comments and not api.work_items.issue_writes

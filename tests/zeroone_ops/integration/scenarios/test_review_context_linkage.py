"""Context failures and ambiguous authority do not redirect a real review workflow."""

from pathlib import Path

import httpx
import pytest

from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.workflows import provider_workflow_builders
from zeroone_ops.settings import SettingsError

from .provider_api import REPOSITORY_SCOPE, Platform, ScenarioProviderAPI
from .review_cases import create_review_case
from .review_harness import compose_review_harness
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("mode", ["duplicate", "lookup_failure"])
def test_review_continues_without_unverified_work_item_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog, platform: Platform, mode: str
):
    case = create_review_case(tmp_path, number=11, name="annotation")
    api = ReviewProviderAPI(ScenarioProviderAPI(platform), cases={case.number: case})
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_review_harness(api, http, tmp_path / "state.json", monkeypatch)
        linked = harness.seed_link(case)
        if mode == "duplicate":
            second = WorkItemState(
                work_item_id="historical-other",
                kind="remediation",
                status="in_progress",
                summary="Separate work",
                source=WorkItemSourceRef(
                    source="mypy-sarif",
                    source_item_key="another-finding",
                    repository_scope=REPOSITORY_SCOPE,
                ),
                linked_change_request=linked.linked_change_request,
            )
            if platform == "github":
                GitHubWorkItemService(GitHubWorkItemClient(harness._connection())).upsert_work_item(
                    repository_id=REPOSITORY_SCOPE, work_item=second
                )
            else:
                GitLabWorkItemService(GitLabWorkItemClient(harness._connection())).upsert_work_item(
                    project_id=REPOSITORY_SCOPE, work_item=second
                )
        else:
            monkeypatch.setattr(
                provider_workflow_builders,
                f"load_{platform}_connection_config",
                lambda: (_ for _ in ()).throw(SettingsError("Context settings unavailable")),
            )
        sdk = ScriptedReviewSDK(case)

        summary = harness.run(case, sdk)

        assert summary.status.value == "reviewed"
        assert len(sdk.calls) == 2
        for call in sdk.calls:
            assert "Verified linked batch attempt evidence" not in call.prompt
            assert linked.semantic_safety.assessment.current_behavior not in call.prompt
        note = next(iter(api.comments[case.number].values()))
        assert "/zeroone remediation requeue" not in str(note["body"])
        assert case.finding.title in str(note["body"])
        persisted = harness.state_service.state_store.load().reviews[
            f"{case.number}:{case.head_sha}"
        ]
        assert persisted.projection_artifact.classification == "findings_present"
        if mode == "lookup_failure":
            warnings = [
                record
                for record in caplog.records
                if record.getMessage() == "review work-item context lookup failed"
            ]
            assert len(warnings) == 1
        else:
            assert any(
                "multiple" in record.getMessage() and "link" in record.getMessage()
                for record in caplog.records
            )

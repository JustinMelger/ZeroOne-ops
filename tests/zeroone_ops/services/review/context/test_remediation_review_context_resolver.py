from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.batch_execution import BatchAnalysisCoverage, BatchAttemptEvidence
from zeroone_ops.models.config import (
    AppConfig,
    GitHubConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot
from zeroone_ops.models.review import ChangeRequestReviewContext, RemediationReviewContext
from zeroone_ops.models.review_linkage import LinkedReviewWorkItem
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSemanticSafety,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.review.context.remediation_review_context_resolver import (
    RemediationReviewContextResolver,
)
from zeroone_ops.services.review.pipeline import review_runner
from zeroone_ops.services.workflows import provider_workflow_builders
from zeroone_ops.settings import SettingsError


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "lookup", ["linked", "absent", "unlinked", "wrong_url", "failure", "cleared"]
)
@pytest.mark.parametrize("with_batch", [False, True])
@pytest.mark.parametrize("with_rationale", [False, True])
def test_verified_notice_link_does_not_require_semantic_safety(
    tmp_path, monkeypatch, platform, lookup, with_batch, with_rationale
):
    context = ChangeRequestReviewContext(
        change_request_number=9,
        title="Remediation",
        source_branch="remediation",
        target_branch="main",
        head_sha="sha",
        web_url="https://example.com/pr/9",
        description="Tracking work item: https://untrusted.example/issues/1",
    )
    work_item = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="in_progress",
        summary="Fix",
        source=WorkItemSourceRef(source="ruff", source_item_key="1", repository_scope="org/repo"),
        linked_change_request=ChangeRequestRef(
            number=9,
            web_url="https://other.example/pr/9" if lookup == "wrong_url" else context.web_url,
        ),
    )
    if with_batch:
        identity = uuid4().hex
        member = BatchFindingSnapshot(
            finding_id="member",
            source_id="ruff",
            severity="medium",
            title="Unused import",
            summary="Remove import",
            repository_path="src/app.py",
            line_start=1,
            remediation_context={"category": "static_analysis_fix", "diagnostic_code": "F401"},
        )
        attempt = BatchAttemptEvidence(
            batch_id=f"work-{identity}",
            attempt_number=1,
            run_id="original-execution",
            members=(member,),
            observation_run_ids=("scan",),
            coverage=BatchAnalysisCoverage(addressable_ids=("member",)),
        )
        work_item = WorkItemState.model_validate(
            work_item.model_dump()
            | {
                "work_item_id": f"work-{identity}",
                "file_path": "src/app.py",
                "source": {
                    "source": "ruff",
                    "source_item_key": f"batch-v1:{identity}",
                    "repository_scope": "org/repo",
                },
                "remediation_context": {
                    "category": "static_analysis_fix",
                    "diagnostic_code": "F401",
                },
                "batch": {
                    "group": {
                        "repository_scope": "org/repo",
                        "file_path": "src/app.py",
                        "source_id": "ruff",
                        "rule_id": "F401",
                    },
                    "members": [member],
                    "observations": [
                        {
                            "finding_id": "member",
                            "last_confirmed_presence": "detected",
                            "freshness": "current",
                            "sync_run_id": "scan",
                            "observed_at": datetime(2026, 10, 19, tzinfo=UTC),
                        }
                    ],
                },
                "batch_attempt": attempt,
            }
        )
    assessment = SemanticSafetyAssessment(
        current_behavior="Current behavior",
        intended_behavior="Intended change",
        preservation_evidence=["Existing behavior remains covered."],
    )
    if with_rationale:
        work_item = work_item.model_copy(
            update={"semantic_safety": WorkItemSemanticSafety(assessment=assessment)}
        )
    context = context.model_copy(
        update={
            "remediation_context": RemediationReviewContext(
                summary="Existing MR metadata",
                notes="Keep operator notes",
                semantic_safety=assessment,
                batch_attempt=work_item.batch_attempt,
            )
        }
    )
    if lookup == "unlinked":
        work_item = work_item.model_copy(update={"linked_change_request": None})
    elif lookup == "cleared":
        work_item = work_item.model_copy(update={"semantic_safety": None, "batch_attempt": None})
    before_context = context.model_dump_json()
    before_work_item = work_item.model_dump_json()
    result = (
        None
        if lookup == "absent"
        else SimpleNamespace(
            work_item=work_item, issue=SimpleNamespace(web_url="https://example.com/issues/12")
        )
    )
    service = Mock()
    service.find_open_work_item_by_change_request.return_value = result
    if lookup == "failure":
        service.find_open_work_item_by_change_request.side_effect = SettingsError("Unavailable")
    name = "GitHub" if platform == "github" else "GitLab"
    monkeypatch.setattr(
        provider_workflow_builders, f"{name}WorkItemService", lambda client: service
    )
    monkeypatch.setattr(
        provider_workflow_builders, f"{name}WorkItemClient", lambda config: object()
    )
    load_settings = Mock(return_value=object())
    monkeypatch.setattr(
        provider_workflow_builders, f"load_{platform}_connection_config", load_settings
    )
    resolver = provider_workflow_builders.build_review_remediation_context_resolver(
        AppConfig(
            remediation=RemediationConfig(target_branch="main"),
            platform=platform,
            base_branch="main",
            github=GitHubConfig(),
            gitlab=GitLabConfig(),
        ),
        review_runner.LOGGER,
    )
    load_settings.assert_not_called()
    service.find_open_work_item_by_change_request.assert_not_called()
    updated = resolver.resolve(repository_id="org/repo", context=context)
    load_settings.assert_called_once_with()
    if lookup in {"linked", "cleared"}:
        assert updated.remediation_context.verified_work_item_url == "https://example.com/issues/12"
        assert updated.remediation_context.semantic_safety == (
            None if work_item.semantic_safety is None else work_item.semantic_safety.assessment
        )
        assert updated.remediation_context.batch_attempt == work_item.batch_attempt
        assert updated.remediation_context.summary == "Existing MR metadata"
        assert updated.remediation_context.notes == "Keep operator notes"
    else:
        assert updated is context
    assert context.model_dump_json() == before_context
    assert work_item.model_dump_json() == before_work_item
    service.find_open_work_item_by_change_request.assert_called_once_with(
        **{"repository_id" if platform == "github" else "project_id": "org/repo"},
        change_request_number=9,
    )


def _context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=9,
        title="Review",
        source_branch="fix",
        target_branch="main",
        head_sha="current",
        web_url="https://example/pr/9",
        description="Tracking work item: https://untrusted.example/issues/1",
    )


def _config(platform: str) -> AppConfig:
    return AppConfig.model_validate(
        {
            "platform": platform,
            "base_branch": "main",
            platform: {},
            "remediation": {"target_branch": "main"},
        }
    )


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("stage", ["settings", "client", "service", "lookup"])
@pytest.mark.parametrize(
    "error_type",
    [GitHubClientError, GitLabClientError, SettingsError, httpx.HTTPError, RuntimeError],
)
def test_lookup_failures_preserve_existing_warning_and_exception_boundaries(
    monkeypatch, caplog, platform, stage, error_type
):
    service = Mock()
    service.find_open_work_item_by_change_request.return_value = None
    settings = Mock(return_value=object())
    client = Mock(return_value=object())
    facade = Mock(return_value=service)
    selected = {
        "settings": settings,
        "client": client,
        "service": facade,
        "lookup": service.find_open_work_item_by_change_request,
    }[stage]
    selected.side_effect = error_type("lookup unavailable")
    name = "GitHub" if platform == "github" else "GitLab"
    monkeypatch.setattr(provider_workflow_builders, f"load_{platform}_connection_config", settings)
    monkeypatch.setattr(provider_workflow_builders, f"{name}WorkItemClient", client)
    monkeypatch.setattr(provider_workflow_builders, f"{name}WorkItemService", facade)
    other = "gitlab" if platform == "github" else "github"
    monkeypatch.setattr(
        provider_workflow_builders,
        f"load_{other}_connection_config",
        Mock(side_effect=AssertionError("Inactive provider settings accessed")),
    )
    resolver = provider_workflow_builders.build_review_remediation_context_resolver(
        _config(platform), review_runner.LOGGER
    )
    for dependency in (settings, client, facade, service.find_open_work_item_by_change_request):
        dependency.assert_not_called()
    context = _context()

    if error_type is RuntimeError:
        with pytest.raises(RuntimeError, match="lookup unavailable"):
            resolver.resolve(repository_id="org/repo", context=context)
        assert not caplog.records
    else:
        assert resolver.resolve(repository_id="org/repo", context=context) is context
        warnings = [record for record in caplog.records if record.name == review_runner.LOGGER.name]
        assert len(warnings) == 1
        assert warnings[0].getMessage() == "review work-item context lookup failed"
        assert warnings[0].exc_info is not None
        assert warnings[0].exc_info[0] is error_type
    selected.assert_called_once()


def test_resolver_uses_authoritative_link_without_description_evidence():
    context = _context()
    state = WorkItemState(
        work_item_id="historical",
        kind="remediation",
        status="in_progress",
        summary="Fix",
        source=WorkItemSourceRef(source="ruff", source_item_key="a", repository_scope="org/repo"),
        linked_change_request=ChangeRequestRef(number=9, web_url=context.web_url),
    )
    lookup = Mock(return_value=LinkedReviewWorkItem(state, "https://example/issues/12"))
    resolver = RemediationReviewContextResolver(lookup=lookup, logger=review_runner.LOGGER)

    updated = resolver.resolve(repository_id="org/repo", context=context)

    lookup.assert_called_once_with("org/repo", 9)
    assert context.remediation_context is None
    assert updated.remediation_context.verified_work_item_url == "https://example/issues/12"
    assert updated.remediation_context.semantic_safety is None
    assert updated.remediation_context.batch_attempt is None
    assert "untrusted.example" not in updated.remediation_context.model_dump_json()


def test_description_only_routing_does_not_create_verified_context():
    context = _context()
    resolver = RemediationReviewContextResolver(
        lookup=lambda _repo, _number: None, logger=review_runner.LOGGER
    )

    assert resolver.resolve(repository_id="org/repo", context=context) is context
    assert context.remediation_context is None

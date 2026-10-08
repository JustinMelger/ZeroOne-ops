"""Characterize authoritative merge behavior through both provider upserts."""

from datetime import UTC, datetime
from typing import Literal

import pytest

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertService,
)
from zeroone_ops.services.control_plane.work_items.work_item_state_merge import (
    merge_authoritative_work_item_state,
)

from .test_gitlab_work_item_upsert_service import FakeGitLabWorkItemClient
from .test_support import FakeGitHubWorkItemClient, build_work_item

Provider = Literal["github", "gitlab"]
PRESERVED_FIELDS = (
    "linked_change_request",
    "projected_review",
    "publication_retry",
    "execution_failure",
    "policy_deferral",
    "capacity_deferral",
    "resolution",
    "last_revision_command",
    "review_action_required_at",
    "attempt_number",
    "recovery_events",
)


def _existing_state(*, replacement: bool = False) -> WorkItemState:
    marker = "replacement" if replacement else "existing"
    occurred_at = datetime(2026, 9, 2 if replacement else 1, tzinfo=UTC)
    return WorkItemState.model_validate(
        {
            **build_work_item(status="blocked").model_dump(),
            "work_item_id": marker,
            "linked_change_request": {
                "number": 18 if replacement else 17,
                "web_url": f"https://example.com/requests/{marker}",
            },
            "projected_review": {
                "classification": "no_findings",
                "reviewed_sha": marker,
                "follow_up_required": False,
            },
            "publication_retry": {
                "branch_name": f"zeroone-ops/{marker}",
                "commit_sha": marker,
                "reason": "change_request_publish_failed",
            },
            "execution_failure": {
                "stage": "validation",
                "summary": marker,
                "retry_count": 1,
                "run_id": marker,
                "occurred_at": occurred_at,
            },
            "policy_deferral": {
                "reason": marker,
                "run_id": marker,
                "occurred_at": occurred_at,
            },
            "capacity_deferral": {
                "reason": "promotion_capacity_exhausted",
                "run_id": marker,
                "occurred_at": occurred_at,
            },
            "resolution": "merged" if replacement else "no_change_required",
            "last_revision_command": {
                "actor": marker,
                "request_reference": marker,
                "occurred_at": occurred_at,
                "reviewed_sha": marker,
            },
            "review_action_required_at": occurred_at,
            "attempt_number": 3 if replacement else 2,
            "recovery_events": [
                {
                    "action": "requeue",
                    "actor": marker,
                    "request_reference": marker,
                    "occurred_at": occurred_at,
                    "previous_status": "blocked",
                    "resulting_status": "approved",
                    "previous_attempt_number": 1,
                    "resulting_attempt_number": 2,
                }
            ],
            "claim": {"claimed_at": occurred_at, "run_id": marker},
            "review_revision_request": {
                "actor": marker,
                "request_reference": marker,
                "occurred_at": occurred_at,
                "reviewed_sha": marker,
            },
            "semantic_safety": {"rejection_reason": marker},
        }
    )


def _upsert(
    provider: Provider,
    existing: WorkItemState,
    incoming: WorkItemState,
    *,
    stale_labels: bool = False,
    missing_parsed_state: bool = False,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[WorkItemState, str]:
    existing_snapshot = existing.model_dump()
    incoming_snapshot = incoming.model_dump()
    incoming_fields = incoming.model_fields_set.copy()
    if provider == "github":
        renderer = GitHubWorkItemRenderer()
        client = FakeGitHubWorkItemClient()
        client.issues = [
            GitHubIssueInfo(
                id=10,
                number=11,
                web_url="https://example.com/issues/11",
                title=renderer.render_title(existing),
                body=renderer.render_body(existing),
                labels=["operator-label"] if stale_labels else renderer.render_labels(existing),
            )
        ]
        service = GitHubWorkItemUpsertService(
            client, lookup_service=GitHubWorkItemLookupService(client)
        )
        if missing_parsed_state:
            assert monkeypatch is not None
            monkeypatch.setattr(service.parser, "parse_work_item_state", lambda _: None)
        result = service.upsert_work_item(repository_id="octo-org/octo-repo", work_item=incoming)
        parsed = GitHubWorkItemParser().parse_work_item_state(result.issue.body)
    else:
        renderer = GitLabWorkItemRenderer()
        client = FakeGitLabWorkItemClient()
        client.issues = [
            GitLabIssueInfo(
                id=10,
                iid=11,
                web_url="https://example.com/issues/11",
                title=renderer.render_title(existing),
                description=renderer.render_body(existing),
                labels=["operator-label"] if stale_labels else renderer.render_labels(existing),
            )
        ]
        service = GitLabWorkItemUpsertService(
            client, lookup_service=GitLabWorkItemLookupService(client)
        )
        if missing_parsed_state:
            assert monkeypatch is not None
            monkeypatch.setattr(service.parser, "parse_work_item_state", lambda _: None)
        result = service.upsert_work_item(project_id="group/project", work_item=incoming)
        parsed = GitLabWorkItemParser().parse_work_item_state(result.issue.description)
    assert parsed is not None
    assert parsed.model_dump() == result.work_item.model_dump()
    assert existing.model_dump() == existing_snapshot
    assert incoming.model_dump() == incoming_snapshot
    assert incoming.model_fields_set == incoming_fields
    return result.work_item, result.action


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("field_name", PRESERVED_FIELDS)
@pytest.mark.parametrize("mode", ["omitted", "replacement", "clear"])
def test_provider_merge_preserves_omission_and_honors_explicit_values(
    provider: Provider, field_name: str, mode: str
) -> None:
    existing = _existing_state()
    incoming = build_work_item(status="approved")
    if mode == "replacement":
        incoming = incoming.model_copy(
            update={field_name: getattr(_existing_state(replacement=True), field_name)}
        )
    elif mode == "clear":
        value = {"attempt_number": 1, "recovery_events": []}.get(field_name)
        incoming = incoming.model_copy(update={field_name: value})
    merged, action = _upsert(provider, existing, incoming)
    assert merged.work_item_id == existing.work_item_id
    assert merged.identity_key == incoming.identity_key
    assert merged.status == incoming.status
    expected = getattr(existing if mode == "omitted" else incoming, field_name)
    assert getattr(merged, field_name) == expected
    assert action == "updated"


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("field_name", ["claim", "review_revision_request", "semantic_safety"])
@pytest.mark.parametrize("explicit", [False, True])
def test_provider_merge_leaves_execution_owned_fields_incoming(
    provider: Provider, field_name: str, explicit: bool
) -> None:
    incoming = build_work_item(status="approved")
    if explicit:
        incoming = incoming.model_copy(
            update={field_name: getattr(_existing_state(replacement=True), field_name)}
        )
    merged, _ = _upsert(provider, _existing_state(), incoming)
    assert getattr(merged, field_name) == getattr(incoming, field_name)


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_merge_retains_empty_revision_field_presence_difference(
    provider: Provider,
) -> None:
    merged, _ = _upsert(provider, build_work_item(), build_work_item())
    for field_name in ("last_revision_command", "review_action_required_at"):
        assert getattr(merged, field_name) is None
        assert (field_name in merged.model_fields_set) is (provider == "github")


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_merge_falls_back_to_incoming_when_parser_returns_no_state(
    provider: Provider, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming = build_work_item(status="approved")
    merged, _ = _upsert(
        provider,
        _existing_state(),
        incoming,
        missing_parsed_state=True,
        monkeypatch=monkeypatch,
    )
    assert merged == incoming
    assert merged.model_fields_set == incoming.model_fields_set


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_label_only_change_keeps_existing_update_semantics(provider: Provider) -> None:
    original = build_work_item()
    _, action = _upsert(provider, original, original, stale_labels=True)
    assert action == ("unchanged" if provider == "github" else "updated")


@pytest.mark.parametrize("field_name", PRESERVED_FIELDS)
@pytest.mark.parametrize("mode", ["omitted", "replacement", "clear"])
def test_shared_merge_retains_selected_authority_without_mutating_inputs(
    field_name: str, mode: str
) -> None:
    existing = _existing_state()
    incoming = build_work_item(status="approved")
    if mode == "replacement":
        incoming = incoming.model_copy(
            update={field_name: getattr(_existing_state(replacement=True), field_name)}
        )
    elif mode == "clear":
        value = {"attempt_number": 1, "recovery_events": []}.get(field_name)
        incoming = incoming.model_copy(update={field_name: value})
    existing_snapshot = existing.model_dump()
    incoming_snapshot = incoming.model_dump()
    existing_fields = existing.model_fields_set.copy()
    incoming_fields = incoming.model_fields_set.copy()

    merged = merge_authoritative_work_item_state(existing, incoming)

    assert merged is not existing and merged is not incoming
    assert merged.work_item_id == existing.work_item_id
    assert merged.status == incoming.status
    expected = getattr(existing if mode == "omitted" else incoming, field_name)
    assert getattr(merged, field_name) == expected
    assert existing.model_dump() == existing_snapshot
    assert incoming.model_dump() == incoming_snapshot
    assert existing.model_fields_set == existing_fields
    assert incoming.model_fields_set == incoming_fields


@pytest.mark.parametrize("field_name", ["claim", "review_revision_request", "semantic_safety"])
def test_shared_merge_does_not_expand_the_preservation_contract(field_name: str) -> None:
    existing = _existing_state()
    incoming = build_work_item()
    assert getattr(existing, field_name) is not None

    merged = merge_authoritative_work_item_state(existing, incoming)

    assert getattr(merged, field_name) is None
    assert field_name not in merged.model_fields_set


def test_shared_merge_keeps_empty_optional_fields_omitted() -> None:
    merged = merge_authoritative_work_item_state(build_work_item(), build_work_item())

    for field_name in ("last_revision_command", "review_action_required_at"):
        assert getattr(merged, field_name) is None
        assert field_name not in merged.model_fields_set

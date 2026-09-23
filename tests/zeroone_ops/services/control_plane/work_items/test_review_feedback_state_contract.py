"""Provider parity for durable revision state and operator decisions."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
    PublishableReviewFinding,
)
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ReviewRevisionRequest,
    WorkItemClaim,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.review_projection.github_review_projection_service import (
    GitHubReviewProjectionService,
)
from zeroone_ops.services.control_plane.review_projection.gitlab_review_projection_service import (
    GitLabReviewProjectionService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_service import (
    GitHubWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_service import (
    GitLabWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.remediation_work_item_selection_service import (
    is_remediation_execution_eligible,
)
from zeroone_ops.services.control_plane.work_items.work_item_lifecycle_service import (
    WorkItemLifecycleService,
)

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


def artifact(classification="findings_present"):
    return PublishableReviewArtifact(
        classification=classification,
        summary="Review outcome",
        findings=[]
        if classification != "findings_present"
        else [
            PublishableReviewFinding(
                severity="medium",
                file_path="a.py",
                title="Error hidden",
                evidence="Returns success",
                explanation="Lost failure",
                suggested_follow_up="Keep the error",
            )
        ],
    )


def setup_projection(platform):
    current = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="in_progress",
        summary="Fix",
        file_path="a.py",
        source=WorkItemSourceRef(source="sarif", source_item_key="finding"),
        linked_change_request=ChangeRequestRef(number=1, web_url="https://example.com/pr/1"),
    )
    issue = SimpleNamespace(iid=12, number=12, web_url="https://example.com/issues/12")
    store = Mock()
    store.find_open_work_item_by_change_request.side_effect = lambda **kw: SimpleNamespace(
        issue=issue, work_item=current
    )

    def upsert(**kwargs):
        nonlocal current
        current = kwargs["work_item"]
        return SimpleNamespace(issue=issue, work_item=current)

    store.upsert_work_item.side_effect = upsert
    store.update_existing_work_item.side_effect = upsert
    store.list_open_work_items.side_effect = lambda **kw: [
        SimpleNamespace(issue=issue, work_item=current)
    ]
    projection_type = (
        GitHubReviewProjectionService if platform == "github" else GitLabReviewProjectionService
    )
    service = projection_type(
        store,
        change_request_state_lookup=lambda number: ChangeRequestState(
            iid=1,
            web_url="https://example.com/pr/1",
            state="opened",
            head_sha="sha",
            source_branch="fix",
        ),
    )
    context = ChangeRequestReviewContext(
        change_request_number=1,
        title="Fix",
        source_branch="fix",
        target_branch="main",
        web_url="https://example.com/pr/1",
        head_sha="sha",
    )
    service.coordinator.decision_service.clock = lambda: NOW - timedelta(seconds=1)

    def project(review, note_id, *, at=None):
        if at is not None:
            service.coordinator.decision_service.clock = lambda: at
        return service.project_review(
            repository_id="repo",
            context=context,
            artifact=review,
            reviewed_sha="sha",
            review_note_id=note_id,
        )

    project(artifact(), 1)
    return store, issue, project


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "classification", ["findings_present", "no_findings", "manual_review_only"]
)
def test_new_review_supersedes_queue_without_losing_receipt(platform, classification):
    store, issue, project = setup_projection(platform)
    existing = store.list_open_work_items()[0].work_item
    request = ReviewRevisionRequest(
        actor="operator", request_reference="command-1", occurred_at=NOW, reviewed_sha="sha"
    )
    queued = existing.model_copy(
        update={
            "status": "review_revision_queued",
            "review_revision_request": request,
            "claim": WorkItemClaim(claimed_at=NOW, run_id="run-1"),
        }
    )
    store.upsert_work_item(work_item=queued)
    result = project(artifact(classification), 2)
    assert result.work_item.status == (
        "in_progress" if classification == "no_findings" else "review_feedback_required"
    )
    assert result.work_item.review_revision_request is None
    assert result.work_item.claim is None
    assert result.work_item.last_revision_command == request
    if classification == "manual_review_only":
        assert result.work_item.projected_review == existing.projected_review
    assert project(artifact(classification), 2).action == "unchanged"


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_command_cannot_replay_after_queue_marker_clears(platform):
    store, issue, project = setup_projection(platform)
    note = SimpleNamespace(
        id=7,
        body="/zeroone remediation requeue",
        author_username="operator",
        created_at=NOW.isoformat(),
    )
    client, authorization = Mock(), Mock()
    if platform == "github":
        client.list_issue_comments.return_value = [note]
        authorization.authorized_comments.return_value = [note]
        service = GitHubWorkItemRecoveryService(
            comment_client=client,
            comment_authorization_service=authorization,
            work_item_service=store,
        )

        def process():
            return service.process(
                repository_id="repo",
                issue_number=12,
                comment_id=note.id,
                policy_eligible=True,
                persist=True,
            )
    else:
        client.list_issue_notes.return_value = [note]
        authorization.authorized_notes.return_value = [note]
        service = GitLabWorkItemRecoveryService(
            note_client=client, note_authorization_service=authorization, work_item_service=store
        )

        def process():
            return service.process(
                project_id="repo",
                existing=store.list_open_work_items()[0],
                policy_eligible=True,
                persist=True,
            )

    # A historical command rejected before feedback must not become authorization.
    note.created_at = (NOW - timedelta(days=1)).isoformat()
    assert process().accepted_command_count == 0
    note.created_at = NOW.isoformat()
    first = process()
    assert first.accepted_command_count == 1
    failed = first.work_item.model_copy(
        update={
            "status": "review_feedback_required",
            "review_revision_request": None,
            "claim": None,
            "review_action_required_at": NOW + timedelta(minutes=2),
        }
    )
    # Exercise the machine-state round trip, not just in-memory suppression.
    store.upsert_work_item(work_item=WorkItemState.model_validate_json(failed.model_dump_json()))
    assert process().accepted_command_count == 0
    # An additional command sent during execution is not a retry decision.
    note.id = 8
    note.created_at = (NOW + timedelta(minutes=1)).isoformat()
    assert process().accepted_command_count == 0
    note.created_at = (NOW + timedelta(minutes=3)).isoformat()
    assert process().accepted_command_count == 1
    project(artifact(), 3)
    assert process().accepted_command_count == 0


@pytest.mark.parametrize("provider_state", ["opened", "closed", "merged"])
@pytest.mark.parametrize("stale", [False, True])
def test_claim_exclusion_and_lifecycle_ownership(provider_state, stale):
    store, issue, project = setup_projection("github")
    existing = store.list_open_work_items()[0].work_item
    queued = existing.model_copy(
        update={
            "status": "review_revision_queued",
            "claim": WorkItemClaim(claimed_at=NOW, run_id="run"),
            "review_revision_request": ReviewRevisionRequest(
                actor="operator", request_reference="command-1", occurred_at=NOW, reviewed_sha="sha"
            ),
        }
    )
    assert not is_remediation_execution_eligible(queued)
    store.upsert_work_item(work_item=queued)
    lifecycle = WorkItemLifecycleService(
        provider_name="test",
        list_open_work_items=lambda: [(12, store.list_open_work_items()[0].work_item)],
        upsert_work_item=lambda work: store.upsert_work_item(work_item=work).issue.number,
        close_work_item_issue=lambda number: None,
        get_change_request_state=lambda number: ChangeRequestState(
            iid=1,
            web_url="https://example.com/pr/1",
            state=provider_state,
            head_sha="sha",
            source_branch="fix",
        ),
        recoverable_errors=(RuntimeError,),
    )
    lifecycle.reconcile(now=NOW + timedelta(days=2) if stale else NOW)
    updated = store.list_open_work_items()[0].work_item
    if provider_state == "opened":
        if not stale:
            assert updated == queued
            lifecycle.reconcile(now=NOW + timedelta(days=2))
            updated = store.list_open_work_items()[0].work_item
        assert updated.status == "review_feedback_required"
        assert updated.review_action_required_at == NOW + timedelta(days=2)
    else:
        assert updated.status == ("blocked" if provider_state == "closed" else "completed")
    assert updated.claim is None
    assert updated.review_revision_request is None
    assert updated.last_revision_command == queued.review_revision_request


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_projection_boundary_persists_without_advancing_on_repair(platform):
    store, _, project = setup_projection(platform)
    current = store.list_open_work_items()[0].work_item
    assert current.review_action_required_at == NOW - timedelta(seconds=1)
    legacy = current.model_copy(update={"review_action_required_at": None})
    store.upsert_work_item(work_item=legacy)
    repaired = project(artifact(), 1)
    assert repaired.action == "updated"
    assert repaired.work_item.review_action_required_at is not None
    assert project(artifact(), 1).action == "unchanged"
    assert store.list_open_work_items()[0].work_item == repaired.work_item
    newer = project(artifact(), 2, at=NOW + timedelta(minutes=5))
    assert newer.work_item.review_action_required_at == NOW + timedelta(minutes=5)
    assert project(artifact(), 2, at=NOW + timedelta(minutes=6)).action == "unchanged"
    assert store.list_open_work_items()[0].work_item == newer.work_item

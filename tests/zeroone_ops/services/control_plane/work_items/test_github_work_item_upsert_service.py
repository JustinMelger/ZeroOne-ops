from datetime import UTC, datetime

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ProjectedReviewState,
    WorkItemExecutionFailure,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_reconciliation_service import (
    GitHubWorkItemReconciliationService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertService,
)

from .test_support import FakeGitHubWorkItemClient, build_work_item


def test_upsert_creates_when_identity_is_missing() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )

    assert result.action == "created"
    assert result.work_item.work_item_id == "work-1"
    assert client.created_issue is not None
    assert client.created_issue.title == "ZeroOne Ops: Remediate Sonar issue AX123 in api.py"


def test_upsert_updates_matching_open_issue_when_state_changes() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item(status="approved")
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="in_progress"),
    )

    assert result.action == "updated"
    assert result.work_item.work_item_id == "work-1"
    assert client.updated_issue is not None
    assert "`in_progress`" in client.updated_issue.body


def test_upsert_reuses_matching_open_issue_without_title_authority() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item()
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title="Operator renamed this title",
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=original,
    )

    assert result.action == "updated"
    assert client.updated_issue is not None
    assert client.updated_issue.title == renderer.render_title(original)


def test_upsert_preserves_existing_link_when_retry_has_no_replacement() -> None:
    renderer = GitHubWorkItemRenderer()
    linked_change_request = ChangeRequestRef(
        number=17,
        web_url="https://github.example.com/octo-org/octo-repo/pull/17",
    )
    original = build_work_item().model_copy(update={"linked_change_request": linked_change_request})
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="blocked"),
    )

    assert result.action == "updated"
    assert result.work_item.linked_change_request == linked_change_request
    assert client.updated_issue is not None
    assert "pull/17" in client.updated_issue.body


def test_upsert_preserves_existing_projected_review_when_status_changes() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item().model_copy(
        update={
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha="abc123def",
                review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
                follow_up_required=True,
            )
        }
    )
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="in_progress"),
    )

    assert result.action == "updated"
    assert result.work_item.projected_review is not None
    assert result.work_item.projected_review.classification == "findings_present"
    assert client.updated_issue is not None
    assert "## Review Projection" in client.updated_issue.body


def test_upsert_preserves_existing_execution_failure_without_explicit_update() -> None:
    renderer = GitHubWorkItemRenderer()
    execution_failure = WorkItemExecutionFailure(
        stage="validation",
        summary="Validation failed.",
        retry_count=1,
        run_id="run-42",
        occurred_at=datetime(2026, 7, 31, tzinfo=UTC),
    )
    original = build_work_item(status="blocked").model_copy(
        update={"execution_failure": execution_failure}
    )
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="blocked"),
    )

    assert result.work_item.execution_failure == execution_failure


def test_upsert_persists_explicit_execution_failure_clear() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item(status="blocked").model_copy(
        update={
            "execution_failure": WorkItemExecutionFailure(
                stage="validation",
                summary="Validation failed.",
                retry_count=1,
                run_id="run-42",
                occurred_at=datetime(2026, 7, 31, tzinfo=UTC),
            )
        }
    )
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="approved").model_copy(update={"execution_failure": None}),
    )

    assert result.work_item.execution_failure is None
    assert client.updated_issue is not None
    assert "## Last Execution" not in client.updated_issue.body


def test_upsert_persists_explicit_link_clear_from_reconciliation() -> None:
    renderer = GitHubWorkItemRenderer()
    linked_change_request = ChangeRequestRef(
        number=17,
        web_url="https://github.example.com/octo-org/octo-repo/pull/17",
    )
    original = build_work_item(status="in_progress").model_copy(
        update={"linked_change_request": linked_change_request}
    )
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemUpsertService(
        client,
        lookup_service=GitHubWorkItemLookupService(client),
    )
    reconciled = GitHubWorkItemReconciliationService().reconcile(
        work_item=original,
        change_request_state=type(
            "State",
            (),
            {
                "iid": 17,
                "web_url": "https://github.example.com/octo-org/octo-repo/pull/17",
                "source_branch": "zeroone-ops/fix",
                "head_sha": "abc123",
                "state": "closed",
            },
        )(),
        closed_unmerged_outcome="approved",
    )

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=reconciled.work_item,
    )

    assert result.action == "updated"
    assert result.work_item.linked_change_request is None
    assert client.updated_issue is not None
    assert "No remediation pull request is linked yet." in client.updated_issue.body

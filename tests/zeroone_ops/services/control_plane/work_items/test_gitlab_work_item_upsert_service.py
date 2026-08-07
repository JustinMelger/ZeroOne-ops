import pytest

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertService,
)

from .test_support import build_work_item


class FakeGitLabWorkItemClient:
    def __init__(self) -> None:
        self.issues: list[GitLabIssueInfo] = []
        self.closed_issues: list[GitLabIssueInfo] = []
        self.created_issue: GitLabIssueInfo | None = None
        self.updated_issue: GitLabIssueInfo | None = None

    def list_open_issues(self, *, project_id: str, labels: list[str]) -> list[GitLabIssueInfo]:
        del project_id, labels
        return self.issues

    def list_closed_issues(self, *, project_id: str, labels: list[str]) -> list[GitLabIssueInfo]:
        del project_id, labels
        return self.closed_issues

    def create_issue(
        self, *, project_id: str, title: str, description: str, labels: list[str]
    ) -> GitLabIssueInfo:
        del project_id
        self.created_issue = GitLabIssueInfo(
            id=10,
            iid=11,
            web_url="https://gitlab.example.com/group/project/-/issues/11",
            title=title,
            description=description,
            labels=labels,
        )
        self.issues = [self.created_issue]
        return self.created_issue

    def update_issue(
        self,
        *,
        project_id: str,
        issue_iid: int,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        del project_id, issue_iid
        self.updated_issue = GitLabIssueInfo(
            id=10,
            iid=11,
            web_url="https://gitlab.example.com/group/project/-/issues/11",
            title=title,
            description=description,
            labels=labels,
        )
        self.issues = [self.updated_issue]
        return self.updated_issue


def test_upsert_creates_then_preserves_existing_merge_request_link() -> None:
    client = FakeGitLabWorkItemClient()
    service = GitLabWorkItemUpsertService(
        client,  # type: ignore[arg-type]
        lookup_service=GitLabWorkItemLookupService(client),  # type: ignore[arg-type]
    )

    created = service.upsert_work_item(project_id="group/project", work_item=build_work_item())
    existing = build_work_item().model_copy(
        update={
            "linked_change_request": ChangeRequestRef(
                number=17,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
            )
        }
    )
    client.issues = [
        GitLabIssueInfo(
            id=10,
            iid=11,
            web_url="https://gitlab.example.com/group/project/-/issues/11",
            title=GitLabWorkItemRenderer().render_title(existing),
            description=GitLabWorkItemRenderer().render_body(existing),
            labels=GitLabWorkItemRenderer().render_labels(existing),
        )
    ]
    updated = service.upsert_work_item(
        project_id="group/project",
        work_item=build_work_item(status="blocked"),
    )

    assert created.action == "created"
    assert updated.action == "updated"
    assert updated.work_item.linked_change_request is not None
    assert updated.work_item.linked_change_request.number == 17
    assert client.updated_issue is not None


def test_upsert_returns_dismissed_tombstone_without_creating_a_new_issue() -> None:
    dismissed = build_work_item(status="dismissed")
    client = FakeGitLabWorkItemClient()
    client.closed_issues = [
        GitLabIssueInfo(
            id=10,
            iid=11,
            web_url="https://gitlab.example.com/group/project/-/issues/11",
            title=GitLabWorkItemRenderer().render_title(dismissed),
            description=GitLabWorkItemRenderer().render_body(dismissed),
            labels=GitLabWorkItemRenderer().render_labels(dismissed),
            state="closed",
        )
    ]
    service = GitLabWorkItemUpsertService(
        client,  # type: ignore[arg-type]
        lookup_service=GitLabWorkItemLookupService(client),  # type: ignore[arg-type]
    )

    result = service.upsert_work_item(project_id="group/project", work_item=build_work_item())

    assert result.action == "suppressed"
    assert result.work_item.status == "dismissed"
    assert client.created_issue is None


def test_upsert_rejects_ambiguous_open_authoritative_identity() -> None:
    work_item = build_work_item()
    renderer = GitLabWorkItemRenderer()
    client = FakeGitLabWorkItemClient()
    client.issues = [
        GitLabIssueInfo(
            id=10,
            iid=11,
            web_url="https://gitlab.example.com/group/project/-/issues/11",
            title=renderer.render_title(work_item),
            description=renderer.render_body(work_item),
            labels=renderer.render_labels(work_item),
        ),
        GitLabIssueInfo(
            id=12,
            iid=13,
            web_url="https://gitlab.example.com/group/project/-/issues/13",
            title=renderer.render_title(work_item),
            description=renderer.render_body(
                work_item.model_copy(update={"work_item_id": "work-duplicate"})
            ),
            labels=renderer.render_labels(work_item),
        ),
    ]
    service = GitLabWorkItemUpsertService(
        client,  # type: ignore[arg-type]
        lookup_service=GitLabWorkItemLookupService(client),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="ambiguously matched authoritative"):
        service.upsert_work_item(project_id="group/project", work_item=work_item)

    assert client.created_issue is None

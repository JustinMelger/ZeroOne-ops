from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)

from .test_support import build_work_item


class FakeGitLabWorkItemClient:
    def __init__(self) -> None:
        self.open_issues: list[GitLabIssueInfo] = []
        self.closed_issues: list[GitLabIssueInfo] = []
        self.list_labels: list[str] | None = None

    def list_open_issues(
        self,
        *,
        project_id: str,
        labels: list[str] | None = None,
    ) -> list[GitLabIssueInfo]:
        del project_id
        self.list_labels = labels
        return self.open_issues

    def list_closed_issues(
        self,
        *,
        project_id: str,
        labels: list[str] | None = None,
    ) -> list[GitLabIssueInfo]:
        del project_id
        self.list_labels = labels
        return self.closed_issues


def issue(*, iid: int, description: str) -> GitLabIssueInfo:
    return GitLabIssueInfo(
        id=iid + 100,
        iid=iid,
        web_url=f"https://gitlab.example.com/group/project/-/issues/{iid}",
        title=f"Work item {iid}",
        description=description,
        labels=["zeroone-work-item"],
    )


def test_lookup_skips_malformed_state_and_returns_matching_authoritative_issue() -> None:
    original = build_work_item()
    renderer = GitLabWorkItemRenderer()
    client = FakeGitLabWorkItemClient()
    client.open_issues = [
        issue(
            iid=1,
            description=(
                "<details>\n"
                "<summary><code>zeroone-work-item-state</code> machine state</summary>\n\n"
                "```json\n{not-json}\n```\n\n</details>\n"
            ),
        ),
        issue(iid=2, description=renderer.render_body(original)),
    ]

    result = GitLabWorkItemLookupService(client).find_open_work_item_by_source(  # type: ignore[arg-type]
        project_id="group/project",
        kind=original.kind,
        source=original.source,
    )

    assert result is not None
    assert result.issue.iid == 2
    assert client.list_labels == ["zeroone-work-item"]


def test_lookup_returns_no_match_for_duplicate_authoritative_identity(caplog) -> None:
    original = build_work_item()
    duplicate = original.model_copy(update={"work_item_id": "work-duplicate"})
    renderer = GitLabWorkItemRenderer()
    client = FakeGitLabWorkItemClient()
    client.open_issues = [
        issue(iid=1, description=renderer.render_body(original)),
        issue(iid=2, description=renderer.render_body(duplicate)),
    ]

    result = GitLabWorkItemLookupService(client).find_open_work_item_by_source(  # type: ignore[arg-type]
        project_id="group/project",
        kind=original.kind,
        source=original.source,
    )

    assert result is None
    assert any(
        "multiple GitLab work items share one authoritative identity" in message
        for message in caplog.messages
    )


def test_list_closed_work_items_marks_results_as_closed() -> None:
    original = build_work_item(status="dismissed")
    client = FakeGitLabWorkItemClient()
    client.closed_issues = [
        issue(iid=1, description=GitLabWorkItemRenderer().render_body(original))
    ]

    results = GitLabWorkItemLookupService(client).list_closed_work_items(  # type: ignore[arg-type]
        project_id="group/project"
    )

    assert len(results) == 1
    assert results[0].is_open is False
    assert results[0].work_item.status == "dismissed"


def test_lookup_returns_work_item_linked_to_change_request() -> None:
    work_item = build_work_item().model_copy(
        update={
            "linked_change_request": ChangeRequestRef(
                number=17,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
            )
        }
    )
    client = FakeGitLabWorkItemClient()
    client.open_issues = [issue(iid=1, description=GitLabWorkItemRenderer().render_body(work_item))]

    result = GitLabWorkItemLookupService(client).find_open_work_item_by_change_request(  # type: ignore[arg-type]
        project_id="group/project",
        change_request_number=17,
    )

    assert result is not None
    assert result.work_item.work_item_id == work_item.work_item_id


def test_lookup_rejects_duplicate_change_request_links(caplog) -> None:
    work_item = build_work_item().model_copy(
        update={
            "linked_change_request": ChangeRequestRef(
                number=17,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
            )
        }
    )
    duplicate = work_item.model_copy(
        update={
            "work_item_id": "work-duplicate",
            "source": work_item.source.model_copy(update={"source_item_key": "AX124"}),
        }
    )
    client = FakeGitLabWorkItemClient()
    client.open_issues = [
        issue(iid=1, description=GitLabWorkItemRenderer().render_body(work_item)),
        issue(iid=2, description=GitLabWorkItemRenderer().render_body(duplicate)),
    ]

    result = GitLabWorkItemLookupService(client).find_open_work_item_by_change_request(  # type: ignore[arg-type]
        project_id="group/project",
        change_request_number=17,
    )

    assert result is None
    assert any(
        "multiple GitLab remediation work items link to one change request" in message
        for message in caplog.messages
    )

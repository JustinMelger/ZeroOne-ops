from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)

from .test_support import FakeGitHubWorkItemClient, build_work_item


def test_lookup_skips_malformed_issue_state_during_scan() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item()
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=9,
            number=10,
            web_url="https://github.example.com/octo-org/octo-repo/issues/10",
            title="Malformed work item",
            body=(
                "<details>\n"
                "<summary><code>zeroone-work-item-state</code> machine state</summary>\n\n"
                "```json\n"
                "{not-json}\n"
                "```\n\n"
                "</details>\n"
            ),
        ),
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        ),
    ]

    result = GitHubWorkItemLookupService(client).find_open_work_item_by_source(
        repository_id="octo-org/octo-repo",
        kind=original.kind,
        source=original.source,
    )

    assert result is not None
    assert result.issue.number == 11


def test_lookup_filters_reuse_scan_to_authoritative_work_item_label() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item()
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

    result = GitHubWorkItemLookupService(client).find_open_work_item_by_source(
        repository_id="octo-org/octo-repo",
        kind=original.kind,
        source=original.source,
    )

    assert result is not None
    assert client.list_labels == ["zeroone-work-item"]


def test_list_open_work_items_returns_parseable_authoritative_records() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item()
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

    results = GitHubWorkItemLookupService(client).list_open_work_items(
        repository_id="octo-org/octo-repo"
    )

    assert [result.work_item for result in results] == [original]
    assert client.list_labels == ["zeroone-work-item"]
    assert all(result.is_open for result in results)


def test_list_closed_work_items_returns_parseable_authoritative_records() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item(status="completed")
    client = FakeGitHubWorkItemClient()
    client.closed_issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]

    results = GitHubWorkItemLookupService(client).list_closed_work_items(
        repository_id="octo-org/octo-repo"
    )

    assert [result.work_item for result in results] == [original]
    assert client.list_labels == ["zeroone-work-item"]
    assert not results[0].is_open


def test_lookup_skips_projection_when_multiple_work_items_link_one_change_request(caplog) -> None:
    renderer = GitHubWorkItemRenderer()
    first = build_work_item().model_copy(
        update={
            "linked_change_request": ChangeRequestRef(
                number=17,
                web_url="https://github.example.com/octo-org/octo-repo/pull/17",
            )
        }
    )
    duplicate = first.model_copy(update={"work_item_id": "work-2"})
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(first),
            body=renderer.render_body(first),
        ),
        GitHubIssueInfo(
            id=12,
            number=13,
            web_url="https://github.example.com/octo-org/octo-repo/issues/13",
            title=renderer.render_title(duplicate),
            body=renderer.render_body(duplicate),
        ),
    ]

    result = GitHubWorkItemLookupService(client).find_open_work_item_by_change_request(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
    )

    assert result is None
    assert (
        "multiple GitHub remediation work items link to one change request; "
        "review projection skipped"
    ) in caplog.messages

from __future__ import annotations

import httpx

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient


def build_config() -> GitLabConnectionConfig:
    return GitLabConnectionConfig(
        url="https://gitlab.example.com",
        token="token",
        project_id="group/project",
    )


def issue_payload(*, iid: int, state: str = "opened") -> dict[str, object]:
    return {
        "id": iid + 100,
        "iid": iid,
        "web_url": f"https://gitlab.example.com/group/project/-/issues/{iid}",
        "title": f"Work item {iid}",
        "description": "body",
        "labels": ["zeroone-work-item", "zeroone-status:approved"],
        "state": state,
        "created_at": "2026-08-07T10:00:00.000Z",
        "updated_at": "2026-08-07T11:00:00.000Z",
    }


def test_list_open_issues_paginates_and_normalizes_issue_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v4/projects/group/project/issues"
        assert b"group%2Fproject" in request.url.raw_path
        assert request.url.params.get("state") == "opened"
        assert request.url.params.get("labels") == "zeroone-work-item"
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(200, json=[issue_payload(iid=1)], headers={"X-Next-Page": "2"})
        assert page == "2"
        return httpx.Response(200, json=[issue_payload(iid=2)])

    client = GitLabWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    issues = client.list_open_issues(
        project_id="group/project",
        labels=["zeroone-work-item"],
    )

    assert [issue.iid for issue in issues] == [1, 2]
    assert issues[0].labels == ["zeroone-work-item", "zeroone-status:approved"]
    assert issues[0].state == "opened"
    assert issues[0].created_at is not None


def test_create_update_and_close_issue_send_full_work_item_state() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(201, json=issue_payload(iid=7))
        if request.method == "PUT" and request.url.path.endswith("/issues/7"):
            if request.content == b"state_event=close":
                return httpx.Response(200, json=issue_payload(iid=7, state="closed"))
            return httpx.Response(200, json=issue_payload(iid=7))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitLabWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    created = client.create_issue(
        project_id="group/project",
        title="Work item 7",
        description="created body",
        labels=["zeroone-work-item", "zeroone-status:approved"],
    )
    updated = client.update_issue(
        project_id="group/project",
        issue_iid=7,
        title="Updated work item 7",
        description="updated body",
        labels=["zeroone-work-item", "zeroone-status:in_progress"],
    )
    closed = client.close_issue(project_id="group/project", issue_iid=7)

    assert created.iid == 7
    assert updated.iid == 7
    assert closed.state == "closed"
    assert requests[0].content == (
        b"title=Work+item+7&description=created+body&"
        b"labels=zeroone-work-item%2Czeroone-status%3Aapproved"
    )
    assert requests[1].content == (
        b"title=Updated+work+item+7&description=updated+body&"
        b"labels=zeroone-work-item%2Czeroone-status%3Ain_progress"
    )


def test_list_issue_notes_and_looks_up_effective_member_access() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues/7/notes"):
            assert request.url.params.get("page") == "1"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "body": "/zeroone remediation requeue",
                        "created_at": "2026-08-07T10:00:00.000Z",
                        "author": {"id": 8, "username": "maintainer"},
                    }
                ],
            )
        assert request.url.path == "/api/v4/projects/group/project/members/all/8"
        assert b"group%2Fproject" in request.url.raw_path
        return httpx.Response(200, json={"id": 8, "access_level": 40})

    client = GitLabWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    notes = client.list_issue_notes(project_id="group/project", issue_iid=7)
    access_level = client.get_project_member_access_level(project_id="group/project", user_id=8)

    assert notes[0].id == 42
    assert notes[0].author_username == "maintainer"
    assert access_level == 40

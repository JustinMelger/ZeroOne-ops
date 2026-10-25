"""Exercise shared description projection through real GitHub/GitLab transports."""

import json
from unittest.mock import Mock
from urllib.parse import parse_qs

import httpx
import pytest
from test_publish_service import build_config, build_issue

from zeroone_ops.models.config import GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.work_item import ChangeRequestRef
from zeroone_ops.providers.github_client import GitHubClient
from zeroone_ops.providers.gitlab_client import GitLabClient
from zeroone_ops.services.remediation.change_request_publisher import (
    GitHubRemediationChangeRequestPublisher,
    GitLabRemediationChangeRequestPublisher,
)
from zeroone_ops.services.remediation.publication_evidence import (
    EVIDENCE_START,
    render_publication_evidence,
)
from zeroone_ops.services.remediation.publish_service import PublishService
from zeroone_ops.services.remediation.revision_evidence_projection import (
    refresh_revision_description,
)
from zeroone_ops.services.shared.projection_payload import ProjectionSizeExceeded


@pytest.fixture(params=["github", "gitlab"])
def description_publisher(request):
    platform = request.param
    calls = []
    document = dict(
        description="Operator note\n## Semantic Safety\nEarlier rationale.",
        sha="published",
        branch="remediation",
        state="opened",
        number=7,
    )

    def handler(req):
        calls.append(req)
        expected_path = (
            "/repos/org/repo/pulls/7"
            if platform == "github"
            else "/api/v4/projects/123/merge_requests/7"
        )
        assert req.url.path == expected_path
        if req.method == "GET":
            if document.get("read_failure"):
                return httpx.Response(503, json={"message": "private diagnostics"})
            if platform == "github":
                payload = dict(
                    number=document["number"],
                    html_url="https://example/pr/7",
                    state="open" if document["state"] == "opened" else document["state"],
                    merged_at=None,
                    head=dict(ref=document["branch"], sha=document["sha"]),
                    body=document["description"],
                )
            else:
                payload = dict(
                    iid=document["number"],
                    web_url="https://example/mr/7",
                    title="Keep title",
                    state=document["state"],
                    source_branch=document["branch"],
                    sha=document["sha"],
                    description=document["description"],
                )
            return httpx.Response(200, json=payload)
        assert req.method == ("PATCH" if platform == "github" else "PUT")
        if document.get("write_failure"):
            return httpx.Response(403, json={"message": "private diagnostics"})
        payload = (
            json.loads(req.content) if platform == "github" else parse_qs(req.content.decode())
        )
        assert set(payload) == {"body" if platform == "github" else "description"}
        document["description"] = (
            payload["body"] if platform == "github" else payload["description"][0]
        )
        return httpx.Response(200, json={})

    http_client = httpx.Client(base_url="https://example", transport=httpx.MockTransport(handler))
    if platform == "github":
        publisher = GitHubRemediationChangeRequestPublisher(
            GitHubClient(
                GitHubConnectionConfig(
                    token="token",
                    repository="org/repo",
                    api_url="https://example",
                    server_url="https://example",
                ),
                http_client=http_client,
            )
        )
    else:
        publisher = GitLabRemediationChangeRequestPublisher(
            GitLabClient(
                GitLabConnectionConfig(url="https://example", token="token", project_id="123"),
                http_client=http_client,
            )
        )
    return publisher, calls, document


def refresh(publisher, *, is_batch=True):
    refresh_revision_description(
        publisher=publisher,
        number=7,
        source_branch="remediation",
        commit_sha="published",
        evidence=render_publication_evidence(commit_sha="published"),
        is_batch=is_batch,
    )


def test_exact_request_description_only_update_and_repeated_refresh(description_publisher):
    publisher, calls, document = description_publisher
    original = document["description"]
    refresh(publisher)
    assert document["description"].endswith(original)
    assert document["description"].count(EVIDENCE_START) == 1
    assert "Published commit: `published`" in document["description"]
    assert "Validation evidence unavailable" in document["description"]
    refresh(publisher)
    assert [call.method for call in calls] in (["GET", "PATCH", "GET"], ["GET", "PUT", "GET"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "closed"),
        ("state", "merged"),
        ("sha", "moved"),
        ("branch", "different"),
        ("number", 8),
    ],
)
def test_changed_request_is_never_updated(description_publisher, field, value):
    publisher, calls, document = description_publisher
    document[field] = value
    with pytest.raises(ValueError, match="no longer matches"):
        refresh(publisher)
    assert len(calls) == 1


def test_malformed_markers_are_preserved_without_update(description_publisher):
    publisher, calls, document = description_publisher
    document["description"] = EVIDENCE_START + "\nOperator text"
    with pytest.raises(ValueError, match="incomplete or ambiguous"):
        refresh(publisher)
    assert len(calls) == 1
    assert document["description"] == EVIDENCE_START + "\nOperator text"


def test_full_utf8_payload_budget_is_checked_before_transport(description_publisher):
    publisher, calls, document = description_publisher
    overhead = len((render_publication_evidence(commit_sha="published") + "\n\n").encode())
    remaining = 60_000 - overhead
    document["description"] = "é" * (remaining // 2) + "x" * (remaining % 2)
    refresh(publisher)
    assert len(document["description"].encode()) == 60_000
    document["description"] += "é"
    count = len(calls)
    with pytest.raises(ProjectionSizeExceeded):
        refresh(publisher)
    assert len(calls) == count + 1


def test_nullable_description_is_empty_not_a_transport_failure(description_publisher):
    publisher, _, document = description_publisher
    document["description"] = None
    refresh(publisher)
    assert "Latest Revision Evidence" in document["description"]


@pytest.mark.parametrize("description", [[], 1])
def test_malformed_description_is_not_treated_as_empty(description_publisher, description):
    publisher, calls, document = description_publisher
    document["description"] = description
    with pytest.raises(RuntimeError):
        refresh(publisher)
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["read", "write", "closed", "markers", "oversized", "render"])
def test_projection_failures_are_bounded_warnings_without_description_contents(
    description_publisher, failure, caplog, monkeypatch
):
    publisher, calls, document = description_publisher
    if failure in {"read", "write"}:
        document[f"{failure}_failure"] = True
    elif failure == "closed":
        document["state"] = "closed"
    elif failure == "markers":
        document["description"] = EVIDENCE_START
    elif failure == "oversized":
        document["description"] = "é" * 30_000
    else:
        monkeypatch.setattr(
            "zeroone_ops.services.remediation.publish_service.render_publication_evidence",
            Mock(side_effect=ValueError("private diagnostics")),
        )
    target = build_issue().model_copy(
        update={
            "revision_change_request": ChangeRequestRef(number=7, web_url="https://example/7"),
            "batch": Mock(),
        }
    )
    service = PublishService(
        config=build_config(),
        branch_manager=Mock(),
        change_request_publisher=publisher,
    )
    before = document["description"]
    warning = service.refresh_revision_evidence(
        selected_issue=target,
        source_branch="remediation",
        commit_sha="published",
        validation_result=None,
        validation_comparison=None,
        semantic_safety=None,
    )
    assert "revision was published" in warning
    assert "description evidence could not be refreshed and may be stale" in warning
    assert "private diagnostics" not in warning + caplog.text
    assert document["description"] == before
    assert "description may be stale" in caplog.text

"""Small in-memory HTTP responses behind the real GitHub and GitLab clients."""

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qsl

import httpx

Platform = Literal["github", "gitlab"]
REPOSITORY_SCOPE = "offline/application"


@dataclass
class ScenarioProviderAPI:
    """Store native response payloads, never a parallel work-item domain state."""

    platform: Platform
    repository_scope: str = REPOSITORY_SCOPE
    target_branch: str = "main"
    issues: dict[int, dict[str, object]] = field(default_factory=dict)
    requests: dict[int, dict[str, object]] = field(default_factory=dict)
    issue_writes: list[dict[str, object]] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)
    branch_head_lookup: Callable[[str], str | None] | None = None
    allow_request_reuse: bool = False
    issue_comments: dict[int, list[dict[str, object]]] = field(default_factory=dict)
    repository_permissions: dict[str, str | None] = field(default_factory=dict)
    project_access_levels: dict[int, int | None] = field(default_factory=dict)

    def respond(self, request: httpx.Request) -> httpx.Response:
        """Fail closed for endpoints outside the exercised installation contract."""
        assert request.url.scheme == "https" and request.url.host == "provider.invalid", (
            "Unexpected provider origin"
        )
        prefix = (
            f"/repos/{self.repository_scope}"
            if self.platform == "github"
            else f"/api/v4/projects/{self.repository_scope}"
        )
        assert request.url.path.startswith(f"{prefix}/"), "Unexpected repository/project scope"
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        issues_path = f"{prefix}/issues"
        requests_path = f"{prefix}/" + ("pulls" if self.platform == "github" else "merge_requests")
        branch_path = f"{prefix}/" + (
            "git/ref/heads/" if self.platform == "github" else "repository/branches/"
        )
        permission_prefix = f"{prefix}/collaborators/"
        member_prefix = f"{prefix}/members/all/"
        if self.platform == "github" and path.startswith(permission_prefix):
            suffix = path.removeprefix(permission_prefix)
            assert request.method == "GET" and suffix.endswith("/permission")
            username = suffix.removesuffix("/permission")
            assert username in self.repository_permissions, "Unexpected permission lookup"
            permission = self.repository_permissions[username]
            return httpx.Response(
                503 if permission is None else 200, json={"permission": permission}
            )
        if self.platform == "gitlab" and path.startswith(member_prefix):
            identifier = path.removeprefix(member_prefix)
            assert request.method == "GET" and identifier.isdigit()
            assert int(identifier) in self.project_access_levels, "Unexpected member lookup"
            access = self.project_access_levels[int(identifier)]
            return httpx.Response(503 if access is None else 200, json={"access_level": access})
        if path.startswith(branch_path):
            assert request.method == "GET" and self.branch_head_lookup is not None
            sha = self.branch_head_lookup(path.removeprefix(branch_path))
            return httpx.Response(
                404 if sha is None else 200,
                json={"object": {"sha": sha}, "commit": {"id": sha}},
            )
        if path.startswith(f"{requests_path}/"):
            number = path.removeprefix(f"{requests_path}/")
            assert request.method == "GET" and number.isdigit()
            assert int(number) in self.requests and self.branch_head_lookup is not None
            payload = self.requests[int(number)]
            branch = str(payload["head" if self.platform == "github" else "source_branch"])
            return httpx.Response(
                200,
                json=payload
                | {
                    "head": {"ref": branch, "sha": self.branch_head_lookup(branch)},
                    "source_branch": branch,
                    "sha": self.branch_head_lookup(branch),
                    "merged": payload.get("merged_at") is not None,
                },
            )
        if path == issues_path:
            return self._issues_response(request)
        if path == requests_path:
            return self._requests_response(request)
        if path.startswith(f"{issues_path}/"):
            suffix = path.removeprefix(f"{issues_path}/")
            comment_kind = "comments" if self.platform == "github" else "notes"
            if suffix.endswith(f"/{comment_kind}"):
                number = suffix.removesuffix(f"/{comment_kind}")
                assert request.method == "GET" and number.isdigit()
                assert int(number) in self.issues and int(number) in self.issue_comments
                assert dict(request.url.params) == {"page": "1", "per_page": "100"}
                return httpx.Response(200, json=self.issue_comments[int(number)])
            if (
                self.platform == "github"
                and suffix.endswith("/labels")
                and request.method == "POST"
            ):
                assert int(suffix.split("/")[0]) in self.requests
                return httpx.Response(200, json=[])
            assert suffix.isdigit(), f"Unexpected issue endpoint: {path}"
            number = int(suffix)
            if request.method == "GET":
                return httpx.Response(200, json=self.issues[number])
            expected_method = "PATCH" if self.platform == "github" else "PUT"
            assert request.method == expected_method, "Unexpected issue update method"
            fields = self._payload(request)
            if self.platform == "github":
                assert "state_event" not in fields, "Unexpected GitHub state_event"
                if "state" in fields:
                    assert fields["state"] in {"open", "closed"}, "Unexpected GitHub state"
            else:
                assert "state" not in fields, "GitLab issue state requires state_event"
            if "state_event" in fields:
                event = fields.pop("state_event")
                assert event in {"close", "reopen"}, "Unexpected GitLab state_event"
                fields["state"] = "closed" if event == "close" else "opened"
            self.issues[number].update(fields)
            self.issue_writes.append(deepcopy(self.issues[number]))
            return httpx.Response(200, json=self.issues[number])
        raise AssertionError(f"Unexpected provider request: {request.method} {path}")

    def _issues_response(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            labels = set(filter(None, request.url.params.get("labels", "").split(",")))
            state = request.url.params["state"]
            assert request.url.params.get("page") == "1"
            matches = [
                issue
                for issue in self.issues.values()
                if issue["state"] == state and labels.issubset(issue["labels"])
            ]
            return httpx.Response(200, json=matches)
        assert request.method == "POST"
        number = len(self.issues) + 1
        issue = self._native_payload(number, self._payload(request), "issues")
        self.issues[number] = issue
        self.issue_writes.append(deepcopy(issue))
        return httpx.Response(201, json=issue)

    def _requests_response(self, request: httpx.Request) -> httpx.Response:
        target_key = "base" if self.platform == "github" else "target_branch"
        if request.method == "GET":
            assert request.url.params.get(target_key) == self.target_branch, (
                "Unexpected request target branch"
            )
            if self.requests:
                assert self.allow_request_reuse, "Scenario unexpectedly searched after publication"
                source = request.url.params[
                    "head" if self.platform == "github" else "source_branch"
                ]
                if self.platform == "github":
                    source = source.split(":", 1)[-1]
                return httpx.Response(
                    200,
                    json=[
                        payload
                        for payload in self.requests.values()
                        if payload["head" if self.platform == "github" else "source_branch"]
                        == source
                    ],
                )
            return httpx.Response(200, json=[])
        assert request.method == "POST"
        fields = self._payload(request)
        assert fields.get(target_key) == self.target_branch, "Unexpected request target branch"
        assert not self.requests, "Scenario attempted duplicate request creation"
        number = 100
        payload = self._native_payload(number, fields, "requests")
        self.requests[number] = payload
        return httpx.Response(201, json=payload)

    def _native_payload(
        self, number: int, fields: dict[str, object], kind: str
    ) -> dict[str, object]:
        return {
            "id": number,
            "number": number,
            "iid": number,
            "html_url": f"https://provider.invalid/{kind}/{number}",
            "web_url": f"https://provider.invalid/{kind}/{number}",
            "state": "open" if self.platform == "github" else "opened",
            "created_at": "2026-01-01T00:00:00Z",
            "labels": [],
            **fields,
        }

    def _payload(self, request: httpx.Request) -> dict[str, object]:
        if self.platform == "github":
            return json.loads(request.content)
        fields: dict[str, object] = dict(parse_qsl(request.content.decode()))
        if "labels" in fields:
            fields["labels"] = list(filter(None, str(fields["labels"]).split(",")))
        return fields

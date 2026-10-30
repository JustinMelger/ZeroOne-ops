"""Native review HTTP storage behind real provider intake and publication clients."""

import json
from dataclasses import dataclass, field
from urllib.parse import parse_qsl

import httpx
import pytest

from .provider_api import ScenarioProviderAPI
from .review_cases import REVIEW_PATH, ReviewCase


@dataclass
class ReviewProviderAPI:
    """Store request-specific native comments without constructing review decisions."""

    work_items: ScenarioProviderAPI
    cases: dict[int, ReviewCase] = field(default_factory=dict)
    comments: dict[int, dict[int, dict[str, object]]] = field(default_factory=dict)
    inline_comments: dict[int, list[dict[str, object]]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    active_number: int | None = None
    published_heads: set[tuple[int, str]] = field(default_factory=set)

    def respond(self, request: httpx.Request) -> httpx.Response:
        """Fail hard even if production treats a transport boundary as best effort."""
        try:
            return self._respond(request)
        except AssertionError as error:
            pytest.fail(str(error), pytrace=False)

    def _respond(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "provider.invalid" and request.url.scheme == "https", (
            "Wrong review provider origin"
        )
        self.calls.append((request.method, request.url.path))
        github = self.work_items.platform == "github"
        user_path = "/user" if github else "/api/v4/user"
        if request.url.path == user_path:
            assert request.method == "GET"
            return httpx.Response(200, json={"login": "offline-bot", "username": "offline-bot"})
        prefix = (
            f"/repos/{self.work_items.repository_scope}/"
            if github
            else f"/api/v4/projects/{self.work_items.repository_scope}/"
        )
        assert request.url.path.startswith(prefix), "Wrong review repository/project scope"
        suffix = request.url.path.removeprefix(prefix)
        parts = suffix.split("/")
        request_kind = "pulls" if github else "merge_requests"
        if parts[0] == request_kind and len(parts) >= 2:
            assert parts[1].isdigit() and int(parts[1]) in self.cases, "Unknown review request"
            number = int(parts[1])
            assert number == self.active_number, "Cross-request review access"
            case = self.cases[number]
            if len(parts) == 2 or (not github and parts[2:] == ["changes"]):
                assert request.method == "GET"
                return httpx.Response(200, json=self._metadata(case))
            if github and parts[2:] == ["files"]:
                assert request.method == "GET"
                return httpx.Response(
                    200,
                    json=[
                        {
                            "filename": REVIEW_PATH,
                            "status": "modified",
                            "patch": case.diff,
                        }
                    ],
                )
            if (
                (github and parts[2:] == ["comments"])
                or (not github and parts[2:] == ["discussions"])
                or (not github and parts[2] == "notes" and len(parts) in {3, 4})
            ):
                return self._comment_response(request, case, parts[2:], inline=parts[2] != "notes")
        if github and parts[0] == "issues":
            if len(parts) == 3 and parts[1].isdigit() and parts[2] == "comments":
                number = int(parts[1])
                assert number == self.active_number and number in self.cases, (
                    "Cross-request comment access"
                )
                return self._comment_response(request, self.cases[number], parts[2:], inline=False)
            if len(parts) == 3 and parts[1] == "comments":
                assert self.active_number in self.cases
                return self._update_comment(request, self.active_number, int(parts[2]))
        return self.work_items.respond(request)

    def _metadata(self, case: ReviewCase) -> dict[str, object]:
        return {
            "number": case.number,
            "iid": case.number,
            "title": f"Review {case.marker}",
            "body": "",
            "description": "",
            "html_url": case.url,
            "web_url": case.url,
            "head": {"ref": case.branch, "sha": case.head_sha},
            "base": {"ref": "main", "sha": case.base_sha},
            "source_branch": case.branch,
            "target_branch": "main",
            "sha": case.head_sha,
            "state": "open" if self.work_items.platform == "github" else "opened",
            "diff_refs": {
                "base_sha": case.base_sha,
                "start_sha": case.base_sha,
                "head_sha": case.head_sha,
            },
            "changes": [{"old_path": REVIEW_PATH, "new_path": REVIEW_PATH, "diff": case.diff}],
        }

    def _comment_response(
        self, request: httpx.Request, case: ReviewCase, parts: list[str], *, inline: bool
    ) -> httpx.Response:
        notes = self.comments.setdefault(case.number, {})
        if request.method == "GET":
            assert not inline, "Unexpected inline comment inventory"
            return httpx.Response(200, json=list(notes.values()))
        if len(parts) == 2:
            return self._update_comment(request, case.number, int(parts[1]))
        assert request.method == "POST", "Unexpected review publication method"
        fields = self._fields(request)
        if inline:
            if self.work_items.platform == "github":
                assert fields["commit_id"] == case.head_sha and fields["path"] == REVIEW_PATH
                line = fields["line"]
            else:
                assert fields["position[head_sha]"] == case.head_sha
                assert fields["position[base_sha]"] == case.base_sha
                assert fields["position[start_sha]"] == case.base_sha
                assert fields["position[new_path]"] == fields["position[old_path]"] == REVIEW_PATH
                line = int(str(fields["position[new_line]"]))
            assert line == case.finding.line_start, "Wrong inline finding location"
        else:
            identity = (case.number, case.head_sha)
            assert identity not in self.published_heads, "Duplicate authoritative review comment"
            self.published_heads.add(identity)
        note_id = case.number * 100 + (
            len(self.inline_comments.get(case.number, [])) * 10 + 2
            if inline
            else len(notes) * 10 + 1
        )
        note = {
            "id": note_id,
            "body": fields["body"],
            "html_url": f"{case.url}#note-{note_id}",
            "web_url": f"{case.url}#note-{note_id}",
            "created_at": "2026-01-01T00:00:00Z",
            "user": {"login": "offline-bot"},
            "author": {"username": "offline-bot"},
        }
        if inline:
            self.inline_comments.setdefault(case.number, []).append(note)
        else:
            notes[note_id] = note
        payload = (
            {"id": str(note_id), "notes": [note]}
            if inline and self.work_items.platform == "gitlab"
            else note
        )
        return httpx.Response(201, json=payload)

    def _update_comment(self, request: httpx.Request, number: int, note_id: int) -> httpx.Response:
        expected_method = "PATCH" if self.work_items.platform == "github" else "PUT"
        assert request.method == expected_method, "Unexpected review update method"
        notes = self.comments[number]
        assert note_id in notes, "Cross-request review comment update"
        notes[note_id]["body"] = self._fields(request)["body"]
        return httpx.Response(200, json=notes[note_id])

    def _fields(self, request: httpx.Request) -> dict[str, object]:
        if self.work_items.platform == "github":
            return json.loads(request.content)
        return dict(parse_qsl(request.content.decode()))

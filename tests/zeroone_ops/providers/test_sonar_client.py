from __future__ import annotations

import httpx
import pytest

from zeroone_ops.models.config import SonarQubeConnectionConfig
from zeroone_ops.providers.sonar_client import SonarClient, SonarClientError


def build_config() -> SonarQubeConnectionConfig:
    return SonarQubeConnectionConfig(
        url="https://sonarqube.example.com",
        token="token",
        project_key="sample-project",
    )


def test_search_open_issues_normalizes_project_prefixed_component() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/issues/search"
        assert request.url.params["projects"] == "sample-project"
        return httpx.Response(
            200,
            json={
                "paging": {"pageIndex": 1, "pageSize": 100, "total": 1},
                "issues": [
                    {
                        "key": "AX12345",
                        "rule": "python:S2259",
                        "severity": "MAJOR",
                        "type": "BUG",
                        "status": "OPEN",
                        "message": "Add a null check.",
                        "component": "sample-project:src/service.py",
                        "project": "sample-project",
                        "line": 12,
                        "impacts": [
                            {
                                "softwareQuality": "MAINTAINABILITY",
                                "severity": "LOW",
                            }
                        ],
                        "effort": "5min",
                        "tags": ["cwe", "bug"],
                        "creationDate": "2026-03-27T10:00:00+0000",
                    }
                ],
            },
        )

    client = SonarClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://sonarqube.example.com",
        ),
    )

    issues = client.search_open_issues()

    assert len(issues) == 1
    assert issues[0].file_path == "src/service.py"
    assert issues[0].line == 12
    assert issues[0].impacts[0].software_quality == "MAINTAINABILITY"
    assert issues[0].impacts[0].severity == "LOW"
    assert issues[0].creation_date is not None


def test_search_open_issues_accepts_mqr_only_severity_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "paging": {"pageIndex": 1, "pageSize": 100, "total": 1},
                "issues": [
                    {
                        "key": "AX20001",
                        "rule": "python:S1125",
                        "type": "CODE_SMELL",
                        "status": "OPEN",
                        "message": "Boolean literals should not be used in comparisons.",
                        "component": "sample-project:samples/auto_fixable_example.py",
                        "project": "sample-project",
                        "line": 2,
                        "impacts": [
                            {
                                "softwareQuality": "MAINTAINABILITY",
                                "severity": "LOW",
                            }
                        ],
                    }
                ],
            },
        )

    client = SonarClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://sonarqube.example.com",
        ),
    )

    issues = client.search_open_issues()

    assert issues[0].severity == "UNKNOWN"
    assert issues[0].matches_supported_severities(["LOW"]) is True


def test_get_issue_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/issues/show"
        return httpx.Response(404, json={"errors": [{"msg": "Not found"}]})

    client = SonarClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://sonarqube.example.com",
        ),
    )

    try:
        client.get_issue("AX404")
    except SonarClientError as error:
        assert "status 404" in str(error)
    else:
        raise AssertionError("Expected SonarClientError to be raised.")


def _issue_payload(key: str) -> dict[str, str]:
    return {
        "key": key,
        "rule": "python:S1125",
        "severity": "MAJOR",
        "type": "CODE_SMELL",
        "status": "OPEN",
        "message": "Simplify comparison.",
        "component": "sample-project:src/service.py",
        "project": "sample-project",
    }


@pytest.mark.parametrize("total", [0, 1, 2, 3, 4, 5])
def test_pagination_collects_complete_inventory(
    total: int, caplog: pytest.LogCaptureFixture
) -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["p"])
        assert request.url.params["ps"] == "2"
        pages.append(page)
        start = (page - 1) * 2
        return httpx.Response(
            200,
            json={
                "paging": {"pageIndex": page, "pageSize": 2, "total": total},
                "issues": [_issue_payload(str(i)) for i in range(start, min(start + 2, total))],
            },
        )

    client = SonarClient(
        build_config().model_copy(update={"page_size": 2}),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://sonarqube.example.com"
        ),
    )
    with caplog.at_level("INFO"):
        issues = client.search_open_issues()
    expected_pages = max(1, (total + 1) // 2)
    assert pages == list(range(1, expected_pages + 1))
    assert [issue.key for issue in issues] == [str(i) for i in range(total)]
    assert f"pages={expected_pages} findings={total}" in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        "http",
        "transport",
        "json",
        "missing_paging",
        "missing_total",
        "string_total",
        "bool_total",
        "negative_total",
        "changed_total",
        "repeated_page",
        "wrong_size",
        "empty_page",
        "missing_issues",
        "repeated_key",
        "malformed_issue",
        "invalid_issue",
        "pagination_limit",
    ],
)
def test_later_page_failure_discards_partial_inventory(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        page = int(request.url.params["p"])
        payload = {
            "paging": {"pageIndex": page, "pageSize": 1, "total": 2},
            "issues": [_issue_payload(str(page))],
        }
        if page == 1:
            return httpx.Response(200, json=payload)
        if failure in {"http", "pagination_limit"}:
            return httpx.Response(503 if failure == "http" else 400, text="secret-response")
        if failure == "transport":
            raise httpx.ReadTimeout("secret-token", request=request)
        if failure == "json":
            return httpx.Response(200, text="secret-response")
        if failure == "missing_paging":
            del payload["paging"]
        elif failure == "missing_total":
            del payload["paging"]["total"]
        elif failure in {"string_total", "bool_total", "negative_total", "changed_total"}:
            payload["paging"]["total"] = {
                "string_total": "2",
                "bool_total": True,
                "negative_total": -1,
                "changed_total": 3,
            }[failure]
        elif failure == "repeated_page":
            payload["paging"]["pageIndex"] = 1
        elif failure == "wrong_size":
            payload["paging"]["pageSize"] = 2
        elif failure == "empty_page":
            payload["issues"] = []
        elif failure == "missing_issues":
            del payload["issues"]
        elif failure == "repeated_key":
            payload["issues"] = [_issue_payload("1")]
        elif failure == "malformed_issue":
            payload["issues"] = [None]
        elif failure == "invalid_issue":
            payload["issues"] = [{"key": "2"}]
        return httpx.Response(200, json=payload)

    client = SonarClient(
        build_config().model_copy(update={"page_size": 1}),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://sonarqube.example.com"
        ),
    )
    with pytest.raises(SonarClientError, match="page 2; partial results discarded"):
        client.search_open_issues()
    assert calls == 2
    assert "page=2 collected=1" in caplog.text
    assert "secret" not in caplog.text

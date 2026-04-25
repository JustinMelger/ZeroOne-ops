from __future__ import annotations

import httpx

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
                ]
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
                ]
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

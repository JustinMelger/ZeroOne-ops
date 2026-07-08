from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.services.shared.change_request_lookup import (
    GitHubChangeRequestLookup,
    GitLabChangeRequestLookup,
    build_change_request_lookup,
)


class StubGitLabClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"project_id": "group/project"})()
        self.requested: tuple[str, str, str] | None = None

    def find_open_merge_request(
        self,
        *,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo:
        self.requested = (project_id, source_branch, target_branch)
        return ChangeRequestInfo(
            iid=7,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/7",
            title="fix: patch service",
        )


class StubGitHubClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"repository": "octo-org/octo-repo"})()
        self.requested: tuple[str, str, str] | None = None

    def find_open_pull_request(
        self,
        *,
        repository_id: str,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo:
        self.requested = (repository_id, source_branch, target_branch)
        return ChangeRequestInfo(
            iid=9,
            web_url="https://github.com/octo-org/octo-repo/pull/9",
            title="fix: patch service",
        )


def build_gitlab_config() -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        platform="gitlab",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            target_branch="main",
            bootstrap_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(labels=[]),
    )


def build_github_config() -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        platform="github",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            target_branch="main",
            bootstrap_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
    )


def test_gitlab_change_request_lookup_delegates_to_gitlab_client() -> None:
    client = StubGitLabClient()
    lookup = GitLabChangeRequestLookup(client)  # type: ignore[arg-type]

    change_request = lookup.find_open_change_request(
        source_branch="zeroone-ops/issue-1/service",
        target_branch="main",
    )

    assert change_request.iid == 7
    assert client.requested == ("group/project", "zeroone-ops/issue-1/service", "main")


def test_github_change_request_lookup_delegates_to_github_client() -> None:
    client = StubGitHubClient()
    lookup = GitHubChangeRequestLookup(client)  # type: ignore[arg-type]

    change_request = lookup.find_open_change_request(
        source_branch="zeroone-ops/issue-1/service",
        target_branch="main",
    )

    assert change_request.iid == 9
    assert client.requested == ("octo-org/octo-repo", "zeroone-ops/issue-1/service", "main")


def test_build_change_request_lookup_returns_gitlab_lookup(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")

    lookup = build_change_request_lookup(build_gitlab_config())

    assert isinstance(lookup, GitLabChangeRequestLookup)


def test_build_change_request_lookup_returns_github_lookup(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")

    lookup = build_change_request_lookup(build_github_config())

    assert isinstance(lookup, GitHubChangeRequestLookup)

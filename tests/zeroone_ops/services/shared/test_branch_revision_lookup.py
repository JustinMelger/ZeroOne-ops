from zeroone_ops.services.shared.branch_revision_lookup import (
    GitHubBranchRevisionLookup,
    GitLabBranchRevisionLookup,
)


class StubGitHubClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"repository": "octo-org/octo-repo"})()
        self.requested: tuple[str, str] | None = None

    def get_branch_head_sha(self, *, repository_id: str, branch_name: str) -> str:
        self.requested = (repository_id, branch_name)
        return "abc123"


class StubGitLabClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"project_id": "group/project"})()
        self.requested: tuple[str, str] | None = None

    def get_branch_head_sha(self, *, project_id: str, branch_name: str) -> str:
        self.requested = (project_id, branch_name)
        return "abc123"


def test_github_branch_revision_lookup_delegates_to_github_client() -> None:
    client = StubGitHubClient()

    sha = GitHubBranchRevisionLookup(client).get_branch_head_sha(branch_name="zeroone-ops/fix")  # type: ignore[arg-type]

    assert sha == "abc123"
    assert client.requested == ("octo-org/octo-repo", "zeroone-ops/fix")


def test_gitlab_branch_revision_lookup_delegates_to_gitlab_client() -> None:
    client = StubGitLabClient()

    sha = GitLabBranchRevisionLookup(client).get_branch_head_sha(branch_name="zeroone-ops/fix")  # type: ignore[arg-type]

    assert sha == "abc123"
    assert client.requested == ("group/project", "zeroone-ops/fix")

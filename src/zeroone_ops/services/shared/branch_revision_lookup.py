"""Provider-local branch revision lookup seams for shared remediation recovery."""

from __future__ import annotations

from typing import Protocol

from zeroone_ops.models.config import AppConfig
from zeroone_ops.providers.github_client import GitHubClient
from zeroone_ops.providers.gitlab_client import GitLabClient
from zeroone_ops.settings import (
    load_github_connection_config,
    load_gitlab_connection_config,
)


class BranchRevisionLookup(Protocol):
    """Read the current remote SHA for one provider-backed source branch."""

    def get_branch_head_sha(self, *, branch_name: str) -> str | None:
        """Return the remote branch SHA, or ``None`` when it no longer exists."""


class GitHubBranchRevisionLookup:
    """Look up GitHub branch revisions for recovery verification."""

    def __init__(self, github_client: GitHubClient) -> None:
        """Initialize the GitHub-backed lookup."""
        self.github_client = github_client

    def get_branch_head_sha(self, *, branch_name: str) -> str | None:
        """Return the current SHA for one GitHub branch."""
        return self.github_client.get_branch_head_sha(
            repository_id=self.github_client.config.repository,
            branch_name=branch_name,
        )


class GitLabBranchRevisionLookup:
    """Look up GitLab branch revisions for recovery verification."""

    def __init__(self, gitlab_client: GitLabClient) -> None:
        """Initialize the GitLab-backed lookup."""
        self.gitlab_client = gitlab_client

    def get_branch_head_sha(self, *, branch_name: str) -> str | None:
        """Return the current SHA for one GitLab branch."""
        return self.gitlab_client.get_branch_head_sha(
            project_id=self.gitlab_client.config.project_id,
            branch_name=branch_name,
        )


def build_branch_revision_lookup(config: AppConfig) -> BranchRevisionLookup:
    """Build the provider-local branch lookup used by remediation recovery."""
    if config.platform == "github":
        return GitHubBranchRevisionLookup(GitHubClient(load_github_connection_config()))
    if config.platform == "gitlab":
        return GitLabBranchRevisionLookup(GitLabClient(load_gitlab_connection_config()))
    raise RuntimeError(f"Unsupported remediation recovery platform: {config.platform}")

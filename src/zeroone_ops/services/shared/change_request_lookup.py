"""Provider-local change-request lookup seams."""

from __future__ import annotations

from typing import Protocol

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.providers.gitlab_client import GitLabClient
from zeroone_ops.settings import load_gitlab_connection_config


class ChangeRequestLookup(Protocol):
    """Look up active provider-backed change requests for shared orchestration."""

    def find_open_change_request(
        self,
        *,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo | None:
        """Return one open change request for the source and target branch pair."""


class GitLabChangeRequestLookup:
    """Look up active GitLab merge requests for shared orchestration."""

    def __init__(self, gitlab_client: GitLabClient) -> None:
        """Initialize the GitLab-backed change-request lookup."""
        self.gitlab_client = gitlab_client

    def find_open_change_request(
        self,
        *,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo | None:
        """Return one open GitLab merge request for the source and target branches."""
        return self.gitlab_client.find_open_merge_request(
            project_id=self.gitlab_client.config.project_id,
            source_branch=source_branch,
            target_branch=target_branch,
        )


def build_change_request_lookup(config: AppConfig) -> ChangeRequestLookup | None:
    """Build the provider-local lookup used by shared orchestration."""
    if config.platform == "gitlab":
        return GitLabChangeRequestLookup(GitLabClient(load_gitlab_connection_config()))
    if config.platform == "github":
        return None
    raise RuntimeError(f"Unsupported change-request lookup platform: {config.platform}")

"""Provider-neutral remediation change-request publishing seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.providers.gitlab_client import GitLabClient, GitLabClientError
from zeroone_ops.settings import load_gitlab_connection_config


@dataclass(frozen=True)
class ChangeRequestPublishRequest:
    """Represent one provider-neutral remediation change-request publish request."""

    source_branch: str
    target_branch: str
    title: str
    description: str
    labels: list[str]
    assignee_username: str | None = None


@dataclass(frozen=True)
class PublishedChangeRequest:
    """Represent one created or reused change request."""

    info: ChangeRequestInfo
    action: Literal["created", "reused"]


class RemediationChangeRequestPublisher(Protocol):
    """Publish remediation change requests through one provider-local implementation."""

    def publish(self, request: ChangeRequestPublishRequest) -> PublishedChangeRequest:
        """Create or reuse one provider-backed change request."""


class GitLabRemediationChangeRequestPublisher:
    """Publish remediation change requests through GitLab."""

    def __init__(self, gitlab_client: GitLabClient) -> None:
        """Initialize the GitLab remediation publisher."""
        self.gitlab_client = gitlab_client

    def publish(self, request: ChangeRequestPublishRequest) -> PublishedChangeRequest:
        """Create or reuse one GitLab merge request."""
        assignee_id: int | None = None
        if request.assignee_username is not None:
            assignee_id = self.gitlab_client.find_user_id_by_username(request.assignee_username)

        existing_change_request = self.gitlab_client.find_open_merge_request(
            project_id=self.gitlab_client.config.project_id,
            source_branch=request.source_branch,
            target_branch=request.target_branch,
        )
        if existing_change_request is not None:
            if assignee_id is not None:
                self.gitlab_client.update_merge_request_assignee(
                    project_id=self.gitlab_client.config.project_id,
                    merge_request_iid=existing_change_request.iid,
                    assignee_id=assignee_id,
                )
            return PublishedChangeRequest(info=existing_change_request, action="reused")

        created_change_request = self.gitlab_client.create_merge_request(
            project_id=self.gitlab_client.config.project_id,
            source_branch=request.source_branch,
            target_branch=request.target_branch,
            title=request.title,
            description=request.description,
            labels=request.labels,
            assignee_id=assignee_id,
        )
        return PublishedChangeRequest(info=created_change_request, action="created")


def build_remediation_change_request_publisher(
    config: AppConfig,
) -> RemediationChangeRequestPublisher:
    """Build the provider-local remediation change-request publisher for one repo config."""
    if config.platform == "gitlab":
        return GitLabRemediationChangeRequestPublisher(
            GitLabClient(load_gitlab_connection_config())
        )
    if config.platform == "github":
        raise RuntimeError(
            "Remediation change-request publish is not implemented for platform=github."
        )
    raise GitLabClientError(f"Unsupported remediation publish platform: {config.platform}")

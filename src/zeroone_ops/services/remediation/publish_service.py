"""Publish service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import (
    RemediationExecutionTarget,
    remediation_profile_for,
)
from zeroone_ops.models.work_item import PublicationRetryState, WorkItemState
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.remediation.change_request_publisher import (
    ChangeRequestPublishRequest,
    RemediationChangeRequestPublisher,
    build_remediation_change_request_publisher,
)
from zeroone_ops.services.remediation.control_plane import (
    RemediationControlPlane,
    build_remediation_control_plane,
)
from zeroone_ops.services.shared.branch_manager import (
    BranchManager,
    BranchManagerError,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Summarize remote publish and change-request creation."""

    branch_name: str | None = None
    change_request_url: str | None = None
    change_request_action: str | None = None
    error_message: str | None = None


class PublishService:
    """Push branches and create or reuse provider-backed change requests.

    Args:
        config: Loaded application configuration.
        branch_manager: Branch manager implementation.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        branch_manager: BranchManager,
        change_request_publisher: RemediationChangeRequestPublisher | None = None,
        remediation_control_plane: RemediationControlPlane | None = None,
    ) -> None:
        """Initialize the publish service.

        Args:
            config: Loaded application configuration.
            branch_manager: Branch manager implementation.
            change_request_publisher: Optional provider-local publisher override.
            remediation_control_plane: Optional provider-local control-plane override.
        """
        self.config = config
        self.branch_manager = branch_manager
        self.change_request_publisher = change_request_publisher
        self._remediation_control_plane_override = remediation_control_plane
        self._remediation_control_plane: RemediationControlPlane | None = None

    def publish(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        change_request_title: str | None = None,
        change_request_description: str | None = None,
        commit_sha: str | None = None,
    ) -> PublishResult:
        """Push the current branch and create or reuse a change request."""
        if change_request_title is None:
            return PublishResult(error_message="Publish failed: change request title is required.")
        if change_request_description is None:
            return PublishResult(
                error_message="Publish failed: change request description is required."
            )
        control_plane_work_item = None
        pushed_branch: str | None = None
        try:
            labels, assignee_username = self._publication_options()
            target_branch = self.config.require_remediation_target_branch(
                reason="Remediation publish",
            )
            publisher = self.change_request_publisher or build_remediation_change_request_publisher(
                self.config
            )
            control_plane_work_item = self._mark_control_plane_publish_started_best_effort(
                selected_issue=selected_issue,
            )
            pushed_branch = self.branch_manager.push_current_branch()
            published_change_request = publisher.publish(
                ChangeRequestPublishRequest(
                    source_branch=pushed_branch,
                    target_branch=target_branch,
                    title=self.build_change_request_title(
                        selected_issue=selected_issue,
                        proposed_title=change_request_title,
                    ),
                    description=self.build_change_request_description(
                        selected_issue=selected_issue,
                        change_summary=change_request_description,
                    ),
                    labels=labels,
                    assignee_username=assignee_username,
                )
            )
            self._sync_control_plane_change_request_link_best_effort(
                selected_issue=selected_issue,
                published_change_request=published_change_request.info,
                existing_work_item=control_plane_work_item,
            )
        except (BranchManagerError, GitLabClientError, GitHubClientError, RuntimeError) as error:
            self._mark_control_plane_blocked_best_effort(
                selected_issue=selected_issue,
                existing_work_item=control_plane_work_item,
                original_error=error,
                publication_retry=(
                    PublicationRetryState(
                        branch_name=pushed_branch,
                        commit_sha=commit_sha,
                        reason="change_request_publish_failed",
                    )
                    if pushed_branch is not None and commit_sha is not None
                    else None
                ),
            )
            return PublishResult(
                branch_name=pushed_branch,
                error_message=f"Publish failed: {error}",
            )
        return PublishResult(
            branch_name=pushed_branch,
            change_request_url=published_change_request.info.web_url,
            change_request_action=published_change_request.action,
        )

    def build_change_request_title(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        proposed_title: str,
    ) -> str:
        """Build a conventional-commit-style change-request title.

        Args:
            selected_issue: Selected remediation execution target.
            proposed_title: LLM-proposed change-request title.

        Returns:
            A deterministic conventional-commit-style title.
        """
        del proposed_title
        issue_summary = selected_issue.rule_id or selected_issue.source_ref
        file_name = Path(selected_issue.file_path).name
        return f"fix: remediate {issue_summary} in {file_name}"

    def build_change_request_description(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        change_summary: str,
    ) -> str:
        """Build a deterministic change-request description."""
        profile = remediation_profile_for(selected_issue)
        issue_line = str(selected_issue.line) if selected_issue.line is not None else "n/a"
        issue_type = (
            selected_issue.remediation_category
            or selected_issue.issue_type
            or selected_issue.source_type
        )
        return "\n".join(
            [
                "## Summary",
                change_summary,
                "",
                f"## {profile.mr_section_title}",
                f"- Source: `{profile.source_display_name}`",
                f"- Source ID: `{selected_issue.source_type}`",
                f"- {profile.item_reference_label}: `{selected_issue.source_ref}`",
                f"- Rule: `{selected_issue.rule_id or 'unknown'}`",
                f"- Severity: `{selected_issue.severity or 'unknown'}`",
                f"- Type: `{issue_type}`",
                f"- File: `{selected_issue.file_path}`",
                f"- Line: `{issue_line}`",
                f"- Message: {selected_issue.message}",
                "",
                "## Notes",
                profile.diff_note,
            ]
        )

    def _publication_options(self) -> tuple[list[str], str | None]:
        """Return provider-local publish options for the current repository config."""
        if self.config.platform == "gitlab":
            workflow_gitlab_config = self.config.require_gitlab_config(
                reason="Remediation publish",
            )
            return (
                workflow_gitlab_config.labels,
                workflow_gitlab_config.merge_request_assignee_username,
            )
        if self.config.platform == "github":
            workflow_github_config = self.config.github
            if workflow_github_config is None:
                return ([], None)
            return (
                workflow_github_config.labels,
                workflow_github_config.pull_request_assignee_username,
            )
        return ([], None)

    def _remediation_control_plane_instance(self) -> RemediationControlPlane:
        """Return the provider-local remediation control plane, building defaults lazily."""
        if self._remediation_control_plane_override is not None:
            return self._remediation_control_plane_override
        if self._remediation_control_plane is None:
            self._remediation_control_plane = build_remediation_control_plane(self.config)
        return self._remediation_control_plane

    def _mark_control_plane_publish_started_best_effort(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState | None:
        """Project publish-start state without blocking change-request publication."""
        try:
            return self._remediation_control_plane_instance().mark_publish_started(
                selected_issue=selected_issue,
            )
        except (GitHubClientError, RuntimeError):
            LOGGER.warning(
                "Remediation control-plane publish-start sync failed before publish",
                exc_info=True,
            )
            return None

    def _sync_control_plane_change_request_link_best_effort(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Sync the published change request onto control-plane state without altering success."""
        try:
            self._remediation_control_plane_instance().sync_change_request_link(
                selected_issue=selected_issue,
                published_change_request=published_change_request,
                existing_work_item=existing_work_item,
            )
        except (GitHubClientError, RuntimeError):
            LOGGER.warning(
                "Remediation control-plane change-request sync failed after publish",
                extra={"change_request_url": published_change_request.web_url},
                exc_info=True,
            )

    def _mark_control_plane_blocked_best_effort(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        original_error: Exception,
        publication_retry: PublicationRetryState | None,
    ) -> None:
        """Mark control-plane state as blocked without overwriting the original publish error."""
        try:
            self._remediation_control_plane_instance().mark_publish_blocked(
                selected_issue=selected_issue,
                existing_work_item=existing_work_item,
                publication_retry=publication_retry,
            )
        except (GitHubClientError, RuntimeError):
            LOGGER.warning(
                "Remediation control-plane blocked-state cleanup failed after publish failure",
                extra={"original_error": str(original_error)},
                exc_info=True,
            )

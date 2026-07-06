"""Publish service.

This module owns branch push and provider-backed change-request publication.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import (
    RemediationExecutionTarget,
    remediation_profile_for,
)
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.remediation.change_request_publisher import (
    ChangeRequestPublishRequest,
    RemediationChangeRequestPublisher,
    build_remediation_change_request_publisher,
)
from zeroone_ops.services.shared.branch_manager import (
    BranchManager,
    BranchManagerError,
)


@dataclass
class PublishResult:
    """Summarize remote publish and change-request creation."""

    branch_name: str | None = None
    change_request_url: str | None = None
    change_request_action: str | None = None
    error_message: str | None = None

    @property
    def mr_url(self) -> str | None:
        """Return the legacy merge-request URL alias."""
        return self.change_request_url

    @property
    def mr_action(self) -> str | None:
        """Return the legacy merge-request action alias."""
        return self.change_request_action


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
    ) -> None:
        """Initialize the publish service.

        Args:
            config: Loaded application configuration.
            branch_manager: Branch manager implementation.
            change_request_publisher: Optional provider-local publisher override.
        """
        self.config = config
        self.branch_manager = branch_manager
        self.change_request_publisher = change_request_publisher

    def publish(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        mr_title: str,
        mr_description: str,
    ) -> PublishResult:
        """Push the current branch and create or reuse a change request."""
        try:
            labels, assignee_username = self._publication_options()
            target_branch = self.config.require_remediation_target_branch(
                reason="Remediation publish",
            )
            pushed_branch = self.branch_manager.push_current_branch()
            publisher = self.change_request_publisher or build_remediation_change_request_publisher(
                self.config
            )
            published_change_request = publisher.publish(
                ChangeRequestPublishRequest(
                    source_branch=pushed_branch,
                    target_branch=target_branch,
                    title=self.build_change_request_title(
                        selected_issue=selected_issue,
                        proposed_title=mr_title,
                    ),
                    description=self.build_change_request_description(
                        selected_issue=selected_issue,
                        change_summary=mr_description,
                    ),
                    labels=labels,
                    assignee_username=assignee_username,
                )
            )
        except (BranchManagerError, GitLabClientError, RuntimeError) as error:
            return PublishResult(error_message=f"Publish failed: {error}")
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
        return "\n".join(
            [
                "## Summary",
                change_summary,
                "",
                f"## {profile.mr_section_title}",
                f"- Source: `{profile.source_display_name}`",
                f"- {profile.item_reference_label}: `{selected_issue.source_ref}`",
                f"- Rule: `{selected_issue.rule_id or 'unknown'}`",
                f"- Severity: `{selected_issue.severity or 'unknown'}`",
                f"- Type: `{selected_issue.issue_type or selected_issue.source_type}`",
                f"- File: `{selected_issue.file_path}`",
                f"- Line: `{issue_line}`",
                f"- Message: {selected_issue.message}",
                "",
                "## Notes",
                profile.diff_note,
            ]
        )

    def build_mr_title(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        proposed_title: str,
    ) -> str:
        """Return the legacy merge-request title alias."""
        return self.build_change_request_title(
            selected_issue=selected_issue,
            proposed_title=proposed_title,
        )

    def build_mr_description(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        change_summary: str,
    ) -> str:
        """Return the legacy merge-request description alias."""
        return self.build_change_request_description(
            selected_issue=selected_issue,
            change_summary=change_summary,
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
        return ([], None)

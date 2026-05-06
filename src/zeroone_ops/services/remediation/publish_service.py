"""Publish service.

This module owns branch push and GitLab merge request publication.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.analysis import ValidationResult
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import (
    RemediationExecutionTarget,
    remediation_profile_for,
)
from zeroone_ops.providers.gitlab_client import GitLabClient, GitLabClientError
from zeroone_ops.services.shared.branch_manager import (
    BranchManager,
    BranchManagerError,
)
from zeroone_ops.services.shared.mr_service import MergeRequestService
from zeroone_ops.settings import load_gitlab_connection_config


@dataclass
class PublishResult:
    """Summarize remote publish and merge request creation."""

    branch_name: str | None = None
    mr_url: str | None = None
    mr_action: str | None = None
    error_message: str | None = None


class PublishService:
    """Push branches and create or reuse GitLab merge requests.

    Args:
        config: Loaded application configuration.
        branch_manager: Branch manager implementation.
    """

    def __init__(self, *, config: AppConfig, branch_manager: BranchManager) -> None:
        """Initialize the publish service.

        Args:
            config: Loaded application configuration.
            branch_manager: Branch manager implementation.
        """
        self.config = config
        self.branch_manager = branch_manager

    def publish(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        validation_result: ValidationResult | None,
        branch_name: str,
        mr_title: str,
        mr_description: str,
    ) -> PublishResult:
        """Push the current branch and create or reuse a merge request."""
        try:
            gitlab_config = load_gitlab_connection_config()
            pushed_branch = self.branch_manager.push_current_branch()
            merge_request_service = MergeRequestService(GitLabClient(gitlab_config))
            existing_mr = merge_request_service.find_open(
                project_id=gitlab_config.project_id,
                source_branch=pushed_branch,
                target_branch=self.config.gitlab.target_branch,
            )
            if existing_mr is not None:
                return PublishResult(
                    branch_name=pushed_branch,
                    mr_url=existing_mr.web_url,
                    mr_action="reused",
                )
            created_mr = merge_request_service.create(
                project_id=gitlab_config.project_id,
                source_branch=branch_name,
                target_branch=self.config.gitlab.target_branch,
                title=self.build_mr_title(
                    selected_issue=selected_issue,
                    proposed_title=mr_title,
                ),
                description=self.build_mr_description(
                    selected_issue=selected_issue,
                    validation_result=validation_result,
                    change_summary=mr_description,
                ),
                labels=self.config.gitlab.labels,
            )
        except (BranchManagerError, GitLabClientError, RuntimeError) as error:
            return PublishResult(error_message=f"Publish failed: {error}")
        return PublishResult(
            branch_name=branch_name,
            mr_url=created_mr.web_url,
            mr_action="created",
        )

    def build_mr_title(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        proposed_title: str,
    ) -> str:
        """Build a conventional-commit-style merge request title.

        Args:
            selected_issue: Selected remediation execution target.
            proposed_title: LLM-proposed merge request title.

        Returns:
            A deterministic conventional-commit-style title.
        """
        del proposed_title
        issue_summary = selected_issue.rule_id or selected_issue.source_ref
        file_name = Path(selected_issue.file_path).name
        return f"fix: remediate {issue_summary} in {file_name}"

    def build_mr_description(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        validation_result: ValidationResult | None,
        change_summary: str,
    ) -> str:
        """Build a deterministic merge request description."""
        profile = remediation_profile_for(selected_issue)
        issue_line = str(selected_issue.line) if selected_issue.line is not None else "n/a"
        validation_summary = (
            validation_result.summary
            if validation_result is not None
            else "Validation did not run."
        )
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
                "## Validation",
                f"- {validation_summary}",
                "",
                "## Notes",
                profile.diff_note,
            ]
        )

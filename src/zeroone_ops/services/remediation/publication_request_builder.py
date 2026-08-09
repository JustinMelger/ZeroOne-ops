"""Build deterministic provider-neutral remediation publication requests."""

from __future__ import annotations

from pathlib import Path

from zeroone_ops.models.analysis import ValidationComparison
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget, remediation_profile_for
from zeroone_ops.services.remediation.change_request_publisher import ChangeRequestPublishRequest


class RemediationPublicationRequestBuilder:
    """Build one change-request publication request from a remediation target."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the builder with repository publication configuration."""
        self.config = config

    def build(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        source_branch: str,
        change_summary: str,
        validation_comparison: ValidationComparison | None = None,
    ) -> ChangeRequestPublishRequest:
        """Build the complete provider-neutral request for one source branch."""
        labels, assignee_username = self._publication_options()
        return ChangeRequestPublishRequest(
            source_branch=source_branch,
            target_branch=self.config.require_remediation_target_branch(
                reason="Remediation publish",
            ),
            title=self.build_title(selected_issue=selected_issue),
            description=self.build_description(
                selected_issue=selected_issue,
                change_summary=change_summary,
                validation_comparison=validation_comparison,
            ),
            labels=labels,
            assignee_username=assignee_username,
        )

    @staticmethod
    def build_title(*, selected_issue: RemediationExecutionTarget) -> str:
        """Build a deterministic conventional-commit-style change-request title."""
        issue_summary = selected_issue.rule_id or selected_issue.source_ref
        file_name = Path(selected_issue.file_path).name
        return f"fix: remediate {issue_summary} in {file_name}"

    @staticmethod
    def build_description(
        *,
        selected_issue: RemediationExecutionTarget,
        change_summary: str,
        validation_comparison: ValidationComparison | None = None,
    ) -> str:
        """Build a deterministic change-request description."""
        profile = remediation_profile_for(selected_issue)
        issue_line = str(selected_issue.line) if selected_issue.line is not None else "n/a"
        issue_type = (
            selected_issue.remediation_category
            or selected_issue.issue_type
            or selected_issue.source_type
        )
        item_reference = (
            f"- Tracking work item: {selected_issue.work_item_url}"
            if selected_issue.work_item_url is not None
            else f"- {profile.item_reference_label}: `{selected_issue.source_ref}`"
        )
        lines = [
            "## Summary",
            change_summary,
            "",
            f"## {profile.mr_section_title}",
            f"- Source: `{profile.source_display_name}`",
            f"- Source ID: `{selected_issue.source_type}`",
            item_reference,
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
        if validation_comparison is not None:
            commands = [result.command for result in validation_comparison.post_edit.results]
            status = (
                "Validation passed"
                if validation_comparison.outcome == "passed"
                else "Validation baseline preserved"
            )
            lines.extend(
                [
                    "",
                    "## Validation",
                    f"- Status: {status}",
                    "- Commands: " + ", ".join(f"`{command}`" for command in commands),
                ]
            )
        return "\n".join(lines)

    def _publication_options(self) -> tuple[list[str], str | None]:
        """Return provider-local publish options for the configured repository."""
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

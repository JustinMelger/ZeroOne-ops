"""Terminal approval service.

This module handles the local operator approval prompt used before publishing
changes.
"""

from __future__ import annotations

from ai_sonar_bot.models.analysis import ValidationResult
from ai_sonar_bot.models.sonar import SonarIssue


class ApprovalService:
    """Request human approval before publishing changes."""

    def request(
        self,
        issue: SonarIssue,
        changed_files: list[str],
        validation: ValidationResult,
        commit_message: str,
        mr_title: str,
    ) -> bool:
        """Prompt the operator for approval.

        Args:
            issue: SonarQube issue being addressed.
            changed_files: Repository-relative files changed by the proposal.
            validation: Validation result for the proposed change.
            commit_message: Proposed commit message.
            mr_title: Proposed merge request title.

        Returns:
            ``True`` if the operator approves publishing, otherwise ``False``.
        """
        print(f"Issue: {issue.key} - {issue.message}")
        print(f"Changed files: {', '.join(changed_files) if changed_files else 'none'}")
        print(f"Validation: {validation.summary}")
        print(f"Commit message: {commit_message}")
        print(f"Merge request title: {mr_title}")
        response = input("Approve change? [y/N]: ").strip().lower()
        return response in {"y", "yes"}

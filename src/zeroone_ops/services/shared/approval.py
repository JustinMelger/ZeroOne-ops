"""Terminal approval service.

This module handles the local operator approval prompt used before publishing
changes.
"""

from __future__ import annotations

from zeroone_ops.models.analysis import ValidationResult
from zeroone_ops.models.remediation import RemediationExecutionTarget


class ApprovalService:
    """Request human approval before publishing changes."""

    def request(
        self,
        issue: RemediationExecutionTarget,
        changed_files: list[str],
        validation: ValidationResult,
        commit_message: str,
        change_request_title: str,
    ) -> bool:
        """Prompt the operator for approval.

        Args:
            issue: Remediation target being addressed.
            changed_files: Repository-relative files changed by the proposal.
            validation: Validation result for the proposed change.
            commit_message: Proposed commit message.
            change_request_title: Proposed change-request title.

        Returns:
            ``True`` if the operator approves publishing, otherwise ``False``.
        """
        print(f"Issue: {issue.source_ref} - {issue.message}")
        print(f"Changed files: {', '.join(changed_files) if changed_files else 'none'}")
        print(f"Validation: {validation.summary}")
        print(f"Commit message: {commit_message}")
        print(f"Change request title: {change_request_title}")
        response = input("Approve change? [y/N]: ").strip().lower()
        return response in {"y", "yes"}

"""Issue eligibility policy.

This module centralizes the v1 policy that decides whether a SonarQube issue is
safe and in scope for automated handling.
"""

from __future__ import annotations

from collections.abc import Sequence

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.models.state import AppState

DEFAULT_V1_SUPPORTED_TYPES = frozenset(
    {
        "BUG",
        "CODE_SMELL",
    }
)


class IssueEligibilityPolicy:
    """Evaluate whether a SonarQube issue is eligible for automation.

    Args:
        config: Loaded application configuration.
    """

    def __init__(self, config: AppConfig) -> None:
        """Initialize the policy.

        Args:
            config: Loaded application configuration.
        """
        self.config = config

    def skip_reason(self, issue: SonarIssue, state: AppState) -> str | None:
        """Return the stable reason an issue should be skipped, if any.

        Args:
            issue: Candidate SonarQube issue.
            state: Current persisted application state.

        Returns:
            A stable skip-reason code, or ``None`` if the issue is eligible.
        """
        if not issue.matches_supported_severities(self.config.remediation.supported_severities):
            return "unsupported_severity"
        if issue.type not in DEFAULT_V1_SUPPORTED_TYPES:
            return "unsupported_type"
        if _is_risky_rename_issue(issue):
            return "risky_rename"
        issue_state = state.issues.get(issue.key)
        if issue_state and issue_state.status == "mr_created":
            return "existing_merge_request"
        return None


def describe_skip_reasons(reason_counts: dict[str, int]) -> str:
    """Render skip-reason counts into a short human-readable sentence.

    Args:
        reason_counts: Mapping from skip-reason codes to occurrence counts.

    Returns:
        A compact sentence fragment suitable for run summaries.
    """
    ordered_reasons: Sequence[tuple[str, str]] = (
        ("missing_local_file", "without a matching local file"),
        ("in_progress_state", "already in progress locally"),
        ("open_merge_request", "with an open merge request"),
        ("risky_rename", "excluded as rename-style issues"),
        ("unsupported_severity", "with unsupported severity"),
        ("unsupported_type", "with unsupported type"),
        ("existing_merge_request", "already marked as merge-request created"),
    )
    parts = [
        f"{reason_counts[reason]} {label}"
        for reason, label in ordered_reasons
        if reason_counts.get(reason, 0) > 0
    ]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _is_risky_rename_issue(issue: SonarIssue) -> bool:
    """Return whether an issue should be rejected as a risky rename for v1.

    SonarQube naming issues often ask for renaming a variable, method, class,
    parameter, or similar symbol. The current bot does not perform symbol-aware
    reference analysis, so these issues are excluded from the v1 automation
    scope to avoid local renames that break surrounding code.

    Args:
        issue: Candidate SonarQube issue.

    Returns:
        ``True`` when the issue should be skipped as a rename-style issue.
    """
    message = issue.message.lower()
    return "rename this" in message

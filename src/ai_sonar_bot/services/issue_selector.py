"""Issue selection rules.

This module filters and prioritizes SonarQube issues for automated handling.
"""

from __future__ import annotations

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import AppState


class IssueSelector:
    """Select one eligible SonarQube issue for a run.

    Args:
        config: Loaded application configuration.
    """

    def __init__(self, config: AppConfig) -> None:
        """Initialize the issue selector.

        Args:
            config: Loaded application configuration.
        """
        self.config = config

    def select(self, issues: list[SonarIssue], state: AppState) -> SonarIssue | None:
        """Select the next issue to process.

        Args:
            issues: Candidate SonarQube issues.
            state: Current persisted application state.

        Returns:
            The first eligible issue, or ``None`` if no issue qualifies.
        """
        for issue in issues:
            if not issue.matches_supported_severities(self.config.supported_severities):
                continue
            if issue.type not in self.config.supported_issue_types:
                continue
            if self.config.supported_rules and issue.rule not in self.config.supported_rules:
                continue
            issue_state = state.issues.get(issue.key)
            if issue_state and issue_state.status == "mr_created":
                continue
            return issue
        return None

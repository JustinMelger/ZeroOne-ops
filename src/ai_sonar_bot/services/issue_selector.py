"""Issue selection rules."""

from __future__ import annotations

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import AppState
from ai_sonar_bot.services.issue_eligibility import IssueEligibilityPolicy


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
        self.policy = IssueEligibilityPolicy(config)

    def select(self, issues: list[SonarIssue], state: AppState) -> SonarIssue | None:
        """Select the next issue to process.

        Args:
            issues: Candidate SonarQube issues.
            state: Current persisted application state.

        Returns:
            The first eligible issue, or ``None`` if no issue qualifies.
        """
        for issue in issues:
            if self.skip_reason(issue, state) is not None:
                continue
            return issue
        return None

    def skip_reason(self, issue: SonarIssue, state: AppState) -> str | None:
        """Return the policy reason an issue should be skipped, if any.

        Args:
            issue: Candidate SonarQube issue.
            state: Current persisted application state.

        Returns:
            A stable skip-reason code, or ``None`` if the issue is eligible.
        """
        return self.policy.skip_reason(issue, state)

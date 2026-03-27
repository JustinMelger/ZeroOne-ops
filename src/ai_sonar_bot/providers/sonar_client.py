"""SonarQube API client.

This module will provide SonarQube REST integration for issue retrieval.
"""

from __future__ import annotations

from ai_sonar_bot.models.sonar import SonarIssue


class SonarClient:
    """Placeholder SonarQube client for the initial scaffold."""

    def search_open_issues(self) -> list[SonarIssue]:
        """Fetch open issues from SonarQube.

        Returns:
            Open SonarQube issues for the configured project.
        """
        raise NotImplementedError("SonarQube integration is not implemented yet.")

    def get_issue(self, issue_key: str) -> SonarIssue:
        """Fetch a specific SonarQube issue.

        Args:
            issue_key: SonarQube issue key.

        Returns:
            The requested SonarQube issue.
        """
        raise NotImplementedError("SonarQube integration is not implemented yet.")

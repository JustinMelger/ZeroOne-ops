"""LLM client.

This module will provide structured issue analysis and patch generation through
an LLM provider.
"""

from __future__ import annotations

from ai_sonar_bot.models.analysis import IssueAnalysis, PatchProposal
from ai_sonar_bot.models.sonar import SonarIssue


class LLMClient:
    """Placeholder LLM client for the initial scaffold."""

    def analyze_issue(self, issue: SonarIssue, context: str) -> IssueAnalysis:
        """Analyze a SonarQube issue.

        Args:
            issue: Issue to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis.
        """
        raise NotImplementedError("LLM integration is not implemented yet.")

    def generate_patch(self, issue: SonarIssue, context: str) -> PatchProposal:
        """Generate a patch proposal for a SonarQube issue.

        Args:
            issue: Issue to fix.
            context: Repository context for the issue.

        Returns:
            Structured patch proposal.
        """
        raise NotImplementedError("LLM integration is not implemented yet.")

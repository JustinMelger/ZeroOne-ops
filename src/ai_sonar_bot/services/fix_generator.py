"""Fix generation service.

This module coordinates issue analysis and patch generation through the LLM
provider.
"""

from __future__ import annotations

from ai_sonar_bot.models.analysis import IssueAnalysis, IssueContext, PatchProposal
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.providers.llm_client import LLMClient


class FixGenerator:
    """Delegate analysis and patch generation to the LLM client.

    Args:
        llm_client: LLM provider implementation.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize the fix generator.

        Args:
            llm_client: LLM provider implementation.
        """
        self.llm_client = llm_client

    def analyze(self, issue: SonarIssue, context: IssueContext) -> IssueAnalysis:
        """Analyze an issue.

        Args:
            issue: SonarQube issue to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis.
        """
        return self.llm_client.analyze_issue(issue, context)

    def generate(self, issue: SonarIssue, context: IssueContext) -> PatchProposal:
        """Generate a patch proposal.

        Args:
            issue: SonarQube issue to fix.
            context: Repository context for the issue.

        Returns:
            Structured patch proposal.
        """
        return self.llm_client.generate_patch(issue, context)

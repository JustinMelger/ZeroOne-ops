"""Fix generation service.

This module coordinates issue analysis and patch generation through the LLM
provider.
"""

from __future__ import annotations

from zeroone_ops.models.analysis import IssueAnalysis, IssueContext, StructuredEditProposal
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.providers.llm_client import LLMClient


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

    def analyze(self, target: RemediationExecutionTarget, context: IssueContext) -> IssueAnalysis:
        """Analyze an issue.

        Args:
            target: Remediation target to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis.
        """
        return self.llm_client.analyze_issue(target, context)

    def generate_structured_edit(
        self,
        target: RemediationExecutionTarget,
        context: IssueContext,
    ) -> StructuredEditProposal:
        """Generate a structured edit proposal.

        Args:
            target: Remediation target to fix.
            context: Repository context for the issue.

        Returns:
            Structured edit proposal for bot-rendered diffs.
        """
        return self.llm_client.generate_structured_edit(target, context)

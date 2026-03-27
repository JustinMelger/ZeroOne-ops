"""LLM client.

This module will provide structured issue analysis and patch generation through
an LLM provider.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_sonar_bot.models.analysis import IssueAnalysis, IssueContext, PatchProposal
from ai_sonar_bot.models.sonar import SonarIssue


class LLMClientError(RuntimeError):
    """Raised when LLM analysis or patch generation fails."""


class LLMClient:
    """Placeholder LLM client for the initial scaffold."""

    def analyze_issue(self, issue: SonarIssue, context: IssueContext) -> IssueAnalysis:
        """Analyze a SonarQube issue.

        Args:
            issue: Issue to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis.
        """
        raise NotImplementedError("LLM integration is not implemented yet.")

    def generate_patch(self, issue: SonarIssue, context: IssueContext) -> PatchProposal:
        """Generate a patch proposal for a SonarQube issue.

        Args:
            issue: Issue to fix.
            context: Repository context for the issue.

        Returns:
            Structured patch proposal.
        """
        raise NotImplementedError("LLM integration is not implemented yet.")


class FixtureLLMClient(LLMClient):
    """LLM client backed by a local analysis fixture file.

    Args:
        analysis_fixture_path: Path to a local JSON analysis fixture.
    """

    def __init__(self, analysis_fixture_path: Path) -> None:
        """Initialize the fixture-backed LLM client.

        Args:
            analysis_fixture_path: Path to a local JSON analysis fixture.
        """
        self.analysis_fixture_path = analysis_fixture_path

    def analyze_issue(self, issue: SonarIssue, context: IssueContext) -> IssueAnalysis:
        """Load a fixture-based issue analysis result.

        Args:
            issue: Issue to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis from the fixture.
        """
        del issue, context
        return load_analysis_fixture(self.analysis_fixture_path)


def load_analysis_fixture(path: Path) -> IssueAnalysis:
    """Load an issue analysis result from a JSON fixture.

    Args:
        path: Path to the analysis fixture.

    Returns:
        Structured issue analysis.

    Raises:
        LLMClientError: If the fixture file is missing or invalid.
    """
    if not path.exists():
        raise LLMClientError(f"LLM analysis fixture file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LLMClientError(f"LLM analysis fixture file is invalid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise LLMClientError("Unexpected LLM analysis fixture payload.")

    try:
        return IssueAnalysis.model_validate(payload)
    except Exception as error:
        raise LLMClientError("Invalid LLM analysis fixture structure.") from error

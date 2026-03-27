"""Code context builder.

This module reads repository files and prepares contextual source text for the
LLM prompt.
"""

from __future__ import annotations

from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue


class ContextBuilder:
    """Build prompt context for a SonarQube issue.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
    """

    def __init__(self, repo_root: Path, config: AppConfig) -> None:
        """Initialize the context builder.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
        """
        self.repo_root = repo_root
        self.config = config

    def build(self, issue: SonarIssue) -> str:
        """Build code context for an issue.

        Args:
            issue: SonarQube issue to analyze.

        Returns:
            Source content for the issue file, or an empty string if the file is
            missing.
        """
        target = self.repo_root / issue.file_path
        if not target.exists():
            return ""
        return target.read_text(encoding="utf-8")

"""Provider-neutral remediation context builder."""

from __future__ import annotations

from pathlib import Path

from ai_sonar_bot.models.analysis import IssueContext
from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.remediation import RemediationWorkItem
from ai_sonar_bot.services.context_builder import build_issue_context


class RemediationContextBuilder:
    """Build repository context for a normalized remediation work item."""

    def __init__(self, repo_root: Path, config: AppConfig) -> None:
        """Initialize the remediation context builder."""
        self.repo_root = repo_root
        self.config = config

    def build(self, work_item: RemediationWorkItem) -> IssueContext | None:
        """Build source context for one remediation work item."""
        return build_issue_context(
            repo_root=self.repo_root,
            config=self.config,
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            issue_line=work_item.line,
        )

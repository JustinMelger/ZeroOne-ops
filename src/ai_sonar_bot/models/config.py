"""Configuration models.

This module defines the typed configuration objects loaded from JSON and
environment overrides.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class AnalysisConfig(BaseModel):
    """Configure source context collection for analysis.

    Attributes:
        context_lines_before: Lines of context before the issue line.
        context_lines_after: Lines of context after the issue line.
        max_file_bytes: Maximum file size to include in prompts.
    """

    context_lines_before: int = 40
    context_lines_after: int = 40
    max_file_bytes: int = 200_000


class ApprovalConfig(BaseModel):
    """Configure human approval behavior.

    Attributes:
        required: Whether approval is required before publishing.
    """

    required: bool = True


class GitLabConfig(BaseModel):
    """Configure GitLab merge request behavior.

    Attributes:
        target_branch: Merge request target branch.
        labels: Labels to attach to created merge requests.
    """

    target_branch: str
    labels: list[str] = Field(default_factory=list)


class SonarQubeConnectionConfig(BaseModel):
    """Configure SonarQube API connectivity.

    Attributes:
        url: SonarQube base URL.
        token: SonarQube API token.
        project_key: SonarQube project key.
        page_size: Number of issues to request per page.
    """

    url: str
    token: str
    project_key: str
    page_size: int = 100


class StateConfig(BaseModel):
    """Configure local state persistence.

    Attributes:
        path: Path to the local JSON state file.
    """

    path: Path = Path(".ai-sonar-bot-state.json")


class AppConfig(BaseModel):
    """Represent validated runtime configuration.

    Attributes:
        base_branch: Repository base branch.
        branch_prefix: Prefix for generated branches.
        dry_run: Whether dry-run mode is enabled by default.
        mock_sonar_issues_path: Optional path to a local SonarQube issue fixture.
        max_retry_count: Maximum retry attempts after validation failure.
        supported_severities: Allowed SonarQube severities.
        supported_issue_types: Allowed SonarQube issue types.
        supported_rules: Optional allow-list of SonarQube rules.
        validation_commands: Commands run after a generated patch is applied.
        analysis: Analysis-related settings.
        approval: Approval-related settings.
        gitlab: GitLab merge request settings.
        state: State persistence settings.
    """

    base_branch: str
    branch_prefix: str = "ai-sonar"
    dry_run: bool = False
    mock_sonar_issues_path: Path | None = None
    max_retry_count: int = 1
    supported_severities: list[str] = Field(default_factory=list)
    supported_issue_types: list[str] = Field(default_factory=list)
    supported_rules: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    gitlab: GitLabConfig
    state: StateConfig = Field(default_factory=StateConfig)

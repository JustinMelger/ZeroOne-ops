"""Configuration models.

This module defines the typed configuration objects loaded from JSON and
environment overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

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


class ReviewConfig(BaseModel):
    """Configure pull-request review behavior."""

    max_changed_files: int = 10
    max_context_lines_before: int = 30
    max_context_lines_after: int = 30
    publish_no_findings_note: bool = True
    supported_paths: list[str] = Field(default_factory=list)
    skip_draft_merge_requests: bool = True


class GitLabConfig(BaseModel):
    """Configure GitLab merge request behavior.

    Attributes:
        target_branch: Merge request target branch.
        labels: Labels to attach to created merge requests.
    """

    target_branch: str
    labels: list[str] = Field(default_factory=list)


class GitLabConnectionConfig(BaseModel):
    """Configure GitLab API connectivity.

    Attributes:
        url: GitLab base URL.
        token: GitLab API token.
        project_id: GitLab project identifier.
    """

    url: str
    token: str
    project_id: str


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


class OpenAIConnectionConfig(BaseModel):
    """Configure OpenAI API connectivity.

    Attributes:
        api_key: OpenAI API key.
        model: OpenAI model identifier.
        base_url: Optional override for the API base URL.
    """

    api_key: str
    model: str
    base_url: str | None = None


class StateConfig(BaseModel):
    """Configure local state persistence.

    Attributes:
        path: Path to the local JSON state file.
    """

    path: Path = Path(".ai-sonar-bot-state.json")


class AppConfig(BaseModel):
    """Represent validated runtime configuration.

    Attributes:
        execution_mode: Whether the bot is running locally or in CI.
        base_branch: Repository base branch.
        branch_prefix: Prefix for generated branches.
        dry_run: Whether dry-run mode is enabled by default.
        apply_patch_in_dry_run: Whether dry-run may apply proposed patches locally.
        openai_solution_output_path: Path where OpenAI solutions should be written.
        write_solution_artifacts_in_ci: Whether CI mode should write solution artifact files.
        mock_sonar_issues_path: Optional path to a local SonarQube issue fixture.
        mock_llm_analysis_path: Optional path to a local LLM analysis fixture.
        mock_llm_edit_path: Optional path to a local LLM structured edit fixture.
        max_retry_count: Maximum retry attempts after validation failure.
        supported_severities: Allowed SonarQube severities.
        supported_issue_types: Allowed SonarQube issue types.
        supported_rules: Optional allow-list of SonarQube rules.
        validation_commands: Commands run after a generated patch is applied.
        analysis: Analysis-related settings.
        approval: Approval-related settings.
        review: Review-related settings.
        gitlab: GitLab merge request settings.
        state: State persistence settings.
    """

    execution_mode: Literal["local", "ci"] = "ci"
    base_branch: str
    branch_prefix: str = "ai-sonar"
    dry_run: bool = False
    apply_patch_in_dry_run: bool = False
    openai_solution_output_path: Path = Path("artifacts/openai-solution.json")
    write_solution_artifacts_in_ci: bool = False
    mock_sonar_issues_path: Path | None = None
    mock_llm_analysis_path: Path | None = None
    mock_llm_edit_path: Path | None = None
    max_retry_count: int = 1
    supported_severities: list[str] = Field(default_factory=list)
    supported_issue_types: list[str] = Field(default_factory=list)
    supported_rules: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    gitlab: GitLabConfig
    state: StateConfig = Field(default_factory=StateConfig)

    def requires_local_approval(self) -> bool:
        """Return whether this run should block for terminal approval.

        Returns:
            ``True`` when the bot is running locally and pre-publish approval is
            configured as required.
        """
        return self.execution_mode == "local" and self.approval.required

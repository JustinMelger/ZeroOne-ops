"""Configuration models.

This module defines the typed configuration objects loaded from JSON and
environment overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


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
    enable_function_context: bool = True
    max_function_context_lines: int = 200
    enable_helper_following: bool = True
    log_helper_following: bool = False
    helper_follow_depth: int = 1
    max_followed_helpers_per_function: int = 3
    max_followed_helper_lines: int = 120
    max_followed_helper_lines_per_review: int = 240
    max_findings_per_review: int = 3
    max_prior_review_passes: int = 2
    max_review_feedback_retries: int = 1
    inline_comments_enabled: bool = False
    supported_paths: list[str] = Field(default_factory=list)
    ignored_paths: list[str] = Field(default_factory=list)
    skip_draft_merge_requests: bool = True


class GitLabConfig(BaseModel):
    """Configure GitLab merge request behavior.

    Attributes:
        labels: Labels to attach to created merge requests.
        merge_request_assignee_username: Optional GitLab username to assign
            created remediation merge requests to.
    """

    target_branch: str | None = None
    labels: list[str] = Field(default_factory=list)
    merge_request_assignee_username: str | None = None


class GitHubConfig(BaseModel):
    """Configure GitHub pull request behavior.

    Attributes:
        labels: Labels to attach to created pull requests.
        pull_request_assignee_username: Optional GitHub username to assign
            created remediation pull requests to.
    """

    labels: list[str] = Field(default_factory=list)
    pull_request_assignee_username: str | None = None


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


class GitHubConnectionConfig(BaseModel):
    """Configure GitHub API connectivity for pull-request review.

    Attributes:
        api_url: GitHub API base URL.
        server_url: GitHub server URL for building web links when needed.
        token: GitHub API token.
        repository: Repository full name in ``owner/name`` form.
    """

    api_url: str
    server_url: str
    token: str
    repository: str


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
        mlflow_enabled: Whether MLflow OpenAI autologging should be enabled.
        mlflow_tracking_uri: Optional MLflow tracking URI.
        mlflow_experiment_name: Optional MLflow experiment name.
    """

    api_key: str
    model: str
    base_url: str | None = None
    mlflow_enabled: bool = False
    mlflow_tracking_uri: str | None = None
    mlflow_experiment_name: str | None = None


class StateConfig(BaseModel):
    """Configure local state persistence.

    Attributes:
        path: Path to the local JSON state file.
    """

    path: Path = Path(".zeroone-ops-state.json")


class RemediationConfig(BaseModel):
    """Configure remediation workflow behavior."""

    target_branch: str | None = None
    bootstrap_severities: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("bootstrap_severities", "supported_severities"),
    )
    max_retry_count: int = 1
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)

    @property
    def supported_severities(self) -> list[str]:
        """Return the legacy severity seed name for compatibility."""
        return self.bootstrap_severities


class SonarQubeConfig(BaseModel):
    """Configure SonarQube producer behavior."""

    mock_issues_path: Path | None = None


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
        mock_llm_analysis_path: Optional path to a local LLM analysis fixture.
        mock_llm_edit_path: Optional path to a local LLM structured edit fixture.
        validation_commands: Commands run after a generated patch is applied.
        approval: Approval-related settings.
        review: Review-related settings.
        remediation: Remediation-related settings.
        sonarqube: SonarQube producer settings.
    gitlab: GitLab merge request settings when GitLab workflows are used.
    github: GitHub pull request settings when GitHub workflows are used.
        state: State persistence settings.
    """

    execution_mode: Literal["local", "ci"] = "ci"
    platform: Literal["gitlab", "github"] = "gitlab"
    base_branch: str
    branch_prefix: str = "zeroone-ops"
    dry_run: bool = False
    apply_patch_in_dry_run: bool = False
    openai_solution_output_path: Path = Path("artifacts/openai-solution.json")
    write_solution_artifacts_in_ci: bool = False
    mock_llm_analysis_path: Path | None = None
    mock_llm_edit_path: Path | None = None
    validation_commands: list[str] = Field(default_factory=list)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    remediation: RemediationConfig = Field(default_factory=RemediationConfig)
    sonarqube: SonarQubeConfig = Field(default_factory=SonarQubeConfig)
    gitlab: GitLabConfig | None = None
    github: GitHubConfig | None = None
    state: StateConfig = Field(default_factory=StateConfig)

    _REMOVED_FLAT_CONFIG_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "supported_severities",
            "bootstrap_severities",
            "max_retry_count",
            "analysis",
            "mock_sonar_issues_path",
        }
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, value: object) -> object:
        """Lift legacy flat config keys into nested workflow/source blocks."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        removed_keys = sorted(key for key in cls._REMOVED_FLAT_CONFIG_KEYS if key in data)
        if removed_keys:
            keys = ", ".join(removed_keys)
            raise ValueError(
                "Removed flat config keys are no longer supported: "
                f"{keys}. Use nested remediation/sonarqube config instead."
            )

        remediation = dict(data.get("remediation", {}))
        raw_gitlab = data.get("gitlab")
        gitlab = raw_gitlab if isinstance(raw_gitlab, dict) else {}
        if (
            "target_branch" not in remediation
            and isinstance(gitlab.get("target_branch"), str)
            and gitlab["target_branch"]
        ):
            remediation["target_branch"] = gitlab["target_branch"]
        if remediation:
            data["remediation"] = remediation

        sonarqube = dict(data.get("sonarqube", {}))
        if sonarqube:
            data["sonarqube"] = sonarqube

        review = dict(data.get("review", {}))
        if "platform" not in data and "platform" in review:
            data["platform"] = review["platform"]

        return data

    @model_validator(mode="after")
    def _validate_provider_requirements(self) -> AppConfig:
        """Validate provider-specific configuration requirements."""
        if self.platform == "gitlab" and self.gitlab is None:
            raise ValueError("platform=gitlab requires a top-level gitlab configuration block.")
        if self.remediation.target_branch is None and self.gitlab is not None:
            self.remediation.target_branch = self.gitlab.target_branch
        if self.platform == "gitlab" and self.remediation.target_branch is None:
            raise ValueError("platform=gitlab requires remediation.target_branch to be configured.")
        return self

    def require_gitlab_config(self, *, reason: str) -> GitLabConfig:
        """Return GitLab workflow settings or fail with a scoped message."""
        if self.gitlab is None:
            raise ValueError(f"{reason} requires a top-level gitlab configuration block.")
        return self.gitlab

    def requires_local_approval(self) -> bool:
        """Return whether this run should block for terminal approval.

        Returns:
            ``True`` when the bot is running locally and pre-publish approval is
            configured as required.
        """
        return self.execution_mode == "local" and self.approval.required

    def require_remediation_target_branch(self, *, reason: str) -> str:
        """Return the shared remediation target branch or fail with a scoped message."""
        if self.remediation.target_branch is None:
            raise ValueError(f"{reason} requires remediation.target_branch to be configured.")
        return self.remediation.target_branch

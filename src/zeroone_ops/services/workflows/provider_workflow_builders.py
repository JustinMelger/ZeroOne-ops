"""Lazy provider-local dependency construction for workflow entrypoints."""

from __future__ import annotations

import logging
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review_linkage import LinkedReviewWorkItem
from zeroone_ops.models.state import AppState
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_policy_client import GitLabPolicyClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.providers.review.github import GitHubReviewClient
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.providers.review.platform import ChangeRequestReviewPlatformProtocol
from zeroone_ops.services.control_plane.github_comment_authorization_service import (
    GitHubCommentAuthorizationService,
)
from zeroone_ops.services.control_plane.policy.github_policy_issue_service import (
    GitHubPolicyIssueService,
)
from zeroone_ops.services.control_plane.policy.github_policy_processing_runner import (
    GitHubPolicyProcessingRunner,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service import (
    GitLabPolicyIssueService,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_processing_runner import (
    GitLabPolicyProcessingRunner,
)
from zeroone_ops.services.control_plane.policy.policy_view_builder import PolicyViewBuilder
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_runner import (
    GitHubWorkItemRecoveryRunner,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_service import (
    GitHubWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.review.context.remediation_review_context_resolver import (
    RemediationReviewContextResolver,
)
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.settings import (
    load_current_change_request_number,
    load_current_github_pull_request_head_sha,
    load_current_github_pull_request_number,
    load_github_connection_config,
    load_gitlab_connection_config,
)


def build_github_policy_issue_service(
    *, repo_root: Path, config: AppConfig, state: AppState
) -> GitHubPolicyIssueService:
    """Build lazy GitHub policy access for a control-plane workflow."""
    return GitHubPolicyIssueService(
        GitHubPolicyClient(load_github_connection_config()),
        policy_view_builder=PolicyViewBuilder(
            bootstrap_severities=config.remediation.bootstrap_severities
        ),
    )


def build_github_policy_processing_runner(
    *, repo_root: Path, config: AppConfig, state: AppState, run_state_service: RunStateService
) -> GitHubPolicyProcessingRunner:
    """Build GitHub policy processing only when that workflow is selected."""
    return GitHubPolicyProcessingRunner(
        policy_issue_service=build_github_policy_issue_service(
            repo_root=repo_root, config=config, state=state
        ),
        run_state_service=run_state_service,
    )


def build_gitlab_policy_issue_service(
    *, repo_root: Path, config: AppConfig, state: AppState
) -> GitLabPolicyIssueService:
    """Build lazy GitLab issue-mode policy access for a workflow."""
    return GitLabPolicyIssueService(
        GitLabPolicyClient(load_gitlab_connection_config()),
        policy_view_builder=PolicyViewBuilder(
            bootstrap_severities=config.remediation.bootstrap_severities
        ),
    )


def build_gitlab_policy_processing_runner(
    *, repo_root: Path, config: AppConfig, state: AppState, run_state_service: RunStateService
) -> GitLabPolicyProcessingRunner:
    """Build GitLab issue-mode policy processing lazily."""
    return GitLabPolicyProcessingRunner(
        policy_issue_service=build_gitlab_policy_issue_service(
            repo_root=repo_root, config=config, state=state
        ),
        run_state_service=run_state_service,
    )


def build_github_work_item_recovery_runner(
    *, run_state_service: RunStateService
) -> tuple[GitHubWorkItemRecoveryRunner, GitHubWorkItemService]:
    """Build GitHub recovery processing and its shared work-item access."""
    work_item_client = GitHubWorkItemClient(load_github_connection_config())
    work_item_service = GitHubWorkItemService(work_item_client)
    return (
        GitHubWorkItemRecoveryRunner(
            recovery_service=GitHubWorkItemRecoveryService(
                comment_client=work_item_client,
                comment_authorization_service=GitHubCommentAuthorizationService(work_item_client),
                work_item_service=work_item_service,
            ),
            run_state_service=run_state_service,
        ),
        work_item_service,
    )


def build_review_platform_runtime(
    config: AppConfig,
) -> tuple[
    ChangeRequestReviewPlatformProtocol,
    str,
    int | None,
    str | None,
]:
    """Build review dependencies for the configured provider only."""
    if config.platform == "github":
        github_config = load_github_connection_config()
        return (
            GitHubReviewClient(github_config),
            github_config.repository,
            load_current_github_pull_request_number(),
            load_current_github_pull_request_head_sha(),
        )

    gitlab_config = load_gitlab_connection_config()
    return (
        GitLabReviewClient(gitlab_config),
        gitlab_config.project_id,
        load_current_change_request_number(),
        None,
    )


def build_review_remediation_context_resolver(
    config: AppConfig, logger: logging.Logger
) -> RemediationReviewContextResolver:
    """Compose provider-local read-only lookup, deferring settings and clients until resolution."""

    def lookup(repository_id: str, change_request_number: int) -> LinkedReviewWorkItem | None:
        """Normalize a unique open link while keeping construction within guarded resolution."""
        if config.platform == "github":
            github_result = GitHubWorkItemService(
                GitHubWorkItemClient(load_github_connection_config())
            ).find_open_work_item_by_change_request(
                repository_id=repository_id, change_request_number=change_request_number
            )
            return (
                None
                if github_result is None
                else LinkedReviewWorkItem(github_result.work_item, github_result.issue.web_url)
            )
        if config.platform == "gitlab":
            gitlab_result = GitLabWorkItemService(
                GitLabWorkItemClient(load_gitlab_connection_config())
            ).find_open_work_item_by_change_request(
                project_id=repository_id, change_request_number=change_request_number
            )
            return (
                None
                if gitlab_result is None
                else LinkedReviewWorkItem(gitlab_result.work_item, gitlab_result.issue.web_url)
            )
        return None

    return RemediationReviewContextResolver(lookup=lookup, logger=logger)

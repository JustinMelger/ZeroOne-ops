"""Compose the real review pipeline with fixed settings and offline transports."""

from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from zeroone_ops.models.config import (
    AppConfig,
    GitHubConfig,
    GitHubConnectionConfig,
    GitLabConfig,
    GitLabConnectionConfig,
    OpenAIConnectionConfig,
    RemediationConfig,
    ReviewConfig,
)
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_client import GitHubClient
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.providers.llm_client import OpenAILLMClient
from zeroone_ops.providers.review.github import GitHubReviewClient
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.review.continuity.review_overlap_analysis_service import (
    ReviewOverlapAnalysisService,
)
from zeroone_ops.services.review.pipeline.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
)
from zeroone_ops.services.review.pipeline.review_reconciliation_service import (
    ReviewReconciliationService,
)
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.shared.state_store import StateStore

from .provider_api import REPOSITORY_SCOPE
from .repository import git
from .review_cases import REVIEW_PATH, ReviewCase
from .review_provider_api import ReviewProviderAPI
from .review_scripted_sdk import ScriptedReviewSDK
from .review_work_item import linked_review_work_item


@dataclass
class ReviewHarness:
    """Keep actual state and transport reusable across sequential request runs."""

    api: ReviewProviderAPI
    http: httpx.Client
    state_service: ReviewStateService
    monkeypatch: pytest.MonkeyPatch

    def _connection(self) -> GitHubConnectionConfig | GitLabConnectionConfig:
        if self.api.work_items.platform == "github":
            return GitHubConnectionConfig(
                api_url="https://provider.invalid",
                server_url="https://provider.invalid",
                token="offline-test-token",
                repository=REPOSITORY_SCOPE,
            )
        return GitLabConnectionConfig(
            url="https://provider.invalid", token="offline-test-token", project_id=REPOSITORY_SCOPE
        )

    def install_transport(self) -> None:
        """Route even runner-created context/projection clients to the same fake HTTP store."""
        github = self.api.work_items.platform == "github"
        connection = self._connection()
        loader = "load_github_connection_config" if github else "load_gitlab_connection_config"
        self.monkeypatch.setattr(
            f"zeroone_ops.services.review.pipeline.review_runner.{loader}", lambda: connection
        )
        clients = (
            (GitHubReviewClient, GitHubWorkItemClient, GitHubClient)
            if github
            else (GitLabReviewClient, GitLabWorkItemClient)
        )
        for client_type in clients:
            original = client_type.__init__

            def initialize(client, config, http_client=None, *, original=original):
                assert config == connection, "Wrong review client connection settings"
                assert http_client is None or http_client is self.http
                original(client, config, http_client=self.http)

            self.monkeypatch.setattr(client_type, "__init__", initialize)

    def seed_link(self, case: ReviewCase) -> WorkItemState:
        """Persist a real rendered work item through the real provider upsert service."""
        self.api.active_number = case.number
        state = linked_review_work_item(case)
        if self.api.work_items.platform == "github":
            service = GitHubWorkItemService(GitHubWorkItemClient(self._connection()))
            return service.upsert_work_item(
                repository_id=REPOSITORY_SCOPE, work_item=state
            ).work_item
        service = GitLabWorkItemService(GitLabWorkItemClient(self._connection()))
        return service.upsert_work_item(project_id=REPOSITORY_SCOPE, work_item=state).work_item

    def run(self, case: ReviewCase, sdk: ScriptedReviewSDK) -> RunSummary:
        """Run real intake through finalization on the explicitly pinned fixture checkout."""
        assert git(case.root, "rev-parse", "HEAD") == case.head_sha
        assert (case.root / REVIEW_PATH).read_text() == case.after
        self.api.active_number = case.number
        llm = OpenAILLMClient(
            OpenAIConnectionConfig(
                api_key="offline-test-key",
                model="offline-review-model",
                base_url="https://model.invalid",
                mlflow_enabled=False,
            ),
            solution_output_path=None,
        )
        llm.client.close()
        llm.client = sdk
        for stage in (
            ReviewCandidateGenerationService,
            ReviewReconciliationService,
            ReviewOverlapAnalysisService,
        ):
            self.monkeypatch.setattr(stage, "_build_llm_client", lambda self: llm)
        client = (
            GitHubReviewClient(self._connection())
            if self.api.work_items.platform == "github"
            else GitLabReviewClient(self._connection())
        )
        runner = ReviewRunner(
            repo_root=case.root,
            config=AppConfig(
                platform=self.api.work_items.platform,
                base_branch="main",
                execution_mode="ci",
                github=GitHubConfig(),
                gitlab=GitLabConfig(),
                remediation=RemediationConfig(target_branch="main"),
                repository_guidance_paths=["AGENTS.md"],
                review=ReviewConfig(
                    supported_paths=["src/"],
                    max_context_lines_before=100,
                    max_context_lines_after=100,
                    enable_function_context=False,
                    enable_helper_following=False,
                    inline_comments_enabled=True,
                ),
            ),
            review_client=client,
            review_state_service=self.state_service,
        )
        run_id = f"offline-review-{case.number}-{case.head_sha}"
        summary = runner.run(
            repository_id=REPOSITORY_SCOPE,
            current_change_request_number=case.number,
            triggered_head_sha=case.head_sha,
            run_id=run_id,
            record=self.state_service.start_run(run_id),
            active_dry_run=False,
        )
        assert len(sdk.calls) == sdk.expected_call_count, "Unused scripted review responses"
        return summary


def compose_review_harness(
    api: ReviewProviderAPI, http: httpx.Client, state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ReviewHarness:
    """Load real shared review state without environment or provider settings access."""
    store = StateStore(
        state_path, base_branch="main", gitlab_project_id=None, sonarqube_project_key=None
    )
    service = ReviewStateService(store, store.load())
    harness = ReviewHarness(api, http, service, monkeypatch)
    harness.install_transport()
    return harness

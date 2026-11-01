"""Compose authorized commands and lifecycle over the existing offline harness."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
import pytest

from zeroone_ops.models.work_item import (
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    WorkItemState,
)
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.services.control_plane.github_comment_authorization_service import (
    GitHubCommentAuthorizationService,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lifecycle_service import (
    GitHubWorkItemLifecycleService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_runner import (
    GitHubWorkItemRecoveryRunner,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_service import (
    GitHubWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lifecycle_service import (
    GitLabWorkItemLifecycleService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_runner import (
    GitLabWorkItemRecoveryRunner,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_service import (
    GitLabWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.work_item_lifecycle_service import (
    WorkItemLifecycleResult,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)
from zeroone_ops.services.shared.run_state_service import RunSummary

from .harness import SCOPE, ScenarioHarness
from .repository import TARGET_PATH, ScenarioRepository, git
from .revision import RevisionModel, persist_work_item

ACTION_AT = datetime(2030, 1, 1, tzinfo=UTC)
COMMAND_AT = ACTION_AT + timedelta(minutes=1)


@dataclass(frozen=True)
class OperatorLoop:
    """Drive real provider runners while retaining only native HTTP authority."""

    harness: ScenarioHarness
    repository: ScenarioRepository
    recovery: GitHubWorkItemRecoveryRunner | GitLabWorkItemRecoveryRunner
    lifecycle: GitHubWorkItemLifecycleService | GitLabWorkItemLifecycleService

    def feedback(self) -> WorkItemState:
        """Persist actionable review evidence, not a pre-authorized queued revision."""
        original = self.harness.work_item()
        return persist_work_item(
            self.harness,
            original.model_copy(
                update={
                    "status": "review_feedback_required",
                    "review_action_required_at": ACTION_AT,
                    "projected_review": ProjectedReviewState(
                        classification="findings_present",
                        reviewed_sha=git(self.repository.root, "rev-parse", "HEAD"),
                        follow_up_required=True,
                        feedback=ProjectedReviewFeedback(
                            summary="Preserve value",
                            finding_count=1,
                            findings=[
                                ProjectedReviewFinding(
                                    title="Keep constant",
                                    file_path=TARGET_PATH,
                                    evidence="Keep the exported value",
                                    explanation="Callers import value",
                                    suggested_follow_up="Annotate without changing it",
                                )
                            ],
                        ),
                    ),
                }
            ),
        )

    def comment(
        self,
        identifier: int,
        *,
        at: datetime = COMMAND_AT,
        actor: Literal["operator", "outsider"] = "operator",
    ) -> str:
        """Supply a native issue event with explicit permissions and stable ordering."""
        api = self.harness.api
        number = next(iter(api.issues))
        user_id = 7 if actor == "operator" else 8
        api.issue_comments.setdefault(number, []).append(
            {
                "id": identifier,
                "body": "/zeroone remediation requeue",
                "created_at": at.isoformat(),
                "html_url": f"https://provider.invalid/issues/{number}#comment-{identifier}",
                "user": {"login": actor},
                "author": {"id": user_id, "username": actor},
            }
        )
        prefix = "github-comment" if api.platform == "github" else "gitlab-note"
        return f"{prefix}-{identifier}"

    def requeue(self, identifier: int, *, dry_run: bool = False) -> RunSummary:
        """Use event targeting on GitHub and scheduled note polling on GitLab."""
        record = self.harness.runs.start_run(
            f"command-{identifier}-{len(self.harness.runs.state.runs)}"
        )
        if isinstance(self.recovery, GitHubWorkItemRecoveryRunner):
            return self.recovery.run(
                repository_id=SCOPE,
                issue_number=next(iter(self.harness.api.issues)),
                comment_id=identifier,
                policy_eligible=FindingWorkflowPolicyService().is_work_item_eligible(
                    work_item=self.harness.work_item(), policy_state=self.harness.policy
                ),
                record=record,
                active_dry_run=dry_run,
                execution_mode="ci",
            )
        return self.recovery.run(
            project_id=SCOPE,
            policy_state=self.harness.policy,
            record=record,
            active_dry_run=dry_run,
            execution_mode="ci",
        )

    def reconcile(self, *, persist: bool = True) -> WorkItemLifecycleResult:
        """Run provider-local lifecycle composition at a deterministic instant."""
        scope = {"repository_id" if self.harness.api.platform == "github" else "project_id": SCOPE}
        return self.lifecycle.reconcile(
            now=COMMAND_AT + timedelta(hours=1), persist=persist, **scope
        )

    def request_state(self, state: Literal["opened", "closed", "merged"]) -> None:
        """Supply native request state; no provider merge or remote Git mutation is simulated."""
        payload = next(iter(self.harness.api.requests.values()))
        if self.harness.api.platform == "github":
            payload["state"] = "open" if state == "opened" else "closed"
            payload["merged_at"] = COMMAND_AT.isoformat() if state == "merged" else None
        else:
            payload["state"] = state

    def revise(
        self, monkeypatch: pytest.MonkeyPatch, *, succeeds: bool
    ) -> tuple[RunSummary, RevisionModel]:
        """Execute a finite model script from main against the verified request checkout."""
        harness = self.harness
        model = RevisionModel(
            harness,
            self.repository,
            harness.work_item(),
            git(self.repository.root, "rev-parse", "HEAD"),
            succeeds,
        )
        monkeypatch.setattr(harness.engine.analysis_service, "_build_llm_client", lambda: model)
        git(self.repository.root, "checkout", "main")
        summary = harness.runner.run(
            record=harness.runs.start_run(f"revision-{len(harness.runs.state.runs)}"),
            active_dry_run=False,
        )
        return summary, model


def compose_operator_loop(
    harness: ScenarioHarness, repository: ScenarioRepository, http: httpx.Client
) -> OperatorLoop:
    """Compose real authorization, recovery runners, and provider lifecycle services."""
    work_items = harness.work_items
    client = work_items.lookup_service.client
    publisher = harness.engine.publish_service.change_request_publisher
    if harness.api.platform == "github":
        recovery = GitHubWorkItemRecoveryRunner(
            recovery_service=GitHubWorkItemRecoveryService(
                comment_client=client,
                comment_authorization_service=GitHubCommentAuthorizationService(client),
                work_item_service=work_items,
            ),
            run_state_service=harness.runs,
        )
        lifecycle = GitHubWorkItemLifecycleService(
            work_item_service=work_items, change_request_client=publisher.github_client
        )
    else:
        recovery = GitLabWorkItemRecoveryRunner(
            recovery_service=GitLabWorkItemRecoveryService(
                note_client=client,
                note_authorization_service=GitLabPolicyNoteAuthorizationService(client),
                work_item_service=work_items,
            ),
            work_item_service=work_items,
            policy_service=FindingWorkflowPolicyService(),
            run_state_service=harness.runs,
        )
        lifecycle = GitLabWorkItemLifecycleService(
            work_item_service=work_items,
            change_request_client=GitLabReviewClient(
                publisher.gitlab_client.config, http_client=http
            ),
        )
    return OperatorLoop(harness, repository, recovery, lifecycle)

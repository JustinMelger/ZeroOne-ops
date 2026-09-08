from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from zeroone_ops.models.analysis import (
    CodeContextSnippet,
    IssueContext,
    ValidationComparison,
    ValidationResult,
)
from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitHubConfig,
    RemediationConfig,
    StateConfig,
)
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import (
    AppState,
    FailureDetails,
    FailureStage,
    RepositoryState,
    RunStatus,
)
from zeroone_ops.models.work_item import (
    PublicationRetryState,
    WorkItemExecutionFailure,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
)
from zeroone_ops.services.remediation.analysis_service import AnalysisResult
from zeroone_ops.services.remediation.change_request_publisher import ChangeRequestPublishRequest
from zeroone_ops.services.remediation.control_plane import RemediationControlPlane
from zeroone_ops.services.remediation.execution_service import ExecutionResult, ExecutionService
from zeroone_ops.services.remediation.github_remediation_runner import GitHubRemediationRunner
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryResult,
    PublicationRetryService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore


class FakeGitHubWorkItemService:
    """Store GitHub work-item state in memory for runner lifecycle tests."""

    def __init__(self, work_item: WorkItemState | None) -> None:
        self.work_item = work_item
        self.upserted_work_items: list[WorkItemState] = []

    def list_open_work_items(
        self,
        *,
        repository_id: str,
    ) -> list[GitHubWorkItemLookupResult]:
        del repository_id
        if self.work_item is None:
            return []
        return [
            GitHubWorkItemLookupResult(
                issue=GitHubIssueInfo(
                    id=1,
                    number=12,
                    web_url="https://github.example.com/octo-org/octo-repo/issues/12",
                    title=self.work_item.summary,
                    body="machine state",
                    created_at=datetime(2026, 7, 26, tzinfo=UTC),
                ),
                work_item=self.work_item,
            )
        ]

    def upsert_work_item(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
    ) -> GitHubWorkItemUpsertResult:
        del repository_id
        self.work_item = work_item
        self.upserted_work_items.append(work_item)
        return GitHubWorkItemUpsertResult(
            issue=self.list_open_work_items(repository_id="")[0].issue,
            action="updated",
            work_item=work_item,
        )


class StubExecutionService:
    """Return one predetermined shared execution outcome."""

    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.calls: list[tuple[RemediationExecutionTarget, bool, str | None]] = []

    def execute_with_context(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        dry_run: bool,
        branch_name: str | None = None,
        attempt_number: int = 1,
    ) -> ExecutionResult:
        del context, attempt_number
        self.calls.append((selected_issue, dry_run, branch_name))
        return self.result


class StubPublicationRetryService:
    """Return one bounded publication retry result without provider transport."""

    def __init__(self, result: PublicationRetryResult) -> None:
        self.result = result
        self.calls: list[PublicationRetryState] = []
        self.requests: list[ChangeRequestPublishRequest] = []

    def retry(
        self,
        *,
        publication_retry: PublicationRetryState,
        request: ChangeRequestPublishRequest,
    ) -> PublicationRetryResult:
        self.calls.append(publication_retry)
        self.requests.append(request)
        return self.result


class StubControlPlane:
    """Capture terminal projections without provider transport."""

    def __init__(self) -> None:
        self.blocked: list[str] = []
        self.execution_failures: list[WorkItemExecutionFailure | None] = []
        self.dismissed: list[str] = []
        self.dismissal_failures: list[WorkItemExecutionFailure | None] = []
        self.completed: list[str] = []
        self.publish_blocked: list[str] = []
        self.linked_change_requests: list[str] = []

    def materialize_promoted_work_item(self, **kwargs: object) -> WorkItemState | None:
        del kwargs
        return None

    def mark_publish_started(self, **kwargs: object) -> WorkItemState | None:
        del kwargs
        return None

    def mark_execution_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety=None,
    ) -> None:
        del existing_work_item, semantic_safety
        self.blocked.append(selected_issue.item_id)
        self.execution_failures.append(execution_failure)

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety=None,
    ) -> None:
        del existing_work_item, semantic_safety
        self.dismissed.append(selected_issue.item_id)
        self.dismissal_failures.append(execution_failure)

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        del existing_work_item
        self.completed.append(selected_issue.item_id)

    def mark_publish_blocked(self, **kwargs: object) -> None:
        selected_issue = kwargs["selected_issue"]
        assert isinstance(selected_issue, RemediationExecutionTarget)
        self.publish_blocked.append(selected_issue.item_id)

    def sync_change_request_link(self, **kwargs: object) -> None:
        selected_issue = kwargs["selected_issue"]
        assert isinstance(selected_issue, RemediationExecutionTarget)
        self.linked_change_requests.append(selected_issue.item_id)


def _config(state_path: Path) -> AppConfig:
    return AppConfig(
        platform="github",
        execution_mode="ci",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(target_branch="main", analysis=AnalysisConfig()),
        github=GitHubConfig(labels=[]),
        state=StateConfig(path=state_path),
    )


def _work_item() -> WorkItemState:
    return WorkItemState(
        work_item_id="github-work-1",
        kind="remediation",
        status="approved",
        source=WorkItemSourceRef(
            source="ruff",
            source_item_key="F841:src/service.py:12",
            repository_scope="octo-org/octo-repo",
        ),
        summary="Unused local variable.",
        severity="high",
        file_path="src/service.py",
        line=12,
    )


def _run_state_service(tmp_path: Path) -> RunStateService:
    config = _config(tmp_path / ".zeroone-ops-state.json")
    store = StateStore(
        config.state.path,
        base_branch="main",
        gitlab_project_id=None,
        sonarqube_project_key=None,
    )
    return RunStateService(
        config=config,
        state_store=store,
        state=AppState(repository=RepositoryState(base_branch="main")),
    )


def _execution_result(**updates: object) -> ExecutionResult:
    values: dict[str, object] = {
        "analysis_result": AnalysisResult(summary="Analysis completed."),
        "status_message": "Remediation completed.",
    }
    values.update(updates)
    return ExecutionResult(**values)  # type: ignore[arg-type]


def _runner(
    *,
    tmp_path: Path,
    run_state_service: RunStateService,
    work_item_service: FakeGitHubWorkItemService,
    execution_service: StubExecutionService,
    control_plane: StubControlPlane,
    publication_retry_service: StubPublicationRetryService | None = None,
) -> GitHubRemediationRunner:
    return GitHubRemediationRunner(
        repo_root=tmp_path,
        config=_config(tmp_path / ".zeroone-ops-state.json"),
        repository_id="octo-org/octo-repo",
        work_item_service=cast("GitHubWorkItemService", work_item_service),
        run_state_service=run_state_service,
        execution_service=cast(ExecutionService, execution_service),
        remediation_control_plane=cast(RemediationControlPlane, control_plane),
        publication_retry_service=cast(PublicationRetryService | None, publication_retry_service),
    )


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> IssueContext:
    result = IssueContext(
        issue_key="github-work-1",
        file_path="src/service.py",
        line=12,
        file_size_bytes=20,
        snippet=CodeContextSnippet(start_line=10, end_line=14, content="value = 1"),
        full_file_included=True,
        truncated=False,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder."
        "RemediationContextBuilder.build",
        lambda self, target: result,
    )
    return result


def test_runner_completes_unpublished_work_item(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    work_item_service = FakeGitHubWorkItemService(_work_item())
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=work_item_service,
        execution_service=StubExecutionService(_execution_result(commit_sha="abc123")),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.SELECTED
    assert summary.work_item_id == "github-work-1"
    assert work_item_service.upserted_work_items[0].status == "in_progress"
    assert control_plane.completed == ["github-work-1"]


def test_runner_blocks_failed_work_item(
    tmp_path: Path,
    context: IssueContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del context
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.example.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    run_state_service = _run_state_service(tmp_path)
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(
                failure=FailureDetails(
                    stage=FailureStage.VALIDATION,
                    message="Checks failed.",
                    failed_command="uv run pytest",
                    exit_code=1,
                    stderr_excerpt="FAILED tests/example.py::test_example",
                )
            )
        ),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.FAILED
    assert "Failed command output:" in summary.message
    assert "FAILED tests/example.py::test_example" in summary.message
    assert control_plane.blocked == ["github-work-1"]
    execution_failure = control_plane.execution_failures[0]
    assert execution_failure is not None
    assert execution_failure.run_id == "run-1"
    assert execution_failure.execution_url == (
        "https://github.example.com/octo-org/octo-repo/actions/runs/42"
    )


def test_runner_persists_validation_setup_guidance_without_command_output(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(
                failure=FailureDetails(
                    stage=FailureStage.VALIDATION_SETUP,
                    message="Validation environment setup failed: uv sync --locked (exit code 1).",
                    failed_command="uv sync --locked",
                    exit_code=1,
                    stderr_excerpt="Authorization: Bearer private-token",
                )
            )
        ),
        control_plane=control_plane,
    )

    runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    execution_failure = control_plane.execution_failures[0]
    assert execution_failure is not None
    assert "package-registry access" in execution_failure.summary
    assert "private-token" not in execution_failure.summary
    assert execution_failure.failed_command == "uv sync --locked"
    assert execution_failure.exit_code == 1


def test_runner_dismisses_rejected_work_item(tmp_path: Path, context: IssueContext) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(
                final_status=RunStatus.REJECTED,
                status_message="Rejected.",
                terminal_rejection_stage=FailureStage.APPROVAL,
            )
        ),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.REJECTED
    assert control_plane.dismissed == ["github-work-1"]
    dismissal_failure = control_plane.dismissal_failures[0]
    assert dismissal_failure is not None
    assert dismissal_failure.stage == "approval"


def test_runner_projects_change_request_link_after_injected_execution(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(
                change_request_url="https://github.example.com/octo-org/octo-repo/pull/9",
                change_request_action="created",
                published_change_request=ChangeRequestInfo(
                    iid=9,
                    web_url="https://github.example.com/octo-org/octo-repo/pull/9",
                    title="fix: remediation",
                ),
            )
        ),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.CHANGE_REQUEST_CREATED
    assert control_plane.completed == []
    assert control_plane.blocked == []
    assert control_plane.dismissed == []
    assert control_plane.linked_change_requests == ["github-work-1"]


def test_runner_exposes_successful_validation_feedback_outcome(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    """Successful validation-feedback results remain available for workflow tracing."""
    del context
    run_state_service = _run_state_service(tmp_path)
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(
                analysis_result=AnalysisResult(
                    summary="Analysis completed.",
                    validation_comparison=ValidationComparison(
                        outcome="baseline_preserved",
                        baseline=ValidationResult(passed=False, summary="baseline failed"),
                        post_edit=ValidationResult(passed=False, summary="baseline preserved"),
                        baseline_failure_count=1,
                    ),
                ),
                change_request_url="https://github.example.com/octo-org/octo-repo/pull/9",
                change_request_action="created",
                published_change_request=ChangeRequestInfo(
                    iid=9,
                    web_url="https://github.example.com/octo-org/octo-repo/pull/9",
                    title="fix: remediation",
                ),
            )
        ),
        control_plane=StubControlPlane(),
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.validation_outcome == "baseline_preserved"


def test_runner_blocks_published_change_request_without_provider_identity(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(
                change_request_url="https://github.example.com/octo-org/octo-repo/pull/9",
                change_request_action="created",
            )
        ),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.FAILED
    assert "missing identity" in summary.message
    assert control_plane.blocked == ["github-work-1"]
    assert control_plane.linked_change_requests == []


def test_runner_retries_recorded_publication_without_rerunning_execution(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    work_item = _work_item().model_copy(
        update={
            "publication_retry": PublicationRetryState(
                branch_name="zeroone-ops/ruff-sarif/fix",
                commit_sha="abc123",
                reason="change_request_publish_failed",
                remediation_intent="fix",
            )
        }
    )
    execution_service = StubExecutionService(_execution_result())
    control_plane = StubControlPlane()
    retry_service = StubPublicationRetryService(
        PublicationRetryResult(
            change_request=ChangeRequestInfo(
                iid=9,
                web_url="https://github.example.com/octo-org/octo-repo/pull/9",
                title="fix: remediation",
            ),
            action="created",
        )
    )
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(work_item),
        execution_service=execution_service,
        control_plane=control_plane,
        publication_retry_service=retry_service,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.CHANGE_REQUEST_CREATED
    assert summary.change_request_url == "https://github.example.com/octo-org/octo-repo/pull/9"
    assert execution_service.calls == []
    assert retry_service.calls == [work_item.publication_retry]
    assert retry_service.requests[0].title.startswith("fix:")
    assert control_plane.linked_change_requests == ["github-work-1"]


def test_runner_keeps_failed_publication_retry_blocked(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    work_item = _work_item().model_copy(
        update={
            "publication_retry": PublicationRetryState(
                branch_name="zeroone-ops/ruff-sarif/fix",
                commit_sha="abc123",
                reason="change_request_publish_failed",
            )
        }
    )
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(work_item),
        execution_service=StubExecutionService(_execution_result()),
        control_plane=control_plane,
        publication_retry_service=StubPublicationRetryService(
            PublicationRetryResult(
                error_message="Recorded remediation branch no longer exists remotely."
            )
        ),
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.FAILED
    assert "Recorded remediation branch no longer exists remotely." in summary.message
    assert control_plane.publish_blocked == ["github-work-1"]


def test_runner_dry_run_does_not_claim_or_project_work_item(
    tmp_path: Path,
    context: IssueContext,
) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    work_item_service = FakeGitHubWorkItemService(_work_item())
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=work_item_service,
        execution_service=StubExecutionService(_execution_result()),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=True)

    assert summary.status == RunStatus.SELECTED
    assert work_item_service.upserted_work_items == []
    assert control_plane.completed == []

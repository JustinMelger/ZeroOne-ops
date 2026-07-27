from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from zeroone_ops.models.analysis import CodeContextSnippet, IssueContext
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
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
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
from zeroone_ops.services.remediation.control_plane import RemediationControlPlane
from zeroone_ops.services.remediation.execution_service import ExecutionResult, ExecutionService
from zeroone_ops.services.remediation.github_remediation_runner import GitHubRemediationRunner
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
        self.calls: list[tuple[RemediationExecutionTarget, bool]] = []

    def execute_with_context(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        dry_run: bool,
    ) -> ExecutionResult:
        del context
        self.calls.append((selected_issue, dry_run))
        return self.result


class StubControlPlane:
    """Capture terminal projections without provider transport."""

    def __init__(self) -> None:
        self.blocked: list[str] = []
        self.dismissed: list[str] = []
        self.completed: list[str] = []

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
    ) -> None:
        del existing_work_item
        self.blocked.append(selected_issue.item_id)

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        del existing_work_item
        self.dismissed.append(selected_issue.item_id)

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        del existing_work_item
        self.completed.append(selected_issue.item_id)

    def mark_publish_blocked(self, **kwargs: object) -> None:
        del kwargs

    def sync_change_request_link(self, **kwargs: object) -> None:
        del kwargs


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
) -> GitHubRemediationRunner:
    return GitHubRemediationRunner(
        repo_root=tmp_path,
        config=_config(tmp_path / ".zeroone-ops-state.json"),
        repository_id="octo-org/octo-repo",
        work_item_service=cast("GitHubWorkItemService", work_item_service),
        run_state_service=run_state_service,
        execution_service=cast(ExecutionService, execution_service),
        remediation_control_plane=cast(RemediationControlPlane, control_plane),
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


def test_runner_blocks_failed_work_item(tmp_path: Path, context: IssueContext) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(
                failure=FailureDetails(stage=FailureStage.VALIDATION, message="Checks failed.")
            )
        ),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.FAILED
    assert control_plane.blocked == ["github-work-1"]


def test_runner_dismisses_rejected_work_item(tmp_path: Path, context: IssueContext) -> None:
    del context
    run_state_service = _run_state_service(tmp_path)
    control_plane = StubControlPlane()
    runner = _runner(
        tmp_path=tmp_path,
        run_state_service=run_state_service,
        work_item_service=FakeGitHubWorkItemService(_work_item()),
        execution_service=StubExecutionService(
            _execution_result(final_status=RunStatus.REJECTED, status_message="Rejected.")
        ),
        control_plane=control_plane,
    )

    summary = runner.run(record=run_state_service.start_run("run-1"), active_dry_run=False)

    assert summary.status == RunStatus.REJECTED
    assert control_plane.dismissed == ["github-work-1"]


def test_runner_leaves_change_request_projection_to_publish_service(
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

    assert summary.status == RunStatus.CHANGE_REQUEST_CREATED
    assert control_plane.completed == []
    assert control_plane.blocked == []
    assert control_plane.dismissed == []


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

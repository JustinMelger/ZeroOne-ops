from pathlib import Path
from typing import cast

import pytest

from zeroone_ops.models.analysis import CodeContextSnippet, IssueContext
from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.remediation import RemediationExecutionTarget, RemediationWorkItem
from zeroone_ops.models.state import AppState, RepositoryState
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.remediation_work_item_promotion_service import (
    RemediationWorkItemPromotionContext,
)
from zeroone_ops.services.dashboard.dashboard_remediation_runner import (
    DashboardRemediationRunner,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore


class DummyDashboardService:
    pass


class StubRemediationControlPlane:
    def __init__(self, *, raise_on_materialize: bool = False) -> None:
        self.calls: list[tuple[RemediationWorkItem, RemediationWorkItemPromotionContext]] = []
        self.blocked_calls: list[tuple[RemediationExecutionTarget, WorkItemState | None]] = []
        self.dismissed_calls: list[tuple[RemediationExecutionTarget, WorkItemState | None]] = []
        self.completed_calls: list[tuple[RemediationExecutionTarget, WorkItemState | None]] = []
        self.raise_on_materialize = raise_on_materialize

    def materialize_promoted_work_item(
        self,
        *,
        work_item: RemediationWorkItem,
        promotion_context: RemediationWorkItemPromotionContext,
    ) -> WorkItemState | None:
        self.calls.append((work_item, promotion_context))
        if self.raise_on_materialize:
            raise RuntimeError("promotion materialization failed")
        return WorkItemState(
            work_item_id="work-1",
            kind="remediation",
            status="approved",
            source=WorkItemSourceRef(
                source=work_item.source_type,
                source_item_key=work_item.source_ref,
                repository_scope="octo-org/octo-repo",
            ),
            summary=work_item.title,
            severity=work_item.severity,
            file_path=work_item.file_path,
            line=work_item.line,
        )

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState | None:
        del selected_issue
        return None

    def mark_publish_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        del selected_issue, existing_work_item

    def mark_execution_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        self.blocked_calls.append((selected_issue, existing_work_item))

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        self.dismissed_calls.append((selected_issue, existing_work_item))

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        self.completed_calls.append((selected_issue, existing_work_item))

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        del selected_issue, published_change_request, existing_work_item


def build_config() -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            target_branch="main",
            bootstrap_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main", labels=[]),
    )


def build_selected_item() -> DashboardItem:
    return DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )


def build_work_item() -> RemediationWorkItem:
    return RemediationWorkItem(
        dashboard_item_id="sonar:AX123",
        source_type="sonarqube",
        source_ref="AX123",
        title="python:S1125 in src/service.py",
        status="open",
        message="Replace boolean equality with direct truthiness.",
        file_path="src/service.py",
        line=42,
        rule_id="python:S1125",
        severity="LOW",
    )


def build_run_state_service(tmp_path: Path) -> tuple[RunStateService, AppState]:
    config = build_config()
    state_store = StateStore(
        tmp_path / "state.json",
        base_branch=config.base_branch,
        gitlab_project_id=None,
        sonarqube_project_key=None,
    )
    state = AppState(repository=RepositoryState(base_branch=config.base_branch))
    return RunStateService(config=config, state_store=state_store, state=state), state


def test_runner_materializes_promoted_work_item_for_live_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_state_service, state = build_run_state_service(tmp_path)
    record = run_state_service.start_run("run-1")
    control_plane = StubRemediationControlPlane()
    selected_item = build_selected_item().model_copy(update={"attempt_number": 2})
    work_item = build_work_item()
    branch_names: list[str] = []

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": work_item,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder."
        "RemediationContextBuilder.build",
        lambda self, item: IssueContext(
            issue_key=item.dashboard_item_id,
            file_path=item.file_path,
            line=item.line,
            file_size_bytes=12,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="42: value = value"),
            full_file_included=True,
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater."
        "DashboardRemediationUpdater.mark_in_progress",
        lambda self, **kwargs: type(
            "UpdateResult",
            (),
            {"dashboard_issue_url": None, "updated_item": selected_item, "error_message": None},
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        lambda self, selected_issue, context, dry_run, branch_name: (
            branch_names.append(branch_name),
            type(
                "ExecutionResult",
                (),
                {
                    "failure": None,
                    "final_status": None,
                    "status_message": "Remediation completed.",
                    "branch_name": branch_name,
                    "commit_sha": "abc123",
                    "change_request_url": None,
                    "change_request_action": None,
                },
            )(),
        )[1],
    )

    summary = DashboardRemediationRunner(
        repo_root=tmp_path,
        config=build_config(),
        dashboard_service=cast(DashboardService, DummyDashboardService()),
        run_state_service=run_state_service,
        remediation_control_plane=control_plane,
    ).run(
        project_id="123",
        state=state,
        run_id="run-1",
        record=record,
        active_dry_run=False,
    )

    assert summary.status.value == "selected"
    assert len(control_plane.calls) == 1
    materialized_work_item, promotion_context = control_plane.calls[0]
    assert materialized_work_item.dashboard_item_id == "sonar:AX123"
    assert promotion_context.selected_for_remediation is True
    assert promotion_context.blocked_requires_attention is False
    assert promotion_context.linked_change_request_open is False
    assert len(control_plane.completed_calls) == 1
    completed_issue, completed_work_item = control_plane.completed_calls[0]
    assert completed_issue.source_ref == "AX123"
    assert completed_work_item is not None
    assert completed_work_item.work_item_id == "work-1"
    assert branch_names[0].endswith("/attempt-2")


def test_runner_materializes_before_context_failure_on_live_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_state_service, state = build_run_state_service(tmp_path)
    record = run_state_service.start_run("run-1")
    control_plane = StubRemediationControlPlane()
    selected_item = build_selected_item()
    work_item = build_work_item()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": work_item,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder."
        "RemediationContextBuilder.build",
        lambda self, item: None,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater."
        "DashboardRemediationUpdater.mark_failed",
        lambda self, **kwargs: type(
            "UpdateResult",
            (),
            {"dashboard_issue_url": None, "updated_item": selected_item, "error_message": None},
        )(),
    )

    summary = DashboardRemediationRunner(
        repo_root=tmp_path,
        config=build_config(),
        dashboard_service=cast(DashboardService, DummyDashboardService()),
        run_state_service=run_state_service,
        remediation_control_plane=control_plane,
    ).run(
        project_id="123",
        state=state,
        run_id="run-1",
        record=record,
        active_dry_run=False,
    )

    assert summary.status.value == "failed"
    assert "Context unavailable" in summary.message
    assert len(control_plane.calls) == 1
    assert len(control_plane.blocked_calls) == 1
    blocked_issue, blocked_work_item = control_plane.blocked_calls[0]
    assert blocked_issue.source_ref == "AX123"
    assert blocked_work_item is not None
    assert blocked_work_item.work_item_id == "work-1"


def test_runner_ignores_promotion_materialization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_state_service, state = build_run_state_service(tmp_path)
    record = run_state_service.start_run("run-1")
    control_plane = StubRemediationControlPlane(raise_on_materialize=True)
    selected_item = build_selected_item()
    work_item = build_work_item()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": work_item,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder."
        "RemediationContextBuilder.build",
        lambda self, item: IssueContext(
            issue_key=item.dashboard_item_id,
            file_path=item.file_path,
            line=item.line,
            file_size_bytes=12,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="42: value = value"),
            full_file_included=True,
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater."
        "DashboardRemediationUpdater.mark_in_progress",
        lambda self, **kwargs: type(
            "UpdateResult",
            (),
            {"dashboard_issue_url": None, "updated_item": selected_item, "error_message": None},
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        lambda self, selected_issue, context, dry_run, branch_name: type(
            "ExecutionResult",
            (),
            {
                "failure": None,
                "final_status": None,
                "status_message": "Remediation completed.",
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "change_request_url": None,
                "change_request_action": None,
            },
        )(),
    )

    summary = DashboardRemediationRunner(
        repo_root=tmp_path,
        config=build_config(),
        dashboard_service=cast(DashboardService, DummyDashboardService()),
        run_state_service=run_state_service,
        remediation_control_plane=control_plane,
    ).run(
        project_id="123",
        state=state,
        run_id="run-1",
        record=record,
        active_dry_run=False,
    )

    assert summary.status.value == "selected"
    assert len(control_plane.calls) == 1


def test_runner_blocks_promoted_work_item_when_dashboard_start_update_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_state_service, state = build_run_state_service(tmp_path)
    record = run_state_service.start_run("run-1")
    control_plane = StubRemediationControlPlane()
    selected_item = build_selected_item()
    work_item = build_work_item()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": work_item,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder."
        "RemediationContextBuilder.build",
        lambda self, item: IssueContext(
            issue_key=item.dashboard_item_id,
            file_path=item.file_path,
            line=item.line,
            file_size_bytes=12,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="42: value = value"),
            full_file_included=True,
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater."
        "DashboardRemediationUpdater.mark_in_progress",
        lambda self, **kwargs: type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": None,
                "updated_item": selected_item,
                "error_message": "dashboard write failed",
            },
        )(),
    )

    summary = DashboardRemediationRunner(
        repo_root=tmp_path,
        config=build_config(),
        dashboard_service=cast(DashboardService, DummyDashboardService()),
        run_state_service=run_state_service,
        remediation_control_plane=control_plane,
    ).run(
        project_id="123",
        state=state,
        run_id="run-1",
        record=record,
        active_dry_run=False,
    )

    assert summary.status.value == "failed"
    assert "Dashboard lifecycle update failed" in summary.message
    assert len(control_plane.calls) == 1
    assert len(control_plane.blocked_calls) == 1
    blocked_issue, blocked_work_item = control_plane.blocked_calls[0]
    assert blocked_issue.source_ref == "AX123"
    assert blocked_work_item is not None
    assert blocked_work_item.work_item_id == "work-1"


def test_runner_dismisses_promoted_work_item_when_execution_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_state_service, state = build_run_state_service(tmp_path)
    record = run_state_service.start_run("run-1")
    control_plane = StubRemediationControlPlane()
    selected_item = build_selected_item()
    work_item = build_work_item()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": work_item,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder."
        "RemediationContextBuilder.build",
        lambda self, item: IssueContext(
            issue_key=item.dashboard_item_id,
            file_path=item.file_path,
            line=item.line,
            file_size_bytes=12,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="42: value = value"),
            full_file_included=True,
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater."
        "DashboardRemediationUpdater.mark_in_progress",
        lambda self, **kwargs: type(
            "UpdateResult",
            (),
            {"dashboard_issue_url": None, "updated_item": selected_item, "error_message": None},
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater."
        "DashboardRemediationUpdater.mark_rejected",
        lambda self, **kwargs: type(
            "UpdateResult",
            (),
            {"dashboard_issue_url": None, "updated_item": selected_item, "error_message": None},
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        lambda self, selected_issue, context, dry_run, branch_name: type(
            "ExecutionResult",
            (),
            {
                "failure": None,
                "final_status": type("RunStatusValue", (), {"value": "rejected"})(),
                "status_message": "Manual remediation required.",
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "change_request_url": None,
                "change_request_action": None,
            },
        )(),
    )

    summary = DashboardRemediationRunner(
        repo_root=tmp_path,
        config=build_config(),
        dashboard_service=cast(DashboardService, DummyDashboardService()),
        run_state_service=run_state_service,
        remediation_control_plane=control_plane,
    ).run(
        project_id="123",
        state=state,
        run_id="run-1",
        record=record,
        active_dry_run=False,
    )

    assert summary.status.value == "rejected"
    assert "Manual remediation required." in summary.message
    assert len(control_plane.calls) == 1
    assert len(control_plane.blocked_calls) == 0
    assert len(control_plane.dismissed_calls) == 1
    dismissed_issue, dismissed_work_item = control_plane.dismissed_calls[0]
    assert dismissed_issue.source_ref == "AX123"
    assert dismissed_work_item is not None
    assert dismissed_work_item.work_item_id == "work-1"

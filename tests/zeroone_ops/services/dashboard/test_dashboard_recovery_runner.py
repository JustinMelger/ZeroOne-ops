"""Tests for GitLab dashboard recovery command workflow orchestration."""

from pathlib import Path
from typing import cast

from zeroone_ops.models.config import AppConfig, GitLabConfig, RemediationConfig, StateConfig
from zeroone_ops.models.dashboard import DashboardDocument
from zeroone_ops.models.state import AppState, RepositoryState, RunStatus
from zeroone_ops.services.dashboard.dashboard_recovery_runner import DashboardRecoveryRunner
from zeroone_ops.services.dashboard.dashboard_recovery_service import (
    DashboardRecoveryProcessResult,
    DashboardRecoveryService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore


class FakeRecoveryService:
    """Return a deterministic recovery outcome without provider transport."""

    def __init__(self, result: DashboardRecoveryProcessResult) -> None:
        self.result = result
        self.persist_values: list[bool] = []

    def process(
        self,
        *,
        project_id: str,
        run_id: str,
        persist: bool,
    ) -> DashboardRecoveryProcessResult:
        del project_id, run_id
        self.persist_values.append(persist)
        return self.result


def _run_state_service(tmp_path: Path) -> RunStateService:
    config = AppConfig(
        platform="gitlab",
        base_branch="main",
        remediation=RemediationConfig(target_branch="main"),
        gitlab=GitLabConfig(labels=[]),
        state=StateConfig(path=tmp_path / ".zeroone-ops-state.json"),
    )
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=None,
        sonarqube_project_key=None,
    )
    return RunStateService(
        config=config,
        state_store=state_store,
        state=AppState(repository=RepositoryState(base_branch="main")),
    )


def _result(*, accepted_command_count: int) -> DashboardRecoveryProcessResult:
    return DashboardRecoveryProcessResult(
        document=DashboardDocument(
            issue_id=1,
            issue_iid=2,
            issue_url="https://gitlab.example.com/group/project/-/issues/2",
            title="ZeroOne Ops dashboard",
            sections=[],
        ),
        note_count=2,
        authorized_note_count=1,
        matched_command_count=1,
        accepted_command_count=accepted_command_count,
        rejected_command_count=0,
    )


def test_runner_persists_accepted_ci_command(tmp_path: Path) -> None:
    """Accepted CI commands produce the shared synced summary."""
    run_state_service = _run_state_service(tmp_path)
    fake_service = FakeRecoveryService(_result(accepted_command_count=1))
    runner = DashboardRecoveryRunner(
        recovery_service=cast(DashboardRecoveryService, fake_service),
        run_state_service=run_state_service,
    )
    record = run_state_service.start_run("run-1")

    summary = runner.run(
        project_id="123",
        record=record,
        active_dry_run=False,
        execution_mode="ci",
    )

    assert summary.status == RunStatus.SYNCED
    assert fake_service.persist_values == [True]


def test_runner_rejects_live_local_execution(tmp_path: Path) -> None:
    """The command cannot mutate dashboard state from a local shell."""
    run_state_service = _run_state_service(tmp_path)
    fake_service = FakeRecoveryService(_result(accepted_command_count=1))
    runner = DashboardRecoveryRunner(
        recovery_service=cast(DashboardRecoveryService, fake_service),
        run_state_service=run_state_service,
    )
    record = run_state_service.start_run("run-1")

    summary = runner.run(
        project_id="123",
        record=record,
        active_dry_run=False,
        execution_mode="local",
    )

    assert summary.status == RunStatus.FAILED
    assert fake_service.persist_values == []

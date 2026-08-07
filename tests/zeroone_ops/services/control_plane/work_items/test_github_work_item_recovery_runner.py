"""Tests for GitHub recovery command workflow orchestration."""

from pathlib import Path
from typing import cast

from zeroone_ops.models.config import AppConfig, GitHubConfig, RemediationConfig, StateConfig
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.state import AppState, RepositoryState, RunStatus
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_runner import (
    GitHubWorkItemRecoveryRunner,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_service import (
    GitHubWorkItemRecoveryProcessResult,
    GitHubWorkItemRecoveryService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore


class FakeRecoveryService:
    """Return one deterministic recovery outcome without provider transport."""

    def __init__(self, result: GitHubWorkItemRecoveryProcessResult) -> None:
        self.result = result
        self.persist_values: list[bool] = []

    def process(
        self,
        *,
        repository_id: str,
        issue_number: int,
        policy_eligible: bool,
        persist: bool,
    ) -> GitHubWorkItemRecoveryProcessResult:
        del repository_id, issue_number, policy_eligible
        self.persist_values.append(persist)
        return self.result


def _run_state_service(tmp_path: Path) -> RunStateService:
    config = AppConfig(
        platform="github",
        base_branch="main",
        remediation=RemediationConfig(target_branch="main"),
        github=GitHubConfig(labels=[]),
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


def _result(*, accepted_command_count: int) -> GitHubWorkItemRecoveryProcessResult:
    work_item = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="dismissed",
        source=WorkItemSourceRef(
            source="ruff-sarif",
            source_item_key="src/service.py::C416",
            repository_scope="octo-org/octo-repo",
        ),
        summary="Use set() directly.",
    )
    return GitHubWorkItemRecoveryProcessResult(
        issue=GitHubIssueInfo(
            id=1,
            number=2,
            web_url="https://github.example.com/octo-org/octo-repo/issues/2",
            title=work_item.summary,
            body="machine state",
        ),
        work_item=work_item,
        comment_count=1,
        authorized_comment_count=1,
        matched_command_count=1,
        accepted_command_count=accepted_command_count,
        rejected_command_count=0,
    )


def test_runner_persists_accepted_ci_command(tmp_path: Path) -> None:
    """Accepted CI commands produce the shared synced summary."""
    run_state_service = _run_state_service(tmp_path)
    fake_service = FakeRecoveryService(_result(accepted_command_count=1))
    runner = GitHubWorkItemRecoveryRunner(
        recovery_service=cast("GitHubWorkItemRecoveryService", fake_service),
        run_state_service=run_state_service,
    )
    record = run_state_service.start_run("run-1")

    summary = runner.run(
        repository_id="octo-org/octo-repo",
        issue_number=2,
        policy_eligible=True,
        record=record,
        active_dry_run=False,
        execution_mode="ci",
    )

    assert summary.status == RunStatus.SYNCED
    assert summary.work_item_id == "work-1"
    assert fake_service.persist_values == [True]


def test_runner_rejects_live_local_execution(tmp_path: Path) -> None:
    """The command cannot mutate authoritative state from a local shell."""
    run_state_service = _run_state_service(tmp_path)
    fake_service = FakeRecoveryService(_result(accepted_command_count=1))
    runner = GitHubWorkItemRecoveryRunner(
        recovery_service=cast("GitHubWorkItemRecoveryService", fake_service),
        run_state_service=run_state_service,
    )
    record = run_state_service.start_run("run-1")

    summary = runner.run(
        repository_id="octo-org/octo-repo",
        issue_number=2,
        policy_eligible=True,
        record=record,
        active_dry_run=False,
        execution_mode="local",
    )

    assert summary.status == RunStatus.FAILED
    assert fake_service.persist_values == []

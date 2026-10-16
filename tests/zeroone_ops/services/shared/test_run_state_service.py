from pathlib import Path

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
    StateConfig,
)
from zeroone_ops.models.state import (
    AppState,
    FailureDetails,
    FailureStage,
    RepositoryState,
    RunStatus,
)
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore


def build_config(state_path: Path) -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            bootstrap_severities=["MAJOR"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main"),
        state=StateConfig(path=state_path),
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def test_mark_selected_updates_issue_state(tmp_path: Path) -> None:
    state_path = tmp_path / ".zeroone-ops-state.json"
    config = build_config(state_path)
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    service = RunStateService(config=config, state_store=store, state=build_state())

    record = service.start_run("run-1")
    attempt_count = service.mark_selected(record=record, issue_key="ISSUE-1")

    assert attempt_count == 0
    assert record.status == RunStatus.SELECTED
    assert record.issue_key == "ISSUE-1"
    assert service.state.active_issue_key == "ISSUE-1"
    assert service.state.issues["ISSUE-1"].status == "selected"


def test_fail_issue_persists_structured_failure(tmp_path: Path) -> None:
    state_path = tmp_path / ".zeroone-ops-state.json"
    config = build_config(state_path)
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    service = RunStateService(config=config, state_store=store, state=build_state())

    record = service.start_run("run-1")
    record.branch_name = "zeroone-ops/fix"
    failure = FailureDetails(
        stage=FailureStage.VALIDATION,
        message="Validation failed: pytest (exit code 1).",
        retry_count=1,
        failed_command="pytest",
        exit_code=1,
        stdout_excerpt="failed stdout",
        stderr_excerpt="failed stderr",
    )

    summary = service.fail_issue(
        record=record,
        issue_key="ISSUE-1",
        attempt_count=2,
        error_message=failure.message,
        failure=failure,
    )

    loaded = store.load()
    assert summary.status == RunStatus.FAILED
    assert summary.message == "[ci] Validation failed: pytest (exit code 1)."
    assert loaded.issues["ISSUE-1"].failure == failure
    assert loaded.runs[0].failure == failure


def test_build_summary_includes_change_request_action(tmp_path: Path) -> None:
    state_path = tmp_path / ".zeroone-ops-state.json"
    config = build_config(state_path)
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    service = RunStateService(config=config, state_store=store, state=build_state())

    summary = service.build_summary(
        run_id="run-1",
        status=RunStatus.CHANGE_REQUEST_CREATED,
        message="Published successfully.",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/9",
        change_request_action="reused",
    )

    assert (
        summary.message == "[ci] Published successfully. Change request reused: "
        "https://gitlab.example.com/group/project/-/merge_requests/9"
    )


def test_finish_work_item_persists_provider_neutral_reference(tmp_path: Path) -> None:
    state_path = tmp_path / ".zeroone-ops-state.json"
    config = build_config(state_path)
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    service = RunStateService(config=config, state_store=store, state=build_state())

    summary = service.finish_work_item(
        record=service.start_run("run-1"),
        work_item_id="github-work-1",
        status=RunStatus.CHANGE_REQUEST_CREATED,
        message="Published successfully.",
        change_request_url="https://github.example.com/octo-org/octo-repo/pull/9",
        change_request_action="created",
    )

    loaded = store.load()
    assert summary.work_item_id == "github-work-1"
    assert loaded.runs[0].work_item_id == "github-work-1"
    assert loaded.runs[0].status == RunStatus.CHANGE_REQUEST_CREATED


def test_reject_issue_persists_rejected_status(tmp_path: Path) -> None:
    state_path = tmp_path / ".zeroone-ops-state.json"
    config = build_config(state_path)
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    service = RunStateService(config=config, state_store=store, state=build_state())

    record = service.start_run("run-1")
    summary = service.reject_issue(
        record=record,
        issue_key="ISSUE-1",
        attempt_count=1,
        branch_name="zeroone-ops/fix",
        message="Local approval rejected the proposed change.",
    )

    loaded = store.load()
    assert summary.status == RunStatus.REJECTED
    assert loaded.issues["ISSUE-1"].status == "rejected"
    assert loaded.issues["ISSUE-1"].branch_name == "zeroone-ops/fix"

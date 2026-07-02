from pathlib import Path

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
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
        state={"path": state_path},
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
        status=RunStatus.MR_CREATED,
        message="Published successfully.",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/9",
        change_request_action="reused",
    )

    assert (
        summary.message == "[ci] Published successfully. Change request reused: "
        "https://gitlab.example.com/group/project/-/merge_requests/9"
    )


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


def test_mark_dashboard_selected_updates_dashboard_item_state(tmp_path: Path) -> None:
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
    service.dashboard.mark_selected(record=record, dashboard_item_id="sonar:1")
    service.dashboard.finish_success()

    loaded = store.load()
    assert record.dashboard_item_id == "sonar:1"
    assert loaded.dashboard_items["sonar:1"].status == "selected"
    assert loaded.dashboard_items["sonar:1"].last_run_id == "run-1"


def test_mark_dashboard_mr_created_persists_dashboard_item_state(tmp_path: Path) -> None:
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
    service.dashboard.mark_mr_created(
        record=record,
        dashboard_item_id="sonar:1",
        branch_name="zeroone-ops/ax123/service",
        mr_url="https://gitlab.example.com/group/project/-/merge_requests/1",
    )
    service.dashboard.finish_success()

    loaded = store.load()
    assert loaded.dashboard_items["sonar:1"].status == "mr_created"
    assert loaded.dashboard_items["sonar:1"].branch_name == "zeroone-ops/ax123/service"
    assert (
        loaded.dashboard_items["sonar:1"].mr_url
        == "https://gitlab.example.com/group/project/-/merge_requests/1"
    )


def test_mark_dashboard_done_persists_completed_dashboard_item_state(tmp_path: Path) -> None:
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
    service.dashboard.mark_done(
        record=record,
        dashboard_item_id="sonar:1",
        branch_name="zeroone-ops/ax123/service",
        commit_sha="abc123",
        mr_url="https://gitlab.example.com/group/project/-/merge_requests/1",
    )
    service.dashboard.finish_success()

    loaded = store.load()
    assert loaded.active_dashboard_item_id is None
    assert loaded.dashboard_items["sonar:1"].status == "done"
    assert loaded.dashboard_items["sonar:1"].branch_name == "zeroone-ops/ax123/service"
    assert loaded.dashboard_items["sonar:1"].commit_sha == "abc123"
    assert (
        loaded.dashboard_items["sonar:1"].mr_url
        == "https://gitlab.example.com/group/project/-/merge_requests/1"
    )


def test_mark_dashboard_reopened_persists_open_dashboard_item_state(tmp_path: Path) -> None:
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
    service.dashboard.mark_reopened(
        record=record,
        dashboard_item_id="sonar:1",
        branch_name="zeroone-ops/ax123/service",
        commit_sha="abc123",
        mr_url="https://gitlab.example.com/group/project/-/merge_requests/1",
    )
    service.dashboard.finish_success()

    loaded = store.load()
    assert loaded.active_dashboard_item_id is None
    assert loaded.dashboard_items["sonar:1"].status == "open"
    assert loaded.dashboard_items["sonar:1"].branch_name == "zeroone-ops/ax123/service"
    assert loaded.dashboard_items["sonar:1"].commit_sha == "abc123"


def test_fail_dashboard_item_summary_keeps_traceability_fields(tmp_path: Path) -> None:
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
    record.branch_name = "zeroone-ops/ax123/service"
    record.commit_sha = "abc123"
    record.mr_url = "https://gitlab.example.com/group/project/-/merge_requests/1"
    summary = service.dashboard.fail_item(
        record=record,
        dashboard_item_id="sonar:1",
        error_message="Validation failed.",
        failure=FailureDetails(
            stage=FailureStage.VALIDATION,
            message="Validation failed.",
        ),
    )

    assert summary.dashboard_item_id == "sonar:1"
    assert summary.branch_name == "zeroone-ops/ax123/service"
    assert summary.commit_sha == "abc123"
    assert summary.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/1"


def test_reject_dashboard_item_summary_keeps_traceability_fields(tmp_path: Path) -> None:
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
    record.commit_sha = "abc123"
    record.mr_url = "https://gitlab.example.com/group/project/-/merge_requests/1"
    summary = service.dashboard.reject_item(
        record=record,
        dashboard_item_id="sonar:1",
        branch_name="zeroone-ops/ax123/service",
        message="Local approval rejected the proposed change.",
    )

    assert summary.dashboard_item_id == "sonar:1"
    assert summary.branch_name == "zeroone-ops/ax123/service"
    assert summary.commit_sha == "abc123"
    assert summary.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/1"


def test_build_state_starts_with_no_remediation_exclusions() -> None:
    state = build_state()

    assert state.remediation_exclusions == []

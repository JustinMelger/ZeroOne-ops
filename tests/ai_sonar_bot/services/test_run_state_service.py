from pathlib import Path

from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.state import (
    AppState,
    FailureDetails,
    FailureStage,
    RepositoryState,
    RunStatus,
)
from ai_sonar_bot.services.run_state_service import RunStateService
from ai_sonar_bot.services.state_store import StateStore


def build_config(state_path: Path) -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        base_branch="main",
        supported_severities=["MAJOR"],
        supported_issue_types=["BUG"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        state={"path": state_path},
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def test_mark_selected_updates_issue_state(tmp_path: Path) -> None:
    state_path = tmp_path / ".ai-sonar-bot-state.json"
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
    state_path = tmp_path / ".ai-sonar-bot-state.json"
    config = build_config(state_path)
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    service = RunStateService(config=config, state_store=store, state=build_state())

    record = service.start_run("run-1")
    record.branch_name = "ai-sonar/fix"
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


def test_build_summary_includes_merge_request_action(tmp_path: Path) -> None:
    state_path = tmp_path / ".ai-sonar-bot-state.json"
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
        mr_url="https://gitlab.example.com/group/project/-/merge_requests/9",
        mr_action="reused",
    )

    assert (
        summary.message == "[ci] Published successfully. Merge request reused: "
        "https://gitlab.example.com/group/project/-/merge_requests/9"
    )


def test_reject_issue_persists_rejected_status(tmp_path: Path) -> None:
    state_path = tmp_path / ".ai-sonar-bot-state.json"
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
        branch_name="ai-sonar/fix",
        message="Local approval rejected the proposed change.",
    )

    loaded = store.load()
    assert summary.status == RunStatus.REJECTED
    assert loaded.issues["ISSUE-1"].status == "rejected"
    assert loaded.issues["ISSUE-1"].branch_name == "ai-sonar/fix"

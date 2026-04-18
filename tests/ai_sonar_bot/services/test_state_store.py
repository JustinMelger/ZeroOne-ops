from pathlib import Path

from ai_sonar_bot.models.state import (
    AppState,
    DashboardItemState,
    FailureDetails,
    FailureStage,
    IssueState,
    MergeRequestReviewState,
    PriorReviewFindingState,
    RepositoryState,
    RunRecord,
    RunStatus,
)
from ai_sonar_bot.services.state_store import StateStore


def test_state_store_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / ".ai-sonar-bot-state.json"
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )

    initial = store.load()
    assert isinstance(initial, AppState)

    initial.active_issue_key = "ABC"
    initial.active_dashboard_item_id = "sonar:1"
    initial.runs.append(
        RunRecord(
            run_id="run-1",
            status=RunStatus.FAILED,
            started_at="2026-03-29T10:00:00Z",
            updated_at="2026-03-29T10:01:00Z",
            error_message="Validation failed.",
            failure=FailureDetails(
                stage=FailureStage.VALIDATION,
                message="Validation failed.",
                failed_command="pytest",
                exit_code=1,
            ),
        )
    )
    initial.issues["ABC"] = IssueState(
        status="failed",
        last_run_id="run-1",
        attempt_count=1,
        last_error="Validation failed.",
        failure=FailureDetails(
            stage=FailureStage.VALIDATION,
            message="Validation failed.",
            failed_command="pytest",
            exit_code=1,
        ),
    )
    initial.dashboard_items["sonar:1"] = DashboardItemState(
        status="in_progress",
        last_run_id="run-3",
        branch_name="ai-sonar/sonar-1",
    )
    initial.reviews["17:abc123"] = MergeRequestReviewState(
        mr_iid=17,
        head_sha="abc123",
        status="findings_present",
        last_run_id="run-2",
        findings_count=1,
        summary="One finding.",
        findings=[
            PriorReviewFindingState(
                summary="src/service.py: Ordering regression",
                severity="medium",
                symbol="Service.run",
                issue_kind="ordering_regression",
                region_hint="return-order",
            )
        ],
        note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_5",
    )
    store.save(initial)

    loaded = store.load()
    assert loaded.active_issue_key == "ABC"
    assert loaded.active_dashboard_item_id == "sonar:1"
    assert loaded.repository == RepositoryState(
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    assert loaded.runs[0].failure == FailureDetails(
        stage=FailureStage.VALIDATION,
        message="Validation failed.",
        failed_command="pytest",
        exit_code=1,
    )
    assert loaded.issues["ABC"].failure == FailureDetails(
        stage=FailureStage.VALIDATION,
        message="Validation failed.",
        failed_command="pytest",
        exit_code=1,
    )
    assert loaded.dashboard_items["sonar:1"].status == "in_progress"
    assert loaded.dashboard_items["sonar:1"].last_run_id == "run-3"
    assert loaded.dashboard_items["sonar:1"].branch_name == "ai-sonar/sonar-1"
    assert loaded.reviews["17:abc123"].mr_iid == 17
    assert loaded.reviews["17:abc123"].head_sha == "abc123"
    assert loaded.reviews["17:abc123"].status == "findings_present"
    assert loaded.reviews["17:abc123"].last_run_id == "run-2"
    assert loaded.reviews["17:abc123"].findings_count == 1
    assert loaded.reviews["17:abc123"].summary == "One finding."
    assert loaded.reviews["17:abc123"].findings[0].summary == "src/service.py: Ordering regression"
    assert loaded.reviews["17:abc123"].findings[0].severity == "medium"
    assert loaded.reviews["17:abc123"].findings[0].symbol == "Service.run"
    assert loaded.reviews["17:abc123"].findings[0].issue_kind == "ordering_regression"
    assert loaded.reviews["17:abc123"].findings[0].region_hint == "return-order"
    assert (
        loaded.reviews["17:abc123"].note_url
        == "https://gitlab.example.com/group/project/-/merge_requests/17#note_5"
    )

from pathlib import Path

from ai_sonar_bot.models.state import (
    AppState,
    FailureDetails,
    FailureStage,
    IssueState,
    MergeRequestReviewState,
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
    initial.reviews["17:abc123"] = MergeRequestReviewState(
        mr_iid=17,
        head_sha="abc123",
        status="published",
        last_run_id="run-2",
        note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_5",
    )
    store.save(initial)

    loaded = store.load()
    assert loaded.active_issue_key == "ABC"
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
    assert loaded.reviews["17:abc123"].mr_iid == 17
    assert loaded.reviews["17:abc123"].head_sha == "abc123"
    assert loaded.reviews["17:abc123"].status == "published"
    assert loaded.reviews["17:abc123"].last_run_id == "run-2"
    assert (
        loaded.reviews["17:abc123"].note_url
        == "https://gitlab.example.com/group/project/-/merge_requests/17#note_5"
    )

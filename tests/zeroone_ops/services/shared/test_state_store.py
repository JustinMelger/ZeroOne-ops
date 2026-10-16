import json
from pathlib import Path

import pytest

from zeroone_ops.models.state import (
    AppState,
    ChangeRequestReviewState,
    FailureDetails,
    FailureStage,
    IssueState,
    PriorReviewFindingState,
    RepositoryState,
    RunRecord,
    RunStatus,
)
from zeroone_ops.services.shared.state_store import LegacyDashboardStateError, StateStore


def _store(path: Path) -> StateStore:
    return StateStore(path, base_branch="main", gitlab_project_id=None, sonarqube_project_key=None)


@pytest.mark.parametrize(
    "legacy",
    [
        {"dashboard_items": {"secret-id": {"content": "private evidence"}}},
        {"active_dashboard_item_id": "private evidence"},
        {"remediation_exclusions": [{"reason": "private evidence"}]},
        {"runs": [{"dashboard_item_id": "private evidence"}]},
    ],
)
def test_legacy_dashboard_history_requires_manual_cleanup_without_writes(tmp_path, legacy):
    path = tmp_path / "state.json"
    payload = {"repository": {"base_branch": "main"}, **legacy}
    content = json.dumps(payload)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LegacyDashboardStateError) as error:
        _store(path).load()
    assert str(path) in str(error.value)
    assert "Back up" in str(error.value)
    assert "docs/migration-v1.md" in str(error.value)
    assert "private evidence" not in str(error.value)
    assert "secret-id" not in str(error.value)
    assert path.read_text(encoding="utf-8") == content
    assert list(tmp_path.iterdir()) == [path]


def test_empty_dashboard_defaults_are_accepted_and_not_serialized(tmp_path):
    path = tmp_path / "state.json"
    payload = {
        "repository": {"base_branch": "main"},
        "dashboard_items": {},
        "active_dashboard_item_id": None,
        "remediation_exclusions": [],
        "runs": [
            {
                "run_id": "issue-run",
                "dashboard_item_id": None,
                "work_item_id": "work-1",
                "status": "failed",
                "started_at": "2026-10-01T12:00:00Z",
                "updated_at": "2026-10-01T12:00:00Z",
                "failure": {"stage": "dashboard_update", "message": "Issue update failed"},
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = _store(path)
    state = store.load()
    assert state.runs[0].failure.stage == FailureStage.CONTROL_PLANE_UPDATE
    store.save(state)
    serialized = json.loads(path.read_text(encoding="utf-8"))
    assert (
        not {"dashboard_items", "active_dashboard_item_id", "remediation_exclusions"}
        & serialized.keys()
    )
    assert "dashboard_item_id" not in serialized["runs"][0]
    assert serialized["runs"][0]["work_item_id"] == "work-1"
    assert serialized["runs"][0]["failure"]["stage"] == "control_plane_update"


def test_manual_cleanup_preserves_unrelated_runs_issues_and_review_continuity(tmp_path):
    path = tmp_path / "state.json"
    store = _store(path)
    clean = store.load()
    clean.reviews["17:abc123"] = ChangeRequestReviewState(
        change_request_number=17,
        head_sha="abc123",
        status="no_findings",
        last_run_id="review-1",
        findings_count=0,
        note_url="https://example/mr/17#note_1",
        projection_retry_pending=True,
    )
    clean.issues["issue-1"] = IssueState(status="failed", last_run_id="issue-run", attempt_count=1)
    clean.runs.append(
        RunRecord(
            run_id="issue-run",
            work_item_id="work-1",
            status=RunStatus.SYNCED,
            started_at="2026-10-01T12:00:00Z",
            updated_at="2026-10-01T12:00:00Z",
        )
    )
    payload = clean.model_dump(mode="json")
    payload["dashboard_items"] = {"old-id": {"status": "in_progress"}}
    payload["runs"].append({"dashboard_item_id": "old-id"})
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LegacyDashboardStateError):
        store.load()
    del payload["dashboard_items"]
    payload["runs"] = [run for run in payload["runs"] if run.get("dashboard_item_id") is None]
    path.write_text(json.dumps(payload), encoding="utf-8")
    restored = store.load()
    assert restored == clean
    store.save(restored)
    assert store.load().reviews["17:abc123"].projection_retry_pending is True


def test_state_store_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / ".zeroone-ops-state.json"
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
    initial.reviews["17:abc123"] = ChangeRequestReviewState(
        change_request_number=17,
        head_sha="abc123",
        status="findings_present",
        last_run_id="run-2",
        findings_count=1,
        summary="One finding.",
        findings=[
            PriorReviewFindingState(
                identity="src/service.py::ordering_regression::service-run::return-order",
                legacy_identity="src/service.py::order-regress",
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
    assert loaded.reviews["17:abc123"].change_request_number == 17
    assert loaded.reviews["17:abc123"].head_sha == "abc123"
    assert loaded.reviews["17:abc123"].status == "findings_present"
    assert loaded.reviews["17:abc123"].last_run_id == "run-2"
    assert loaded.reviews["17:abc123"].findings_count == 1
    assert loaded.reviews["17:abc123"].summary == "One finding."
    assert (
        loaded.reviews["17:abc123"].findings[0].identity
        == "src/service.py::ordering_regression::service-run::return-order"
    )
    assert loaded.reviews["17:abc123"].findings[0].legacy_identity == (
        "src/service.py::order-regress"
    )
    assert loaded.reviews["17:abc123"].findings[0].summary == "src/service.py: Ordering regression"
    assert loaded.reviews["17:abc123"].findings[0].severity == "medium"
    assert loaded.reviews["17:abc123"].findings[0].symbol == "Service.run"
    assert loaded.reviews["17:abc123"].findings[0].issue_kind == "ordering_regression"
    assert loaded.reviews["17:abc123"].findings[0].region_hint == "return-order"
    assert (
        loaded.reviews["17:abc123"].note_url
        == "https://gitlab.example.com/group/project/-/merge_requests/17#note_5"
    )


def test_state_store_load_migrates_legacy_review_state_identifier(tmp_path: Path) -> None:
    state_path = tmp_path / ".zeroone-ops-state.json"
    state_path.write_text(
        """
        {
          "version": 1,
          "repository": {
            "base_branch": "main",
            "gitlab_project_id": "123",
            "sonarqube_project_key": "project-key"
          },
          "reviews": {
            "17:abc123": {
              "mr_iid": 17,
              "head_sha": "abc123",
              "status": "no_findings",
              "last_run_id": "run-1",
              "findings_count": 0,
              "follow_up_lines": [],
              "findings": []
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )

    loaded = store.load()

    assert loaded.reviews["17:abc123"].change_request_number == 17
    assert loaded.reviews["17:abc123"].status == "no_findings"

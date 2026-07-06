from pathlib import Path

from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.state import AppState, DashboardItemState, RepositoryState
from zeroone_ops.services.dashboard.dashboard_item_selector import (
    DashboardItemSelector,
)


def build_item(
    *,
    item_id: str,
    status: str = "open",
    source: str = "sonarqube",
    item_type: str = "code_smell_fix",
    file_path: str | None = "src/service.py",
) -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source=source,
        type=item_type,
        status=status,
        title="Fix issue",
        summary="Fix the issue safely.",
        priority="low",
        source_reference="issue-1",
        file=file_path,
        line=10,
        rule="python:S1125",
        severity="LOW",
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def test_select_returns_first_supported_open_item(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    selector = DashboardItemSelector(repo_root=tmp_path)

    selected = selector.select([build_item(item_id="sonar:1")], build_state())

    assert selected is not None
    assert selected.id == "sonar:1"


def test_select_skips_items_with_active_local_dashboard_state(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = False\n", encoding="utf-8")
    selector = DashboardItemSelector(repo_root=tmp_path)
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        dashboard_items={"sonar:1": DashboardItemState(status="in_progress", last_run_id="run-1")},
    )

    selected = selector.select(
        [
            build_item(item_id="sonar:1"),
            build_item(item_id="sonar:2", file_path="src/other.py"),
        ],
        state,
    )

    assert selected is not None
    assert selected.id == "sonar:2"


def test_select_skips_items_with_legacy_change_request_state_in_local_state(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = False\n", encoding="utf-8")
    selector = DashboardItemSelector(repo_root=tmp_path)
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        dashboard_items={"sonar:1": DashboardItemState(status="mr_opened", last_run_id="run-1")},
    )

    selected = selector.select(
        [
            build_item(item_id="sonar:1"),
            build_item(item_id="sonar:2", file_path="src/other.py"),
        ],
        state,
    )

    assert selected is not None
    assert selected.id == "sonar:2"


def test_skip_reason_reports_unsupported_status(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    selector = DashboardItemSelector(repo_root=tmp_path)

    reason = selector.skip_reason(
        build_item(item_id="sonar:1", status="in_progress"),
        build_state(),
    )

    assert reason == "unsupported_status"


def test_skip_reason_reports_missing_local_file(tmp_path: Path) -> None:
    selector = DashboardItemSelector(repo_root=tmp_path)

    reason = selector.skip_reason(build_item(item_id="sonar:1"), build_state())

    assert reason == "missing_local_file"


def test_skip_reason_reports_retry_blocked_for_reviewed_item(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    selector = DashboardItemSelector(repo_root=tmp_path)

    reason = selector.skip_reason(
        build_item(item_id="sonar:1").model_copy(
            update={
                "review_status": "manual_review_only",
                "retry_eligible": False,
                "retry_block_reason": "Latest review outcome requires manual review.",
            }
        ),
        build_state(),
    )

    assert reason == "retry_blocked"

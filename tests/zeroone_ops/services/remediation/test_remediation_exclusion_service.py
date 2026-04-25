from pathlib import Path

from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.state import AppState, RepositoryState
from zeroone_ops.services.remediation.remediation_exclusion_service import (
    RemediationExclusionService,
)
from zeroone_ops.services.shared.state_store import StateStore


def build_service(tmp_path: Path) -> tuple[RemediationExclusionService, StateStore]:
    state_path = tmp_path / ".zeroone-ops-state.json"
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
    state = AppState(repository=RepositoryState(base_branch="main"))
    return RemediationExclusionService(state_store=store, state=state), store


def build_dashboard_item(
    *,
    source: str = "sonarqube",
    rule: str | None = "python:S3776",
    file_path: str | None = "src/routers/example.py",
) -> DashboardItem:
    return DashboardItem(
        id="sonar:1",
        source=source,
        type="code_smell_fix",
        status="open",
        title="Fix issue",
        summary="Fix the issue safely.",
        priority="medium",
        source_reference="AX123",
        file=file_path,
        line=10,
        rule=rule,
        severity="LOW",
    )


def test_add_exclusion_persists_new_record(tmp_path: Path) -> None:
    service, store = build_service(tmp_path)

    result = service.add_exclusion(
        source="sonarqube",
        issue_key="python:S3776",
        scope="src/routers/",
        reason="Usually requires broader refactor.",
        updated_by="operator",
    )

    loaded = store.load()
    assert result.created is True
    assert result.replaced is False
    assert len(loaded.remediation_exclusions) == 1
    assert loaded.remediation_exclusions[0].source == "sonarqube"
    assert loaded.remediation_exclusions[0].issue_key == "python:S3776"
    assert loaded.remediation_exclusions[0].scope == "src/routers/"
    assert loaded.remediation_exclusions[0].reason == "Usually requires broader refactor."
    assert loaded.remediation_exclusions[0].updated_by == "operator"


def test_add_exclusion_replaces_existing_record(tmp_path: Path) -> None:
    service, store = build_service(tmp_path)
    service.add_exclusion(
        source="sonarqube",
        issue_key="python:S3776",
        reason="old reason",
    )

    result = service.add_exclusion(
        source="sonarqube",
        issue_key="python:S3776",
        reason="new reason",
        updated_by="operator",
    )

    loaded = store.load()
    assert result.created is False
    assert result.replaced is True
    assert len(loaded.remediation_exclusions) == 1
    assert loaded.remediation_exclusions[0].reason == "new reason"
    assert loaded.remediation_exclusions[0].updated_by == "operator"


def test_remove_exclusion_persists_removal(tmp_path: Path) -> None:
    service, store = build_service(tmp_path)
    service.add_exclusion(
        source="pipeline_failure",
        issue_key="mypy:arg-type",
        reason="Needs broader change.",
    )

    result = service.remove_exclusion(
        source="pipeline_failure",
        issue_key="mypy:arg-type",
    )

    loaded = store.load()
    assert result.removed is True
    assert result.exclusion is not None
    assert loaded.remediation_exclusions == []


def test_list_exclusions_returns_stable_order(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    service.add_exclusion(source="pipeline_failure", issue_key="b", reason="two")
    service.add_exclusion(source="sonarqube", issue_key="a", reason="one")
    service.add_exclusion(source="pipeline_failure", issue_key="a", reason="three")

    exclusions = service.list_exclusions()

    assert [(item.source, item.issue_key) for item in exclusions] == [
        ("pipeline_failure", "a"),
        ("pipeline_failure", "b"),
        ("sonarqube", "a"),
    ]


def test_matches_dashboard_item_for_exact_source_and_issue_key(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    service.add_exclusion(
        source="sonarqube",
        issue_key="python:S3776",
        reason="Usually requires broader refactor.",
    )

    assert service.matches_dashboard_item(build_dashboard_item()) is True


def test_matches_dashboard_item_requires_scope_match_when_present(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    service.add_exclusion(
        source="sonarqube",
        issue_key="python:S3776",
        scope="src/routers",
        reason="Usually requires broader refactor.",
    )

    assert service.matches_dashboard_item(build_dashboard_item()) is True
    assert (
        service.matches_dashboard_item(build_dashboard_item(file_path="src/services/example.py"))
        is False
    )


def test_matches_dashboard_item_ignores_unsupported_source_mapping(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    service.add_exclusion(
        source="pipeline_failure",
        issue_key="mypy:arg-type",
        reason="Needs broader change.",
    )

    assert (
        service.matches_dashboard_item(build_dashboard_item(source="pipeline_failure", rule=None))
        is False
    )

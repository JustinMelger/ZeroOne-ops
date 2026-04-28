from pathlib import Path

from zeroone_ops.models.config import AppConfig, GitLabConfig, RemediationConfig
from zeroone_ops.models.dashboard import (
    DashboardIssueClassPolicyStateEntry,
    DashboardItem,
    DashboardPolicyState,
)
from zeroone_ops.models.state import AppState, RepositoryState
from zeroone_ops.services.dashboard.dashboard_policy_view_builder import (
    DashboardPolicyViewBuilder,
)


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        remediation=RemediationConfig(supported_severities=["low", "medium"]),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_item(
    *,
    item_id: str,
    rule: str,
    severity: str,
    file_path: str,
    status: str = "open",
) -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source="sonarqube",
        type="code_smell_fix",
        status=status,
        title="Title",
        summary="Summary",
        priority="low",
        source_reference=item_id,
        file=file_path,
        rule=rule,
        severity=severity,
        source_severity=severity,
        automation_severity=severity.lower(),
    )


def test_build_returns_read_only_policy_view_with_severity_exclusion_and_inventory(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    source_file = repo_root / "src" / "service.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("print('ok')\n")

    state = AppState(repository=RepositoryState(base_branch="main"))
    builder = DashboardPolicyViewBuilder(
        repo_root=repo_root,
        config=build_config(),
        state=state,
    )

    policy_view = builder.build(
        [
            build_item(
                item_id="sonar:excluded",
                rule="python:S3776",
                severity="HIGH",
                file_path="src/service.py",
            ),
            build_item(
                item_id="sonar:eligible",
                rule="python:S1125",
                severity="LOW",
                file_path="src/service.py",
            ),
        ],
        policy_state=DashboardPolicyState(
            issue_class_exclusions=[
                DashboardIssueClassPolicyStateEntry(
                    source="sonarqube",
                    issue_key="python:S3776",
                    reason="Excluded by dashboard policy action.",
                )
            ]
        ),
    )

    assert [row.severity for row in policy_view.severity_policy] == ["low", "medium", "high"]
    assert [row.enabled for row in policy_view.severity_policy] == [True, True, False]
    assert len(policy_view.excluded_issue_classes) == 1
    assert policy_view.excluded_issue_classes[0].issue_key == "python:S3776"
    assert policy_view.excluded_issue_classes[0].matching_items_count == 1

    inventory_by_key = {
        (row.source, row.issue_key): row for row in policy_view.issue_class_inventory
    }
    assert (
        inventory_by_key[("sonarqube", "python:S3776")].automation_status
        == "excluded from automation"
    )
    assert (
        inventory_by_key[("sonarqube", "python:S1125")].automation_status
        == "eligible for automation"
    )
    assert inventory_by_key[("sonarqube", "python:S3776")].severities_present == ["high"]
    assert inventory_by_key[("sonarqube", "python:S3776")].source_severities_present == ["HIGH"]


def test_resolve_policy_state_seeds_severity_policy_once_from_config(tmp_path: Path) -> None:
    builder = DashboardPolicyViewBuilder(
        repo_root=tmp_path,
        config=build_config(),
        state=AppState(repository=RepositoryState(base_branch="main")),
    )

    policy_state = builder.resolve_policy_state(DashboardPolicyState())

    assert [entry.severity for entry in policy_state.severity_policy] == ["low", "medium", "high"]
    assert [entry.enabled for entry in policy_state.severity_policy] == [True, True, False]


def test_resolve_policy_state_keeps_issue_class_exclusions_empty_without_dashboard_state(
    tmp_path: Path,
) -> None:
    builder = DashboardPolicyViewBuilder(
        repo_root=tmp_path,
        config=build_config(),
        state=AppState(repository=RepositoryState(base_branch="main")),
    )

    policy_state = builder.resolve_policy_state(DashboardPolicyState())

    assert policy_state.issue_class_exclusions == []


def test_resolve_policy_state_defaults_to_low_and_medium_when_config_is_empty(
    tmp_path: Path,
) -> None:
    builder = DashboardPolicyViewBuilder(
        repo_root=tmp_path,
        config=AppConfig(
            base_branch="main",
            remediation=RemediationConfig(supported_severities=[]),
            gitlab=GitLabConfig(target_branch="main"),
        ),
        state=AppState(repository=RepositoryState(base_branch="main")),
    )

    policy_state = builder.resolve_policy_state(DashboardPolicyState())

    assert [entry.severity for entry in policy_state.severity_policy] == ["low", "medium", "high"]
    assert [entry.enabled for entry in policy_state.severity_policy] == [True, True, False]

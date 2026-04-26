from pathlib import Path

from zeroone_ops.models.config import AppConfig, GitLabConfig, RemediationConfig
from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.state import AppState, RemediationExclusionState, RepositoryState
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
    )


def test_build_returns_read_only_policy_view_with_severity_exclusion_and_inventory(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    source_file = repo_root / "src" / "service.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("print('ok')\n")

    state = AppState(
        repository=RepositoryState(base_branch="main"),
        remediation_exclusions=[
            RemediationExclusionState(
                source="sonarqube",
                issue_key="python:S3776",
                reason="Usually needs refactor.",
            )
        ],
    )
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
        ]
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

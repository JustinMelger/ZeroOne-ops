import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardIssueClassPolicyStateEntry,
    DashboardItem,
    DashboardPolicyState,
    DashboardSection,
    DashboardSeverityPolicyStateEntry,
    empty_sections,
)
from zeroone_ops.models.gitlab import MergeRequestInfo
from zeroone_ops.models.state import (
    AppState,
    DashboardItemState,
    RemediationExclusionState,
    RepositoryState,
)
from zeroone_ops.services.dashboard.dashboard_item_intake import (
    DashboardItemIntakeService,
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


class FakeDashboardService:
    def __init__(self, document: DashboardDocument) -> None:
        self.document = document
        self.upserted_items: list[DashboardItem] = []

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        del project_id
        return self.document

    def upsert_items(self, *, project_id: str, items: list[DashboardItem]) -> DashboardDocument:
        del project_id
        self.upserted_items = items
        existing = self.document.items_by_id()
        for item in items:
            existing[item.id] = item
        self.document = build_document(items=list(existing.values()))
        return self.document


class FakeMergeRequestService:
    def __init__(self, branches_with_open_mr: set[str]) -> None:
        self.branches_with_open_mr = branches_with_open_mr

    def find_open(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ) -> MergeRequestInfo | None:
        del project_id, target_branch
        if source_branch not in self.branches_with_open_mr:
            return None
        return MergeRequestInfo(
            iid=1,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/1",
            title="fix: existing issue",
        )


def build_document(*, items: list[DashboardItem]) -> DashboardDocument:
    sections = empty_sections()
    sections[0] = DashboardSection(
        key="open_candidates",
        title="Open Candidates",
        items=items,
    )
    return DashboardDocument(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        sections=sections,
        policy_state=DashboardPolicyState(
            severity_policy=[
                DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
            ]
        ),
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def build_config(*, execution_mode: str = "ci") -> AppConfig:
    return AppConfig(
        execution_mode=execution_mode,
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            supported_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main"),
    )


def test_select_item_returns_first_supported_open_dashboard_item(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=FakeDashboardService(
            build_document(items=[build_item(item_id="sonar:1")])
        ),
    )

    result = service.select_item(project_id="123", state=build_state())

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:1"
    assert result.item_count == 1
    assert result.message == ""


def test_select_item_skips_active_local_dashboard_item_and_moves_to_next(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = False\n", encoding="utf-8")
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=FakeDashboardService(
            build_document(
                items=[
                    build_item(item_id="sonar:1"),
                    build_item(item_id="sonar:2", file_path="src/other.py"),
                ]
            )
        ),
    )
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        dashboard_items={"sonar:1": DashboardItemState(status="in_progress", last_run_id="run-1")},
    )

    result = service.select_item(project_id="123", state=state)

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:2"


def test_select_item_skips_item_with_existing_open_merge_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = False\n", encoding="utf-8")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        config=build_config(),
        dashboard_service=FakeDashboardService(
            build_document(
                items=[
                    build_item(item_id="sonar:1"),
                    build_item(item_id="sonar:2", file_path="src/other.py"),
                ]
            )
        ),
        merge_request_service=FakeMergeRequestService({"zeroone-ops/issue-1/service"}),
    )

    result = service.select_item(project_id="123", state=build_state())

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:2"


def test_select_item_recovers_stale_in_progress_item_before_selection(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item(
                    item_id="sonar:1",
                    status="in_progress",
                ).model_copy(
                    update={
                        "last_run_id": "run-1",
                        "status_updated_at": datetime.now(UTC) - timedelta(hours=25),
                    }
                )
            ]
        )
    )
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=dashboard_service,
    )

    result = service.select_item(project_id="123", state=build_state())

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:1"
    assert result.selected_item.status == "open"
    assert result.recovered_stale_item_ids == ("sonar:1",)
    assert dashboard_service.upserted_items[0].status == "open"
    assert "stale in_progress recovery" in (dashboard_service.upserted_items[0].log_excerpt or "")


def test_select_item_reports_skip_reasons_when_no_dashboard_item_is_eligible(
    tmp_path: Path,
    caplog,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=FakeDashboardService(
            build_document(
                items=[
                    build_item(item_id="sonar:1", status="in_progress"),
                    build_item(item_id="sonar:2", item_type="pipeline_fix"),
                ]
            )
        ),
    )
    caplog.set_level(logging.INFO)

    result = service.select_item(project_id="123", state=build_state())

    assert result.selected_item is None
    assert "unsupported type" in result.message
    assert "2 dashboard items" in result.message
    assert "unsupported status" in result.message
    assert "skipped dashboard remediation item during intake" in caplog.text


def test_select_item_skips_item_excluded_by_policy_and_moves_to_next(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = False\n", encoding="utf-8")
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=FakeDashboardService(
            build_document(
                items=[
                    build_item(item_id="sonar:1"),
                    build_item(item_id="sonar:2", file_path="src/other.py"),
                ]
            )
        ),
    )
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        remediation_exclusions=[
            RemediationExclusionState(
                source="sonarqube",
                issue_key="python:S1125",
                reason="Too noisy for automation.",
                scope="src/service.py",
            )
        ],
    )

    result = service.select_item(project_id="123", state=state)

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:2"


def test_select_item_skips_item_blocked_by_dashboard_severity_policy(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = False\n", encoding="utf-8")
    document = build_document(
        items=[
            build_item(item_id="sonar:1").model_copy(update={"automation_severity": "high"}),
            build_item(
                item_id="sonar:2",
                file_path="src/other.py",
            ).model_copy(update={"automation_severity": "low"}),
        ]
    ).model_copy(
        update={
            "policy_state": DashboardPolicyState(
                severity_policy=[
                    DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                    DashboardSeverityPolicyStateEntry(severity="medium", enabled=False),
                    DashboardSeverityPolicyStateEntry(severity="high", enabled=False),
                ]
            )
        }
    )
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=FakeDashboardService(document),
    )

    result = service.select_item(project_id="123", state=build_state())

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:2"


def test_select_item_reports_dashboard_issue_class_exclusion_when_no_item_is_eligible(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    document = build_document(
        items=[build_item(item_id="sonar:1")]
    ).model_copy(
        update={
            "policy_state": DashboardPolicyState(
                severity_policy=[
                    DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                    DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
                    DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
                ],
                issue_class_exclusions=[
                    DashboardIssueClassPolicyStateEntry(
                        source="sonarqube",
                        issue_key="python:S1125",
                        reason="Excluded by dashboard policy action.",
                    )
                ],
            )
        }
    )
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=FakeDashboardService(document),
    )

    result = service.select_item(project_id="123", state=build_state())

    assert result.selected_item is None
    assert "explicitly excluded from automation" in result.message


def test_select_item_reports_excluded_by_policy_when_no_dashboard_item_is_eligible(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        dashboard_service=FakeDashboardService(
            build_document(items=[build_item(item_id="sonar:1")])
        ),
    )
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        remediation_exclusions=[
            RemediationExclusionState(
                source="sonarqube",
                issue_key="python:S1125",
                reason="Too noisy for automation.",
            )
        ],
    )

    result = service.select_item(project_id="123", state=state)

    assert result.selected_item is None
    assert "explicitly excluded from automation" in result.message


def test_select_item_allows_reopened_item_with_cleared_merge_request_linkage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    service = DashboardItemIntakeService(
        repo_root=tmp_path,
        config=build_config(),
        dashboard_service=FakeDashboardService(
            build_document(
                items=[
                    build_item(item_id="sonar:1").model_copy(
                        update={
                            "branch_name": "zeroone-ops/issue-1/service",
                            "commit_sha": "abc123",
                            "merge_request_url": None,
                            "merge_request_iid": None,
                        }
                    )
                ]
            )
        ),
        merge_request_service=FakeMergeRequestService(set()),
    )

    result = service.select_item(project_id="123", state=build_state())

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:1"

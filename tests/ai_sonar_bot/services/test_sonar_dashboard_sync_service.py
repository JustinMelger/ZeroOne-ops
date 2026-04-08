from ai_sonar_bot.models.dashboard import DashboardDocument, DashboardItem, DashboardSection
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.sonar_dashboard_sync_service import SonarDashboardSyncService


class FakeDashboardDocument:
    def __init__(self, issue_url: str) -> None:
        self.issue_url = issue_url


class FakeDashboardService:
    def __init__(self, document: DashboardDocument | None = None) -> None:
        self.items = []
        self.document = document

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        assert project_id == "123"
        if self.document is None:
            self.document = DashboardDocument(
                issue_id=11,
                issue_iid=11,
                issue_url="https://gitlab.example.com/group/project/-/issues/11",
                title="AI Code Ops Dashboard",
                sections=[],
            )
        return self.document

    def upsert_items(self, *, project_id: str, items: list) -> FakeDashboardDocument:
        assert project_id == "123"
        self.items = items
        return FakeDashboardDocument("https://gitlab.example.com/group/project/-/issues/11")


def test_sync_normalizes_sonar_issues_into_dashboard_items() -> None:
    dashboard_service = FakeDashboardService()
    service = SonarDashboardSyncService(dashboard_service)

    result = service.sync(
        project_id="123",
        issues=[
            SonarIssue(
                key="AX123",
                rule="python:S1125",
                severity="LOW",
                type="CODE_SMELL",
                status="OPEN",
                message="Replace boolean equality with direct truthiness.",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=42,
            )
        ],
    )

    assert result.synced_count == 1
    assert result.dashboard_issue_url is not None
    assert dashboard_service.items[0].id == "sonar:AX123"
    assert dashboard_service.items[0].source == "sonarqube"
    assert dashboard_service.items[0].status == "open"
    assert dashboard_service.items[0].upstream_active is True
    assert dashboard_service.items[0].rule == "python:S1125"


def test_sync_preserves_existing_status_for_current_sonar_items() -> None:
    dashboard_service = FakeDashboardService(
        DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Dashboard",
            sections=[
                DashboardSection(
                    key="merge_requests_opened",
                    title="Merge Requests Opened",
                    items=[
                        DashboardItem(
                            id="sonar:AX123",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="mr_opened",
                            title="python:S1125 in src/service.py",
                            summary="Replace boolean equality with direct truthiness.",
                            priority="low",
                            source_reference="AX123",
                            file="src/service.py",
                            line=42,
                            rule="python:S1125",
                            severity="LOW",
                        )
                    ],
                )
            ],
        )
    )
    service = SonarDashboardSyncService(dashboard_service)

    service.sync(
        project_id="123",
        issues=[
            SonarIssue(
                key="AX123",
                rule="python:S1125",
                severity="LOW",
                type="CODE_SMELL",
                status="OPEN",
                message="Replace boolean equality with direct truthiness.",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=42,
            )
        ],
    )

    assert dashboard_service.items[0].status == "mr_opened"


def test_sync_marks_missing_active_sonar_items_done() -> None:
    dashboard_service = FakeDashboardService(
        DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Dashboard",
            sections=[
                DashboardSection(
                    key="open_candidates",
                    title="Open Candidates",
                    items=[
                        DashboardItem(
                            id="sonar:STALE",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="open",
                            title="python:S1125 in src/stale.py",
                            summary="Old issue.",
                            priority="low",
                            source_reference="STALE",
                            file="src/stale.py",
                            line=10,
                            rule="python:S1125",
                            severity="LOW",
                        )
                    ],
                )
            ],
        )
    )
    service = SonarDashboardSyncService(dashboard_service)

    service.sync(
        project_id="123",
        issues=[],
    )

    assert dashboard_service.items[0].id == "sonar:STALE"
    assert dashboard_service.items[0].status == "done"
    assert dashboard_service.items[0].upstream_active is False


def test_sync_preserves_missing_sonar_items_once_remediation_has_started() -> None:
    dashboard_service = FakeDashboardService(
        DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Dashboard",
            sections=[
                DashboardSection(
                    key="in_progress",
                    title="In Progress",
                    items=[
                        DashboardItem(
                            id="sonar:INPROGRESS",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="in_progress",
                            title="python:S1125 in src/in_progress.py",
                            summary="Still being remediated.",
                            priority="low",
                            source_reference="INPROGRESS",
                            file="src/in_progress.py",
                            line=10,
                            rule="python:S1125",
                            severity="LOW",
                            branch_name="ai-sonar/inprogress",
                            last_run_id="run-1",
                        )
                    ],
                ),
                DashboardSection(
                    key="merge_requests_opened",
                    title="Merge Requests Opened",
                    items=[
                        DashboardItem(
                            id="sonar:MROPENED",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="mr_opened",
                            title="python:S1125 in src/mr_opened.py",
                            summary="Awaiting merge.",
                            priority="low",
                            source_reference="MROPENED",
                            file="src/mr_opened.py",
                            line=10,
                            rule="python:S1125",
                            severity="LOW",
                            branch_name="ai-sonar/mr-opened",
                            last_run_id="run-2",
                            commit_sha="abc123",
                            merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/9",
                        )
                    ],
                ),
            ],
        )
    )
    service = SonarDashboardSyncService(dashboard_service)

    service.sync(
        project_id="123",
        issues=[],
    )

    items_by_id = {item.id: item for item in dashboard_service.items}
    assert items_by_id["sonar:INPROGRESS"].status == "in_progress"
    assert items_by_id["sonar:INPROGRESS"].last_run_id == "run-1"
    assert items_by_id["sonar:INPROGRESS"].upstream_active is False
    assert items_by_id["sonar:MROPENED"].status == "mr_opened"
    assert items_by_id["sonar:MROPENED"].merge_request_url is not None
    assert items_by_id["sonar:MROPENED"].upstream_active is False

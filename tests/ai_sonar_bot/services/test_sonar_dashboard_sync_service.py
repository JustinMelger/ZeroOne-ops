from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.sonar_dashboard_sync_service import SonarDashboardSyncService


class FakeDashboardDocument:
    def __init__(self, issue_url: str) -> None:
        self.issue_url = issue_url


class FakeDashboardService:
    def __init__(self) -> None:
        self.items = []

    def upsert_items(self, *, project_id: str, items: list) -> FakeDashboardDocument:
        assert project_id == "123"
        self.items = items
        return FakeDashboardDocument(
            "https://gitlab.example.com/group/project/-/issues/11"
        )


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
    assert dashboard_service.items[0].rule == "python:S1125"

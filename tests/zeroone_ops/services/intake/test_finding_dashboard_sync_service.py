from zeroone_ops.models.dashboard import DashboardDocument
from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.services.intake.finding_dashboard_sync_service import (
    FindingDashboardSyncService,
)


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
                title="AI Code Ops Work Queue",
                sections=[],
            )
        return self.document

    def upsert_items(self, *, project_id: str, items: list) -> FakeDashboardDocument:
        assert project_id == "123"
        self.items = items
        return FakeDashboardDocument("https://gitlab.example.com/group/project/-/issues/11")


def test_sync_normalizes_non_sonar_findings_into_dashboard_items() -> None:
    dashboard_service = FakeDashboardService()
    service = FindingDashboardSyncService(dashboard_service)

    result = service.sync(
        project_id="123",
        findings=[
            NormalizedFinding(
                finding_id="src/service.py::lint_fix::e712::line-42",
                source_id="ruff-sarif",
                severity="medium",
                title="Avoid equality comparisons to True",
                summary="Use direct truthiness instead of == True.",
                repository_path="src/service.py",
                line_start=42,
                line_end=42,
            )
        ],
    )

    assert result.synced_count == 1
    assert dashboard_service.items[0].id == "ruff-sarif:src/service.py::lint_fix::e712::line-42"
    assert dashboard_service.items[0].source == "ruff-sarif"
    assert dashboard_service.items[0].type == "static_analysis_fix"
    assert dashboard_service.items[0].priority == "medium"


def test_sync_with_no_findings_only_reconciles_explicitly_managed_sources() -> None:
    dashboard_service = FakeDashboardService(
        DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            sections=[],
        )
    )
    dashboard_service.document = DashboardDocument.model_validate(
        {
            "issue_id": 11,
            "issue_iid": 11,
            "issue_url": "https://gitlab.example.com/group/project/-/issues/11",
            "title": "AI Code Ops Work Queue",
            "sections": [
                {
                    "key": "open_candidates",
                    "title": "Open Candidates",
                    "items": [
                        {
                            "id": "ruff-sarif:src/service.py::e712",
                            "source": "ruff-sarif",
                            "type": "code_smell_fix",
                            "status": "open",
                            "title": "Avoid equality comparisons to True",
                            "summary": "Use direct truthiness instead of == True.",
                            "priority": "medium",
                            "source_reference": "src/service.py::e712",
                            "file": "src/service.py",
                            "line": 42,
                            "severity": "medium",
                        },
                        {
                            "id": "manual:123",
                            "source": "manual",
                            "type": "follow_up",
                            "status": "open",
                            "title": "Manual item",
                            "summary": "Do not touch this item.",
                            "priority": "low",
                            "source_reference": "manual:123",
                            "file": "docs/note.md",
                            "severity": "low",
                        },
                    ],
                }
            ],
        }
    )
    service = FindingDashboardSyncService(dashboard_service)

    service.sync(
        project_id="123",
        findings=[],
        managed_source_ids={"ruff-sarif"},
    )

    assert len(dashboard_service.items) == 1
    assert dashboard_service.items[0].id == "ruff-sarif:src/service.py::e712"
    assert dashboard_service.items[0].status == "done"
    assert dashboard_service.items[0].upstream_active is False

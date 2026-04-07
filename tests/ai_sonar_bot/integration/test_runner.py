import subprocess
from pathlib import Path

from ai_sonar_bot.models.analysis import (
    AnalysisClassification,
    CodeContextSnippet,
    IssueAnalysis,
    IssueContext,
    PatchProposal,
    StructuredEditProposal,
    TextEdit,
    ValidationResult,
)
from ai_sonar_bot.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    empty_sections,
)
from ai_sonar_bot.models.remediation import RemediationWorkItem
from ai_sonar_bot.models.review import (
    MergeRequestReviewCandidate,
    MergeRequestReviewContext,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import (
    AppState,
    FailureStage,
    MergeRequestReviewState,
    RepositoryState,
)
from ai_sonar_bot.runner import dashboard_remediate, review, run
from ai_sonar_bot.services.analysis_service import AnalysisResult
from ai_sonar_bot.services.branch_manager import BranchManagerError
from ai_sonar_bot.services.review_publisher import ReviewPublishResult
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.services.workspace_snapshot import WorkspaceSnapshotService


def test_run_dry_run_creates_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.delenv("SONARQUBE_URL", raising=False)
    monkeypatch.delenv("SONARQUBE_TOKEN", raising=False)
    monkeypatch.delenv("SONARQUBE_PROJECT_KEY", raising=False)
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "supported_rules": ["python:S2259"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = run(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "SonarQube credentials not configured" in summary.message


def test_dashboard_remediate_dry_run_returns_no_issue_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": None,
                "item_count": 0,
                "message": "No remediation-ready dashboard item found.",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    summary = dashboard_remediate(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "No remediation-ready dashboard item found." in summary.message


def test_dashboard_remediate_live_run_requires_ci_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "local",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def unexpected_select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        raise AssertionError("dashboard intake should not run for live local mode")

    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        unexpected_select_item,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]

    assert summary.status.value == "failed"
    assert "only supported in CI mode" in summary.message
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.ISSUE_INTAKE


def test_dashboard_remediate_ci_success_marks_dashboard_mr_opened(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.remediation_context_builder.RemediationContextBuilder.build",
        lambda self, work_item: IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        ),
    )
    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(self, *, project_id: str, dashboard_item_id: str, run_id: str):
        del project_id, run_id
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_mr_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        merge_request_url: str,
        commit_sha: str,
        merge_request_iid: int | None = None,
    ):
        del project_id, run_id, branch_name, merge_request_url, commit_sha, merge_request_iid
        recorded_updates.append(("mr_opened", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_mr_opened",
        mark_mr_opened,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.ExecutionService.execute_with_context",
        lambda self, selected_issue, context, dry_run: type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "ai-sonar/ax123/service",
                "commit_sha": "abc123",
                "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "mr_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )(),
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "mr_created"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "ai-sonar/ax123/service"
    assert summary.commit_sha == "abc123"
    assert (
        summary.mr_url
        == "https://gitlab.example.com/group/project/-/merge_requests/1"
    )
    assert "Selected dashboard item sonar:AX123 in src/service.py" in summary.message
    assert "Merge request created:" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("mr_opened", "sonar:AX123")]


def test_dashboard_remediate_fails_when_mr_opened_update_cannot_persist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    def mark_in_progress(self, *, project_id: str, dashboard_item_id: str, run_id: str):
        del self, project_id, dashboard_item_id, run_id
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_mr_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        merge_request_url: str,
        commit_sha: str,
        merge_request_iid: int | None = None,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            branch_name,
            merge_request_url,
            commit_sha,
            merge_request_iid,
        )
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": None,
                "updated_item": None,
                "error_message": "Dashboard remediation update failed: write conflict",
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "ai-sonar/ax123/service",
                "commit_sha": "abc123",
                "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "mr_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_mr_opened",
        mark_mr_opened,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]

    assert summary.status.value == "failed"
    assert "Dashboard lifecycle update failed" in summary.message
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.DASHBOARD_UPDATE
    assert last_run.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/1"


def test_dashboard_remediate_fails_when_failed_update_cannot_persist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    def mark_in_progress(self, *, project_id: str, dashboard_item_id: str, run_id: str):
        del self, project_id, dashboard_item_id, run_id
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
    ):
        del self, project_id, dashboard_item_id, run_id, error_message
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": None,
                "updated_item": None,
                "error_message": "Dashboard remediation update failed: write conflict",
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch failed in run.",
                "failure": type(
                    "Failure",
                    (),
                    {"stage": FailureStage.COMMIT, "message": "Commit failed: git commit failed"},
                )(),
                "branch_name": "ai-sonar/ax123/service",
                "commit_sha": None,
                "mr_url": None,
                "mr_action": None,
                "publish_attempted": False,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]

    assert summary.status.value == "failed"
    assert "Commit failed: git commit failed" in summary.message
    assert "Dashboard lifecycle update failed" in summary.message
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.DASHBOARD_UPDATE


def test_dashboard_remediate_ci_failure_marks_dashboard_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(self, *, project_id: str, dashboard_item_id: str, run_id: str):
        del self, project_id, run_id
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
    ):
        del self, project_id, run_id, error_message
        recorded_updates.append(("failed", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch failed in run.",
                "failure": type(
                    "Failure",
                    (),
                    {"stage": FailureStage.COMMIT, "message": "Commit failed: git commit failed"},
                )(),
                "branch_name": "ai-sonar/ax123/service",
                "commit_sha": None,
                "mr_url": None,
                "mr_action": None,
                "publish_attempted": False,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "failed"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "ai-sonar/ax123/service"
    assert "Commit failed: git commit failed" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("failed", "sonar:AX123")]


def test_dashboard_remediate_ci_rejection_marks_dashboard_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(self, *, project_id: str, dashboard_item_id: str, run_id: str):
        del self, project_id, run_id
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_rejected(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        rejection_reason: str,
    ):
        del self, project_id, run_id, rejection_reason
        recorded_updates.append(("rejected", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Local approval rejected the proposed change.",
                "failure": None,
                "branch_name": "ai-sonar/ax123/service",
                "commit_sha": None,
                "mr_url": None,
                "mr_action": None,
                "publish_attempted": False,
                "final_status": type("FinalStatus", (), {"value": "rejected"})(),
            },
        )()

    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_rejected",
        mark_rejected,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "rejected"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "ai-sonar/ax123/service"
    assert "Local approval rejected the proposed change." in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("rejected", "sonar:AX123")]


def test_dashboard_remediate_ci_commit_failure_restores_workspace_and_failed_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    target_file = tmp_path / "src" / "service.py"
    target_file.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(self, *, project_id: str, dashboard_item_id: str, run_id: str):
        del self, project_id, run_id
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
    ):
        del self, project_id, run_id, error_message
        recorded_updates.append(("failed", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.branch_manager.BranchManager.ensure_ready",
        lambda self: None,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.branch_manager.BranchManager.build_branch_name",
        lambda self, *, branch_prefix, issue_key, file_path: "ai-sonar/ax123/service",
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.branch_manager.BranchManager.create_branch",
        lambda self, branch_name: None,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.branch_manager.BranchManager.reset_index",
        lambda self: None,
    )

    snapshot = WorkspaceSnapshotService(tmp_path).capture(["src/service.py"])

    def analyze_issue_with_context(self, *, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=PatchProposal(
                issue_key="sonar:AX123",
                files_touched=["src/service.py"],
                unified_diff="diff --git a/src/service.py b/src/service.py\n",
                commit_message="fix(sonar): patch service [AX123]",
                mr_title="fix: patch service",
                mr_description="summary",
            ),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
            workspace_snapshot=snapshot,
        )

    def commit_and_push(self, commit_message: str, *, push: bool = False) -> str:
        del self, commit_message, push
        target_file.write_text("value = 2\n", encoding="utf-8")
        raise BranchManagerError("git commit failed")

    monkeypatch.setattr(
        "ai_sonar_bot.services.analysis_service.AnalysisService.analyze_issue_with_context",
        analyze_issue_with_context,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.branch_manager.BranchManager.commit_and_push",
        commit_and_push,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]
    dashboard_state = state.dashboard_items["sonar:AX123"]

    assert summary.status.value == "failed"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "ai-sonar/ax123/service"
    assert summary.commit_sha is None
    assert summary.mr_url is None
    assert "Commit failed: git commit failed" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("failed", "sonar:AX123")]
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"
    assert state.active_dashboard_item_id is None
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.COMMIT
    assert dashboard_state.status == "failed"
    assert dashboard_state.last_run_id == last_run.run_id
    assert dashboard_state.branch_name == "ai-sonar/ax123/service"
    assert dashboard_state.commit_sha is None
    assert dashboard_state.mr_url is None
    assert dashboard_state.last_error == "Commit failed: git commit failed"


def test_review_dry_run_creates_review_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = MergeRequestReviewCandidate(
        iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = MergeRequestReviewContext(
        mr_iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "ai_sonar_bot.services.mr_intake.MergeRequestIntakeService.select_merge_request",
        lambda self, state: type(
            "Result",
            (),
            {
                "selected_merge_request": merge_request,
                "merge_request_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_context_builder.ReviewContextBuilder.build",
        lambda self, merge_request, project_id: type(
            "ContextResult",
            (),
            {
                "context": review_context,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_analysis_service.ReviewAnalysisService.analyze",
        lambda self, context: type(
            "AnalysisResult",
            (),
            {
                "review_result": ReviewResult(
                    classification="no_findings",
                    summary="No findings.",
                    findings=[],
                ),
                "message": "Review classification: no_findings. Summary: No findings.",
            },
        )(),
    )

    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "Reviewed merge request !17 at abc123." in summary.message
    assert "Dry-run skipped note publication." in summary.message


def test_review_non_dry_run_publishes_findings_and_persists_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = MergeRequestReviewCandidate(
        iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = MergeRequestReviewContext(
        mr_iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "ai_sonar_bot.services.mr_intake.MergeRequestIntakeService.select_merge_request",
        lambda self, state: type(
            "Result",
            (),
            {
                "selected_merge_request": merge_request,
                "merge_request_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_context_builder.ReviewContextBuilder.build",
        lambda self, merge_request, project_id: type(
            "ContextResult",
            (),
            {
                "context": review_context,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_analysis_service.ReviewAnalysisService.analyze",
        lambda self, context: type(
            "AnalysisResult",
            (),
            {
                "review_result": ReviewResult(
                    classification="findings_present",
                    summary="One medium-risk finding.",
                    findings=[
                        ReviewFinding(
                            severity="medium",
                            file_path="src/service.py",
                            title="Missing test coverage",
                            explanation="The change alters behavior without test updates.",
                            suggested_follow_up="Add a regression test.",
                        )
                    ],
                ),
                "message": (
                    "Review classification: findings_present. Summary: One medium-risk finding."
                ),
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_publisher.ReviewPublisher.publish",
        lambda self, project_id, merge_request_iid, context, review_result: ReviewPublishResult(
            note=type(
                "Note",
                (),
                {
                    "id": 55,
                    "web_url": (
                        "https://gitlab.example.com/group/project/-/merge_requests/17#note_55"
                    ),
                },
            )(),
            body="summary",
        ),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_dashboard_updater.ReviewDashboardUpdater.update",
        lambda self, project_id, merge_request, review_result: type(
            "DashboardResult",
            (),
            {
                "dashboard_issue_url": ("https://gitlab.example.com/group/project/-/issues/11"),
                "error_message": None,
            },
        )(),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert "Reviewed merge request !17 at abc123." in summary.message
    assert (
        "Review note: https://gitlab.example.com/group/project/-/merge_requests/17#note_55"
        in summary.message
    )
    state = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    assert state.reviews["17:abc123"].status == "findings_present"


def test_review_non_dry_run_succeeds_when_dashboard_mirror_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = MergeRequestReviewCandidate(
        iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = MergeRequestReviewContext(
        mr_iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "ai_sonar_bot.services.mr_intake.MergeRequestIntakeService.select_merge_request",
        lambda self, state: type(
            "Result",
            (),
            {
                "selected_merge_request": merge_request,
                "merge_request_count": 1,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_context_builder.ReviewContextBuilder.build",
        lambda self, merge_request, project_id: type(
            "ContextResult",
            (),
            {
                "context": review_context,
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_analysis_service.ReviewAnalysisService.analyze",
        lambda self, context: type(
            "AnalysisResult",
            (),
            {
                "review_result": ReviewResult(
                    classification="no_findings",
                    summary="No findings.",
                    findings=[],
                ),
                "message": "Review classification: no_findings. Summary: No findings.",
            },
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_publisher.ReviewPublisher.publish",
        lambda self, project_id, merge_request_iid, context, review_result: ReviewPublishResult(
            note=type("Note", (), {"id": 55, "web_url": None})(),
            body="summary",
        ),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.review_dashboard_updater.ReviewDashboardUpdater.update",
        lambda self, project_id, merge_request, review_result: type(
            "DashboardResult",
            (),
            {
                "dashboard_issue_url": None,
                "error_message": "Dashboard mirror failed: boom",
            },
        )(),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert "Dashboard mirror failed: boom" in summary.message


def test_review_skips_unchanged_sha_revision_integration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    store = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    state = AppState(repository=RepositoryState(base_branch="main"))
    state.reviews["17:abc123"] = MergeRequestReviewState(
        mr_iid=17,
        head_sha="abc123",
        status="no_findings",
        last_run_id="run-1",
    )
    store.save(state)

    monkeypatch.setattr(
        "ai_sonar_bot.providers.gitlab_review_client.GitLabReviewClient.list_open_merge_requests",
        lambda self, project_id: [
            MergeRequestReviewCandidate(
                iid=17,
                title="feat: review flow",
                description="summary",
                source_branch="feature/review",
                target_branch="main",
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
                head_sha="abc123",
                changes=[],
            )
        ],
    )

    summary = review(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "already reviewed for their current head SHA" in summary.message


def test_run_selects_issue_with_existing_local_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = None\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "supported_rules": ["python:S2259"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def fake_search_open_issues(self) -> list[SonarIssue]:
        del self
        return [
            SonarIssue(
                key="AX12345",
                rule="python:S2259",
                severity="MAJOR",
                type="BUG",
                status="OPEN",
                message="Add a null check.",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=1,
            )
        ]

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        fake_search_open_issues,
    )

    summary = run(dry_run=True)

    assert summary.status.value == "selected"
    assert "AX12345" in summary.message
    assert "src/service.py" in summary.message


def test_run_dry_run_uses_fixture_when_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    fixture_dir = tmp_path / "fixtures" / "sonar"
    fixture_dir.mkdir(parents=True)
    llm_fixture_dir = tmp_path / "fixtures" / "llm"
    llm_fixture_dir.mkdir(parents=True)
    (fixture_dir / "issues.json").write_text(
        """
        {
          "issues": [
            {
              "key": "FIXTURE-1",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Fixture issue",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "analysis.json").write_text(
        """
        {
          "issue_key": "FIXTURE-1",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Add the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "edit.json").write_text(
        """
        {
          "issue_key": "FIXTURE-1",
          "edits": [
            {
              "file_path": "src/service.py",
              "search_text": "value = 1",
              "replace_text": "value = 2",
              "line_hint": 1
            }
          ],
          "commit_message": "fix(sonar): patch service [FIXTURE-1]",
          "mr_title": "fix: patch service",
          "mr_description": "summary"
        }
        """.strip(),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "mock_llm_analysis_path": "fixtures/llm/analysis.json",
          "mock_llm_edit_path": "fixtures/llm/edit.json",
          "mock_sonar_issues_path": "fixtures/sonar/issues.json",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "supported_rules": ["python:S2259"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = run(dry_run=True)

    assert summary.status.value == "selected"
    assert "FIXTURE-1" in summary.message
    assert "Analysis classification: auto_fixable" in summary.message
    assert "Proposed files: src/service.py" in summary.message
    assert "MR title: fix: patch service" in summary.message


def test_run_dry_run_can_apply_patch_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    fixture_dir = tmp_path / "fixtures" / "sonar"
    fixture_dir.mkdir(parents=True)
    llm_fixture_dir = tmp_path / "fixtures" / "llm"
    llm_fixture_dir.mkdir(parents=True)
    (fixture_dir / "issues.json").write_text(
        """
        {
          "issues": [
            {
              "key": "FIXTURE-2",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Fixture issue",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "analysis.json").write_text(
        """
        {
          "issue_key": "FIXTURE-2",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "edit.json").write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-2",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-2]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "apply_patch_in_dry_run": true,
          "mock_llm_analysis_path": "fixtures/llm/analysis.json",
          "mock_llm_edit_path": "fixtures/llm/edit.json",
          "mock_sonar_issues_path": "fixtures/sonar/issues.json",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "supported_rules": ["python:S2259"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = run(dry_run=True)

    assert summary.status.value == "selected"
    assert "Patch applied locally in dry-run" in summary.message
    assert (tmp_path / "src" / "service.py").read_text(encoding="utf-8") == "value = 2\n"


def test_run_dry_run_can_apply_bot_rendered_diff_from_structured_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "apply_patch_in_dry_run": true,
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "validation_commands": ["test \\"$(cat src/service.py)\\" = \\"value = 2\\""],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def fake_search_open_issues(self) -> list[SonarIssue]:
        del self
        return [
            SonarIssue(
                key="STRUCTURED-1",
                rule="python:S1125",
                severity="MAJOR",
                type="BUG",
                status="OPEN",
                message="Simplify boolean comparison.",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=1,
            )
        ]

    class StructuredEditLLMClient:
        def analyze_issue(self, issue: SonarIssue, context) -> IssueAnalysis:
            del issue, context
            return IssueAnalysis(
                issue_key="STRUCTURED-1",
                classification=AnalysisClassification.AUTO_FIXABLE,
                summary="Fixture analysis summary",
                risk_notes=[],
                target_files=["src/service.py"],
                proposed_strategy="Apply the minimal fix.",
            )

        def generate_structured_edit(
            self,
            issue: SonarIssue,
            context,
        ) -> StructuredEditProposal:
            del issue, context
            return StructuredEditProposal(
                issue_key="STRUCTURED-1",
                edits=[
                    TextEdit(
                        file_path="src/service.py",
                        search_text="value = 1",
                        replace_text="value = 2",
                        line_hint=1,
                    )
                ],
                commit_message="fix(sonar): patch service [STRUCTURED-1]",
                mr_title="fix: patch service",
                mr_description="summary",
            )

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        fake_search_open_issues,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.analysis_service.AnalysisService._build_llm_client",
        lambda self: StructuredEditLLMClient(),
    )

    summary = run(dry_run=True)

    assert summary.status.value == "selected"
    assert "Diff rendered by bot from structured edit proposal." in summary.message
    assert "Patch applied locally in dry-run" in summary.message
    assert (tmp_path / "src" / "service.py").read_text(encoding="utf-8") == "value = 2\n"


def test_run_non_dry_run_creates_branch_and_local_commit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.name", "AI Sonar Bot"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ai-sonar-bot@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "src").mkdir()
    tracked = tmp_path / "src" / "service.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/service.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    llm_fixture_dir = tmp_path / "fixtures" / "llm"
    llm_fixture_dir.mkdir(parents=True)
    (llm_fixture_dir / "analysis.json").write_text(
        """
        {
          "issue_key": "FIXTURE-3",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "edit.json").write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-3",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-3]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
            {
              "execution_mode": "local",
              "base_branch": "main",
              "branch_prefix": "ai-sonar",
              "mock_llm_analysis_path": "fixtures/llm/analysis.json",
              "mock_llm_edit_path": "fixtures/llm/edit.json",
              "supported_severities": ["MAJOR"],
              "supported_issue_types": ["BUG"],
              "supported_rules": ["python:S2259"],
              "validation_commands": ["test \\"$(cat src/service.py)\\" = \\"value = 2\\""],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def fake_search_open_issues(self) -> list[SonarIssue]:
        del self
        return [
            SonarIssue(
                key="FIXTURE-3",
                rule="python:S2259",
                severity="MAJOR",
                type="BUG",
                status="OPEN",
                message="Fixture issue",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=1,
            )
        ]

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        fake_search_open_issues,
    )
    subprocess.run(
        ["git", "add", ".ai-sonar-bot.json", "fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: add bot fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = run(dry_run=False)

    assert summary.status.value == "fix_generated"
    assert "All validation commands passed." in summary.message
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert current_branch == "ai-sonar/fixture-3/service"
    assert tracked.read_text(encoding="utf-8") == "value = 2\n"


def test_run_local_mode_rejects_when_approval_declines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.name", "AI Sonar Bot"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ai-sonar-bot@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "src").mkdir()
    tracked = tmp_path / "src" / "service.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/service.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    llm_fixture_dir = tmp_path / "fixtures" / "llm"
    llm_fixture_dir.mkdir(parents=True)
    (llm_fixture_dir / "analysis.json").write_text(
        """
        {
          "issue_key": "FIXTURE-6",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "edit.json").write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-6",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-6]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "execution_mode": "local",
          "base_branch": "main",
          "branch_prefix": "ai-sonar",
          "mock_llm_analysis_path": "fixtures/llm/analysis.json",
          "mock_llm_edit_path": "fixtures/llm/edit.json",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "supported_rules": ["python:S2259"],
          "validation_commands": ["test \\"$(cat src/service.py)\\" = \\"value = 2\\""],
          "gitlab": {
            "target_branch": "main",
            "labels": ["ai-sonar-bot"]
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def fake_search_open_issues(self) -> list[SonarIssue]:
        del self
        return [
            SonarIssue(
                key="FIXTURE-6",
                rule="python:S2259",
                severity="MAJOR",
                type="BUG",
                status="OPEN",
                message="Fixture issue",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=1,
            )
        ]

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        fake_search_open_issues,
    )
    subprocess.run(
        ["git", "add", ".ai-sonar-bot.json", "fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: add bot fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = run(dry_run=False)

    assert summary.status.value == "rejected"
    assert "Local approval rejected the proposed change." in summary.message
    assert tracked.read_text(encoding="utf-8") == "value = 1\n"


def test_run_ci_mode_pushes_branch_and_creates_merge_request(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    remote_repo = tmp_path.parent / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_repo)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AI Sonar Bot"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ai-sonar-bot@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "src").mkdir()
    tracked = tmp_path / "src" / "service.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/service.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "push",
            "-u",
            "origin",
            subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    llm_fixture_dir = tmp_path / "fixtures" / "llm"
    llm_fixture_dir.mkdir(parents=True)
    (llm_fixture_dir / "analysis.json").write_text(
        """
        {
          "issue_key": "FIXTURE-4",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "edit.json").write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-4",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-4]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "execution_mode": "ci",
          "base_branch": "main",
          "branch_prefix": "ai-sonar",
          "mock_llm_analysis_path": "fixtures/llm/analysis.json",
          "mock_llm_edit_path": "fixtures/llm/edit.json",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "supported_rules": ["python:S2259"],
          "validation_commands": ["test \\"$(cat src/service.py)\\" = \\"value = 2\\""],
          "gitlab": {
            "target_branch": "main",
            "labels": ["ai-sonar-bot"]
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def fake_search_open_issues(self) -> list[SonarIssue]:
        del self
        return [
            SonarIssue(
                key="FIXTURE-4",
                rule="python:S2259",
                severity="MAJOR",
                type="BUG",
                status="OPEN",
                message="Fixture issue",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=1,
            )
        ]

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        fake_search_open_issues,
    )

    def fake_find_open(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ):
        del self, project_id, source_branch, target_branch
        return None

    def fake_create(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str],
    ):
        del self, project_id, source_branch, target_branch, title, description, labels
        from ai_sonar_bot.models.gitlab import MergeRequestInfo

        return MergeRequestInfo(
            iid=9,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/9",
            title="fix: patch service",
        )

    monkeypatch.setattr(
        "ai_sonar_bot.services.mr_service.MergeRequestService.find_open",
        fake_find_open,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.mr_service.MergeRequestService.create",
        fake_create,
    )

    subprocess.run(
        ["git", "add", ".ai-sonar-bot.json", "fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: add bot fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = run(dry_run=False)

    assert summary.status.value == "mr_created"
    assert "Merge request created:" in summary.message
    assert "https://gitlab.example.com/group/project/-/merge_requests/9" in summary.message


def test_run_ci_mode_reuses_existing_merge_request(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    remote_repo = tmp_path.parent / "remote-reuse.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_repo)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AI Sonar Bot"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ai-sonar-bot@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "src").mkdir()
    tracked = tmp_path / "src" / "service.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/service.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "push",
            "-u",
            "origin",
            subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    llm_fixture_dir = tmp_path / "fixtures" / "llm"
    llm_fixture_dir.mkdir(parents=True)
    (llm_fixture_dir / "analysis.json").write_text(
        """
        {
          "issue_key": "FIXTURE-5",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    (llm_fixture_dir / "edit.json").write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-5",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-5]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "execution_mode": "ci",
          "base_branch": "main",
          "branch_prefix": "ai-sonar",
          "mock_llm_analysis_path": "fixtures/llm/analysis.json",
          "mock_llm_edit_path": "fixtures/llm/edit.json",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "supported_rules": ["python:S2259"],
          "validation_commands": ["test \\"$(cat src/service.py)\\" = \\"value = 2\\""],
          "gitlab": {
            "target_branch": "main",
            "labels": ["ai-sonar-bot"]
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def fake_search_open_issues(self) -> list[SonarIssue]:
        del self
        return [
            SonarIssue(
                key="FIXTURE-5",
                rule="python:S2259",
                severity="MAJOR",
                type="BUG",
                status="OPEN",
                message="Fixture issue",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=1,
            )
        ]

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        fake_search_open_issues,
    )

    def fake_find_open(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ):
        del self, project_id, source_branch, target_branch
        from ai_sonar_bot.models.gitlab import MergeRequestInfo

        return MergeRequestInfo(
            iid=11,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/11",
            title="fix: patch service",
        )

    def fail_create(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str],
    ):
        del self, project_id, source_branch, target_branch, title, description, labels
        raise AssertionError("create should not be called when an open merge request exists")

    monkeypatch.setattr(
        "ai_sonar_bot.services.mr_service.MergeRequestService.find_open",
        fake_find_open,
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.mr_service.MergeRequestService.create",
        fail_create,
    )

    subprocess.run(
        ["git", "add", ".ai-sonar-bot.json", "fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: add bot fixtures"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = run(dry_run=False)

    assert summary.status.value == "no_issue"
    assert "No eligible SonarQube issue found in 1 open issues." in summary.message
    assert "Skipped 1 with an open merge request." in summary.message

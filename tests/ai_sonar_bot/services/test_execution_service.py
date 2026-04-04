from pathlib import Path

from ai_sonar_bot.models.analysis import PatchProposal, ValidationResult
from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.gitlab import MergeRequestInfo
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.analysis_service import AnalysisResult
from ai_sonar_bot.services.execution_service import ExecutionService


def build_config(*, execution_mode: str = "local") -> AppConfig:
    return AppConfig(
        execution_mode=execution_mode,
        base_branch="main",
        supported_severities=["MAJOR"],
        supported_issue_types=["BUG"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main", labels=["ai-sonar-bot"]),
    )


def build_issue() -> SonarIssue:
    return SonarIssue(
        key="FIXTURE-1",
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


def build_patch() -> PatchProposal:
    return PatchProposal(
        issue_key="FIXTURE-1",
        files_touched=["src/service.py"],
        unified_diff="diff --git a/src/service.py b/src/service.py\n",
        commit_message="fix(sonar): patch service [FIXTURE-1]",
        mr_title="fix: patch service",
        mr_description="summary",
    )


def test_execute_returns_analysis_summary_in_dry_run(tmp_path: Path, monkeypatch) -> None:
    service = ExecutionService(tmp_path, build_config())

    def fake_analyze_issue(*, selected_issue: SonarIssue, dry_run: bool) -> AnalysisResult:
        del selected_issue
        assert dry_run is True
        return AnalysisResult(summary="Analysis ready.")

    monkeypatch.setattr(service.analysis_service, "analyze_issue", fake_analyze_issue)

    result = service.execute(selected_issue=build_issue(), dry_run=True)

    assert result.failure is None
    assert result.branch_name is None
    assert result.commit_sha is None
    assert result.status_message == "Analysis ready."


def test_execute_returns_commit_failure_details(tmp_path: Path, monkeypatch) -> None:
    service = ExecutionService(tmp_path, build_config(execution_mode="local"))

    monkeypatch.setattr(service.branch_manager, "ensure_ready", lambda: None)
    monkeypatch.setattr(
        service.branch_manager,
        "build_branch_name",
        lambda *, branch_prefix, issue_key, file_path: "ai-sonar/fix",
    )
    monkeypatch.setattr(service.branch_manager, "create_branch", lambda branch_name: None)
    monkeypatch.setattr(
        service.analysis_service,
        "analyze_issue",
        lambda *, selected_issue, dry_run: AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=build_patch(),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
        ),
    )
    monkeypatch.setattr(
        service.approval_service,
        "request",
        lambda issue, changed_files, validation, commit_message, mr_title: True,
    )

    def fail_commit(commit_message: str, *, push: bool = False) -> str:
        del commit_message, push
        raise RuntimeError("should not be called")

    def commit_error(commit_message: str, *, push: bool = False) -> str:
        del commit_message, push
        from ai_sonar_bot.services.branch_manager import BranchManagerError

        raise BranchManagerError("git commit failed")

    monkeypatch.setattr(service.branch_manager, "commit_and_push", commit_error)
    monkeypatch.setattr(service.branch_manager, "push_current_branch", fail_commit)

    result = service.execute(selected_issue=build_issue(), dry_run=False)

    assert result.failure is not None
    assert result.failure.stage.value == "commit"
    assert result.status_message == "Commit failed: git commit failed"
    assert result.branch_name == "ai-sonar/fix"
    assert result.commit_sha is None


def test_execute_reuses_existing_merge_request_in_ci_mode(tmp_path: Path, monkeypatch) -> None:
    service = ExecutionService(tmp_path, build_config(execution_mode="ci"))

    monkeypatch.setattr(service.branch_manager, "ensure_ready", lambda: None)
    monkeypatch.setattr(
        service.branch_manager,
        "build_branch_name",
        lambda *, branch_prefix, issue_key, file_path: "ai-sonar/fix",
    )
    monkeypatch.setattr(service.branch_manager, "create_branch", lambda branch_name: None)
    monkeypatch.setattr(
        service.analysis_service,
        "analyze_issue",
        lambda *, selected_issue, dry_run: AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=build_patch(),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
        ),
    )
    monkeypatch.setattr(
        service.branch_manager,
        "commit_and_push",
        lambda commit_message, *, push=False: "abc123",
    )
    monkeypatch.setattr(service.branch_manager, "push_current_branch", lambda: "ai-sonar/fix")
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.load_gitlab_connection_config",
        lambda: type(
            "GitLabConfigStub",
            (),
            {"project_id": "123", "url": "https://gitlab.example.com", "token": "token"},
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.MergeRequestService.find_open",
        lambda self, project_id, source_branch, target_branch: MergeRequestInfo(
            iid=9,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/9",
            title="fix: patch service",
        ),
    )

    def fail_create(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str],
    ) -> MergeRequestInfo:
        del self, project_id, source_branch, target_branch, title, description, labels
        raise AssertionError("create should not be called when an MR already exists")

    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.MergeRequestService.create",
        fail_create,
    )

    result = service.execute(selected_issue=build_issue(), dry_run=False)

    assert result.failure is None
    assert result.branch_name == "ai-sonar/fix"
    assert result.commit_sha == "abc123"
    assert result.mr_action == "reused"
    assert result.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/9"
    assert result.publish_attempted is True


def test_execute_uses_deterministic_merge_request_description_in_ci_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = ExecutionService(tmp_path, build_config(execution_mode="ci"))

    monkeypatch.setattr(service.branch_manager, "ensure_ready", lambda: None)
    monkeypatch.setattr(
        service.branch_manager,
        "build_branch_name",
        lambda *, branch_prefix, issue_key, file_path: "ai-sonar/fix",
    )
    monkeypatch.setattr(service.branch_manager, "create_branch", lambda branch_name: None)
    monkeypatch.setattr(
        service.analysis_service,
        "analyze_issue",
        lambda *, selected_issue, dry_run: AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=build_patch(),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
        ),
    )
    monkeypatch.setattr(
        service.branch_manager,
        "commit_and_push",
        lambda commit_message, *, push=False: "abc123",
    )
    monkeypatch.setattr(service.branch_manager, "push_current_branch", lambda: "ai-sonar/fix")
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.load_gitlab_connection_config",
        lambda: type(
            "GitLabConfigStub",
            (),
            {"project_id": "123", "url": "https://gitlab.example.com", "token": "token"},
        )(),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.MergeRequestService.find_open",
        lambda self, project_id, source_branch, target_branch: None,
    )

    captured: dict[str, str] = {}

    def capture_create(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str],
    ) -> MergeRequestInfo:
        del self, project_id, source_branch, target_branch, title, labels
        captured["description"] = description
        return MergeRequestInfo(
            iid=10,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/10",
            title="fix: patch service",
        )

    monkeypatch.setattr(
        "ai_sonar_bot.services.execution_service.MergeRequestService.create",
        capture_create,
    )

    result = service.execute(selected_issue=build_issue(), dry_run=False)

    assert result.failure is None
    assert result.mr_action == "created"
    assert result.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/10"
    assert captured["description"] == "\n".join(
        [
            "## Summary",
            "summary",
            "",
            "## SonarQube",
            "- Issue key: `FIXTURE-1`",
            "- Rule: `python:S2259`",
            "- Severity: `MAJOR`",
            "- Type: `BUG`",
            "- File: `src/service.py`",
            "- Line: `1`",
            "- Message: Fixture issue",
            "",
            "## Validation",
            "- All validation commands passed.",
            "",
            "## Notes",
            "- Diff was rendered by the bot from a structured edit proposal.",
        ]
    )


def test_execute_returns_rejected_when_local_approval_declines(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = ExecutionService(tmp_path, build_config(execution_mode="local"))

    monkeypatch.setattr(service.branch_manager, "ensure_ready", lambda: None)
    monkeypatch.setattr(
        service.branch_manager,
        "build_branch_name",
        lambda *, branch_prefix, issue_key, file_path: "ai-sonar/fix",
    )
    monkeypatch.setattr(service.branch_manager, "create_branch", lambda branch_name: None)
    monkeypatch.setattr(
        service.analysis_service,
        "analyze_issue",
        lambda *, selected_issue, dry_run: AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=build_patch(),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
        ),
    )
    monkeypatch.setattr(
        service.approval_service,
        "request",
        lambda issue, changed_files, validation, commit_message, mr_title: False,
    )

    result = service.execute(selected_issue=build_issue(), dry_run=False)

    assert result.failure is None
    assert result.final_status == "rejected"
    assert result.status_message == "Local approval rejected the proposed change."
    assert result.commit_sha is None

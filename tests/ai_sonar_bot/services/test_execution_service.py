from pathlib import Path

from ai_sonar_bot.models.analysis import PatchProposal, ValidationResult
from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.remediation import RemediationExecutionTarget
from ai_sonar_bot.services.analysis_service import AnalysisResult
from ai_sonar_bot.services.execution_service import ExecutionService
from ai_sonar_bot.services.publish_service import PublishResult
from ai_sonar_bot.services.workspace_snapshot import WorkspaceSnapshotService


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


def build_issue() -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="FIXTURE-1",
        source_type="sonarqube",
        source_ref="FIXTURE-1",
        title="python:S2259 in src/service.py",
        status="OPEN",
        message="Fixture issue",
        file_path="src/service.py",
        line=1,
        rule_id="python:S2259",
        severity="MAJOR",
        issue_type="BUG",
        component="sample-project:src/service.py",
        project="sample-project",
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


def fake_branch_name(*, branch_prefix: str, issue_key: str, file_path: str) -> str:
    del branch_prefix, issue_key, file_path
    return "ai-sonar/fix"


def fake_create_branch(branch_name: str) -> None:
    del branch_name


def fake_noop() -> None:
    return None


def fake_analysis_result(
    *,
    selected_issue: RemediationExecutionTarget,
    dry_run: bool,
) -> AnalysisResult:
    del selected_issue, dry_run
    return AnalysisResult(
        summary="Patch applied locally in run. All validation commands passed.",
        patch=build_patch(),
        patch_applied=True,
        validation_passed=True,
        validation_result=ValidationResult(
            passed=True,
            results=[],
            summary="All validation commands passed.",
        ),
    )


def fake_publish_reused(**kwargs) -> PublishResult:
    del kwargs
    return PublishResult(
        branch_name="ai-sonar/fix",
        mr_url="https://gitlab.example.com/group/project/-/merge_requests/9",
        mr_action="reused",
    )


def fake_gitlab_config():
    return type(
        "GitLabConfigStub",
        (),
        {"project_id": "123", "url": "https://gitlab.example.com", "token": "token"},
    )()


def fake_find_open_none(self, project_id, source_branch, target_branch):
    del self, project_id, source_branch, target_branch
    return None


def test_execute_returns_analysis_summary_in_dry_run(tmp_path: Path, monkeypatch) -> None:
    service = ExecutionService(tmp_path, build_config())

    def fake_analyze_issue(
        *, selected_issue: RemediationExecutionTarget, dry_run: bool
    ) -> AnalysisResult:
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
    (tmp_path / "src").mkdir()
    target_file = tmp_path / "src" / "service.py"
    target_file.write_text("value = 1\n", encoding="utf-8")
    snapshot = WorkspaceSnapshotService(tmp_path).capture(["src/service.py"])

    monkeypatch.setattr(service.branch_manager, "ensure_ready", fake_noop)
    monkeypatch.setattr(service.branch_manager, "build_branch_name", fake_branch_name)
    monkeypatch.setattr(service.branch_manager, "create_branch", fake_create_branch)

    def fake_analyze_issue(
        *, selected_issue: RemediationExecutionTarget, dry_run: bool
    ) -> AnalysisResult:
        del selected_issue, dry_run
        return AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=build_patch(),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
            workspace_snapshot=snapshot,
        )

    monkeypatch.setattr(service.analysis_service, "analyze_issue", fake_analyze_issue)

    def approve_request(issue, changed_files, validation, commit_message, mr_title) -> bool:
        del issue, changed_files, validation, commit_message, mr_title
        return True

    monkeypatch.setattr(service.approval_service, "request", approve_request)

    def fail_commit(commit_message: str, *, push: bool = False) -> str:
        del commit_message, push
        raise RuntimeError("should not be called")

    def commit_error(commit_message: str, *, push: bool = False) -> str:
        del commit_message, push
        from ai_sonar_bot.services.branch_manager import BranchManagerError

        target_file.write_text("value = 2\n", encoding="utf-8")
        raise BranchManagerError("git commit failed")

    monkeypatch.setattr(service.branch_manager, "commit_and_push", commit_error)
    monkeypatch.setattr(service.branch_manager, "push_current_branch", fail_commit)
    monkeypatch.setattr(service.branch_manager, "reset_index", fake_noop)

    result = service.execute(selected_issue=build_issue(), dry_run=False)

    assert result.failure is not None
    assert result.failure.stage.value == "commit"
    assert result.status_message == "Commit failed: git commit failed"
    assert result.branch_name == "ai-sonar/fix"
    assert result.commit_sha is None
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"


def test_execute_reuses_existing_merge_request_in_ci_mode(tmp_path: Path, monkeypatch) -> None:
    service = ExecutionService(tmp_path, build_config(execution_mode="ci"))

    monkeypatch.setattr(service.branch_manager, "ensure_ready", fake_noop)
    monkeypatch.setattr(service.branch_manager, "build_branch_name", fake_branch_name)
    monkeypatch.setattr(service.branch_manager, "create_branch", fake_create_branch)
    monkeypatch.setattr(service.analysis_service, "analyze_issue", fake_analysis_result)

    def fake_commit(commit_message: str, *, push: bool = False) -> str:
        del commit_message, push
        return "abc123"

    monkeypatch.setattr(service.branch_manager, "commit_and_push", fake_commit)
    monkeypatch.setattr(
        service.publish_service,
        "publish",
        fake_publish_reused,
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

    monkeypatch.setattr(service.branch_manager, "ensure_ready", fake_noop)
    monkeypatch.setattr(service.branch_manager, "build_branch_name", fake_branch_name)
    monkeypatch.setattr(service.branch_manager, "create_branch", fake_create_branch)
    monkeypatch.setattr(service.analysis_service, "analyze_issue", fake_analysis_result)

    def fake_commit(commit_message: str, *, push: bool = False) -> str:
        del commit_message, push
        return "abc123"

    monkeypatch.setattr(service.branch_manager, "commit_and_push", fake_commit)
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "ai_sonar_bot.services.publish_service.load_gitlab_connection_config",
        fake_gitlab_config,
    )

    def fake_push_current_branch() -> str:
        return "ai-sonar/fix"

    monkeypatch.setattr(service.branch_manager, "push_current_branch", fake_push_current_branch)
    monkeypatch.setattr(
        "ai_sonar_bot.services.publish_service.MergeRequestService.find_open",
        fake_find_open_none,
    )

    def capture_create(self, project_id, source_branch, target_branch, title, description, labels):
        del self, project_id, source_branch, target_branch, title, labels
        captured["description"] = description
        from ai_sonar_bot.models.gitlab import MergeRequestInfo

        return MergeRequestInfo(
            iid=10,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/10",
            title="fix: patch service",
        )

    monkeypatch.setattr(
        "ai_sonar_bot.services.publish_service.MergeRequestService.create",
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
            "## Remediation Target",
            "- Source: `sonarqube`",
            "- Item reference: `FIXTURE-1`",
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
    (tmp_path / "src").mkdir()
    target_file = tmp_path / "src" / "service.py"
    target_file.write_text("value = 1\n", encoding="utf-8")
    snapshot = WorkspaceSnapshotService(tmp_path).capture(["src/service.py"])

    monkeypatch.setattr(service.branch_manager, "ensure_ready", fake_noop)
    monkeypatch.setattr(service.branch_manager, "build_branch_name", fake_branch_name)
    monkeypatch.setattr(service.branch_manager, "create_branch", fake_create_branch)

    def fake_analyze_issue(
        *, selected_issue: RemediationExecutionTarget, dry_run: bool
    ) -> AnalysisResult:
        del selected_issue, dry_run
        return AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=build_patch(),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
            workspace_snapshot=snapshot,
        )

    monkeypatch.setattr(service.analysis_service, "analyze_issue", fake_analyze_issue)

    def reject_approval(issue, changed_files, validation, commit_message, mr_title) -> bool:
        del issue, changed_files, validation, commit_message, mr_title
        target_file.write_text("value = 2\n", encoding="utf-8")
        return False

    monkeypatch.setattr(service.approval_service, "request", reject_approval)
    monkeypatch.setattr(service.branch_manager, "reset_index", fake_noop)

    result = service.execute(selected_issue=build_issue(), dry_run=False)

    assert result.failure is None
    assert result.final_status == "rejected"
    assert result.status_message == "Local approval rejected the proposed change."
    assert result.commit_sha is None
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"


def test_execute_returns_rejected_when_analysis_requires_manual_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = ExecutionService(tmp_path, build_config(execution_mode="ci"))

    monkeypatch.setattr(service.branch_manager, "ensure_ready", fake_noop)
    monkeypatch.setattr(service.branch_manager, "build_branch_name", fake_branch_name)
    monkeypatch.setattr(service.branch_manager, "create_branch", fake_create_branch)

    def fake_analyze_issue(
        *, selected_issue: RemediationExecutionTarget, dry_run: bool
    ) -> AnalysisResult:
        del selected_issue, dry_run
        return AnalysisResult(
            summary="Patch generation skipped because manual review is required.",
            patch=None,
            patch_applied=False,
            validation_passed=False,
        )

    monkeypatch.setattr(service.analysis_service, "analyze_issue", fake_analyze_issue)

    result = service.execute(selected_issue=build_issue(), dry_run=False)

    assert result.failure is None
    assert result.final_status == "rejected"
    assert result.status_message == "Patch generation skipped because manual review is required."
    assert result.commit_sha is None

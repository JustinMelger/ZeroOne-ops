from pathlib import Path

from ai_sonar_bot.models.analysis import CodeContextSnippet, IssueContext, PatchProposal
from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.remediation import RemediationExecutionTarget
from ai_sonar_bot.services.fix_generator import FixGenerator
from ai_sonar_bot.services.patch_applier import PatchApplier, PatchApplyError
from ai_sonar_bot.services.patch_execution_service import PatchExecutionService
from ai_sonar_bot.services.validator import Validator
from ai_sonar_bot.services.workspace_snapshot import WorkspaceSnapshotService


class StubFixGenerator(FixGenerator):
    def __init__(self) -> None:
        pass


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["LOW"],
        supported_issue_types=["BUG"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_issue() -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="AX1",
        source_type="sonarqube",
        source_ref="AX1",
        title="python:S1125 in src/service.py",
        status="OPEN",
        message="Issue",
        file_path="src/service.py",
        line=1,
        rule_id="python:S1125",
        severity="LOW",
        issue_type="BUG",
        component="component",
        project="project",
    )


def build_context() -> IssueContext:
    return IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=1,
        file_size_bytes=10,
        snippet=CodeContextSnippet(start_line=1, end_line=1, content="1: value = 1"),
        full_file_included=True,
        truncated=False,
    )


def build_patch() -> PatchProposal:
    return PatchProposal(
        issue_key="AX1",
        files_touched=["src/service.py"],
        unified_diff="diff --git a/src/service.py b/src/service.py\n",
        commit_message="fix(sonar): update service [AX1]",
        mr_title="fix: update service",
        mr_description="summary",
    )


def test_patch_execution_service_restores_files_on_patch_apply_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src").mkdir()
    target_file = tmp_path / "src" / "service.py"
    target_file.write_text("value = 1\n", encoding="utf-8")

    service = PatchExecutionService(
        config=build_config(),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )

    def partial_apply(proposal: PatchProposal) -> None:
        del proposal
        target_file.write_text("value = 2\n", encoding="utf-8")
        raise PatchApplyError("simulated partial apply failure")

    monkeypatch.setattr(service.patch_applier, "validate", lambda proposal: None)
    monkeypatch.setattr(service.patch_applier, "apply", partial_apply)

    result = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=lambda **kwargs: build_patch(),
    )

    assert result.failure is not None
    assert result.failure.stage.value == "patch_apply"
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"

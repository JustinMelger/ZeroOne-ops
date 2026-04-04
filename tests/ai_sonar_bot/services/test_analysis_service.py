import subprocess
from pathlib import Path
from typing import Literal

from ai_sonar_bot.models.analysis import (
    AnalysisClassification,
    IssueAnalysis,
    StructuredEditProposal,
    TextEdit,
)
from ai_sonar_bot.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
)
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.analysis_service import AnalysisService
from ai_sonar_bot.services.patch_applier import PatchApplyError


def build_config(
    *,
    mock_llm_analysis_path: Path | None = None,
    mock_llm_edit_path: Path | None = None,
    apply_patch_in_dry_run: bool = False,
    validation_commands: list[str] | None = None,
    max_retry_count: int = 1,
    execution_mode: Literal["local", "ci"] = "ci",
    write_solution_artifacts_in_ci: bool = False,
) -> AppConfig:
    return AppConfig(
        execution_mode=execution_mode,
        base_branch="main",
        supported_severities=["MAJOR"],
        supported_issue_types=["BUG"],
        validation_commands=validation_commands or [],
        analysis=AnalysisConfig(
            context_lines_before=1,
            context_lines_after=1,
            max_file_bytes=200_000,
        ),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        mock_llm_analysis_path=mock_llm_analysis_path,
        mock_llm_edit_path=mock_llm_edit_path,
        apply_patch_in_dry_run=apply_patch_in_dry_run,
        write_solution_artifacts_in_ci=write_solution_artifacts_in_ci,
        max_retry_count=max_retry_count,
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


def test_analyze_issue_returns_context_summary_when_no_llm_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")

    result = AnalysisService(tmp_path, build_config()).analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert "Context ready from lines" in result.summary


def test_analyze_issue_applies_patch_in_dry_run_from_fixture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    analysis_path = tmp_path / "analysis.json"
    edit_path = tmp_path / "edit.json"
    analysis_path.write_text(
        """
        {
          "issue_key": "FIXTURE-1",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    edit_path.write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-1",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-1]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )

    result = AnalysisService(
        tmp_path,
        build_config(
            mock_llm_analysis_path=analysis_path,
            mock_llm_edit_path=edit_path,
            apply_patch_in_dry_run=True,
        ),
    ).analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert "Patch applied locally in dry-run" in result.summary
    assert (tmp_path / "src" / "service.py").read_text(encoding="utf-8") == "value = 2\n"


def test_analyze_issue_runs_validation_after_patch_apply(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    analysis_path = tmp_path / "analysis.json"
    edit_path = tmp_path / "edit.json"
    analysis_path.write_text(
        """
        {
          "issue_key": "FIXTURE-1",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    edit_path.write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-1",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-1]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )

    result = AnalysisService(
        tmp_path,
        build_config(
            mock_llm_analysis_path=analysis_path,
            mock_llm_edit_path=edit_path,
            apply_patch_in_dry_run=True,
            validation_commands=['test "$(cat src/service.py)" = "value = 2"'],
        ),
    ).analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert "All validation commands passed." in result.summary


def test_analyze_issue_rolls_back_when_validation_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    analysis_path = tmp_path / "analysis.json"
    edit_path = tmp_path / "edit.json"
    analysis_path.write_text(
        """
        {
          "issue_key": "FIXTURE-1",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    edit_path.write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-1",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-1]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )

    result = AnalysisService(
        tmp_path,
        build_config(
            mock_llm_analysis_path=analysis_path,
            mock_llm_edit_path=edit_path,
            apply_patch_in_dry_run=True,
            validation_commands=["false"],
            max_retry_count=1,
        ),
    ).analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert "Validation failed: false" in result.summary
    assert "Retry attempts exhausted." in result.summary
    assert result.failure is not None
    assert result.failure.stage.value == "validation"
    assert result.failure.failed_command == "false"
    assert result.failure.exit_code == 1
    assert (tmp_path / "src" / "service.py").read_text(encoding="utf-8") == "value = 1\n"


def test_analyze_issue_rolls_back_when_patch_apply_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    target_file = tmp_path / "src" / "service.py"
    target_file.write_text("value = 1\n", encoding="utf-8")
    analysis_path = tmp_path / "analysis.json"
    edit_path = tmp_path / "edit.json"
    analysis_path.write_text(
        """
        {
          "issue_key": "FIXTURE-1",
          "classification": "auto_fixable",
          "summary": "Fixture analysis summary",
          "risk_notes": [],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Apply the minimal fix."
        }
        """.strip(),
        encoding="utf-8",
    )
    edit_path.write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-1",\n'
            '  "edits": [\n'
            "    {\n"
            '      "file_path": "src/service.py",\n'
            '      "search_text": "value = 1",\n'
            '      "replace_text": "value = 2",\n'
            '      "line_hint": 1\n'
            "    }\n"
            "  ],\n"
            '  "commit_message": "fix(sonar): patch service [FIXTURE-1]",\n'
            '  "mr_title": "fix: patch service",\n'
            '  "mr_description": "summary"\n'
            "}"
        ),
        encoding="utf-8",
    )

    service = AnalysisService(
        tmp_path,
        build_config(
            mock_llm_analysis_path=analysis_path,
            mock_llm_edit_path=edit_path,
            apply_patch_in_dry_run=True,
        ),
    )

    def partial_apply(proposal) -> None:
        del proposal
        target_file.write_text("value = 2\n", encoding="utf-8")
        raise PatchApplyError("simulated partial git apply failure")

    monkeypatch.setattr(service.patch_applier, "apply", partial_apply)

    result = service.analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert "Patch apply failed" in result.summary
    assert result.failure is not None
    assert result.failure.stage.value == "patch_apply"
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"


def test_analyze_issue_skips_solution_artifact_in_ci_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "ai_sonar_bot.providers.llm_client.OpenAILLMClient.analyze_issue",
        lambda self, issue, context: IssueAnalysis(
            issue_key=issue.key,
            classification=AnalysisClassification.AUTO_FIXABLE,
            summary="summary",
            risk_notes=[],
            target_files=[context.file_path],
            proposed_strategy="Apply the minimal fix.",
        ),
    )
    monkeypatch.setattr(
        "ai_sonar_bot.providers.llm_client.OpenAILLMClient.generate_structured_edit",
        lambda self, issue, context: StructuredEditProposal(
            issue_key=issue.key,
            edits=[
                TextEdit(
                    file_path=context.file_path,
                    search_text="value = 1",
                    replace_text="value = 2",
                    line_hint=1,
                )
            ],
            commit_message="fix(sonar): patch service [FIXTURE-1]",
            mr_title="fix: patch service",
            mr_description="summary",
        ),
    )

    result = AnalysisService(
        tmp_path,
        build_config(execution_mode="ci", write_solution_artifacts_in_ci=False),
    ).analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert "Solution file:" not in result.summary
    assert result.patch is not None
    assert not (tmp_path / "artifacts" / "openai-solution.json").exists()


def test_analyze_issue_retries_validation_with_regenerated_structured_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")

    class RetryLLMClient:
        def __init__(self) -> None:
            self.edit_calls = 0

        def analyze_issue(self, issue: SonarIssue, context) -> IssueAnalysis:
            del issue, context
            return IssueAnalysis(
                issue_key="FIXTURE-1",
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
            self.edit_calls += 1
            replacement = "value = 3" if self.edit_calls == 1 else "value = 2"
            return StructuredEditProposal(
                issue_key="FIXTURE-1",
                edits=[
                    TextEdit(
                        file_path="src/service.py",
                        search_text="value = 1",
                        replace_text=replacement,
                        line_hint=1,
                    )
                ],
                commit_message="fix(sonar): patch service [FIXTURE-1]",
                mr_title="fix: patch service",
                mr_description="summary",
            )

    retry_client = RetryLLMClient()
    service = AnalysisService(
        tmp_path,
        build_config(
            apply_patch_in_dry_run=True,
            validation_commands=['test "$(cat src/service.py)" = "value = 2"'],
            max_retry_count=1,
        ),
    )
    monkeypatch.setattr(
        AnalysisService,
        "_build_llm_client",
        lambda self: retry_client,
    )

    result = service.analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert result.failure is None
    assert result.patch_applied is True
    assert result.validation_passed is True
    assert retry_client.edit_calls == 2
    assert (tmp_path / "src" / "service.py").read_text(encoding="utf-8") == "value = 2\n"


def test_analyze_issue_prefers_bot_rendered_diff_from_structured_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")

    class StructuredEditLLMClient:
        def analyze_issue(self, issue: SonarIssue, context) -> IssueAnalysis:
            del issue, context
            return IssueAnalysis(
                issue_key="FIXTURE-1",
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
                issue_key="FIXTURE-1",
                edits=[
                    TextEdit(
                        file_path="src/service.py",
                        search_text="value = 1",
                        replace_text="value = 2",
                        line_hint=1,
                    )
                ],
                commit_message="fix(sonar): patch service [FIXTURE-1]",
                mr_title="fix: patch service",
                mr_description="summary",
            )

    service = AnalysisService(
        tmp_path,
        build_config(
            apply_patch_in_dry_run=True,
            validation_commands=['test "$(cat src/service.py)" = "value = 2"'],
        ),
    )
    monkeypatch.setattr(
        AnalysisService,
        "_build_llm_client",
        lambda self: StructuredEditLLMClient(),
    )

    result = service.analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert "Diff rendered by bot from structured edit proposal." in result.summary
    assert result.patch_applied is True
    assert result.validation_passed is True
    assert result.patch is not None
    assert "diff --git a/src/service.py b/src/service.py" in result.patch.unified_diff
    assert (tmp_path / "src" / "service.py").read_text(encoding="utf-8") == "value = 2\n"


def test_analyze_issue_rejects_unrenderable_structured_edit_without_raw_diff_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text(
        "status_code = 1\nstatus_code = 2\n",
        encoding="utf-8",
    )

    class AmbiguousStructuredEditLLMClient:
        def analyze_issue(self, issue: SonarIssue, context) -> IssueAnalysis:
            del issue, context
            return IssueAnalysis(
                issue_key="FIXTURE-1",
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
                issue_key="FIXTURE-1",
                edits=[
                    TextEdit(
                        file_path="src/service.py",
                        search_text="status_code",
                        replace_text="_",
                    )
                ],
                commit_message="fix(sonar): patch service [FIXTURE-1]",
                mr_title="fix: patch service",
                mr_description="summary",
            )

    service = AnalysisService(
        tmp_path,
        build_config(
            apply_patch_in_dry_run=True,
            validation_commands=[],
        ),
    )
    monkeypatch.setattr(
        AnalysisService,
        "_build_llm_client",
        lambda self: AmbiguousStructuredEditLLMClient(),
    )

    result = service.analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert result.patch is None
    assert result.patch_applied is False
    assert result.failure is not None
    assert result.failure.stage.value == "analysis"
    assert "Structured edit could not be rendered safely" in result.summary
    assert "matched multiple locations" in result.summary


def test_analyze_issue_rejects_multi_file_structured_edit_for_v1(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("other = 1\n", encoding="utf-8")

    class MultiFileStructuredEditLLMClient:
        def analyze_issue(self, issue: SonarIssue, context) -> IssueAnalysis:
            del issue, context
            return IssueAnalysis(
                issue_key="FIXTURE-1",
                classification=AnalysisClassification.AUTO_FIXABLE,
                summary="Fixture analysis summary",
                risk_notes=[],
                target_files=["src/service.py", "src/other.py"],
                proposed_strategy="Apply the minimal fix.",
            )

        def generate_structured_edit(
            self,
            issue: SonarIssue,
            context,
        ) -> StructuredEditProposal:
            del issue, context
            return StructuredEditProposal(
                issue_key="FIXTURE-1",
                edits=[
                    TextEdit(
                        file_path="src/service.py",
                        search_text="value = 1",
                        replace_text="value = 2",
                        line_hint=1,
                    ),
                    TextEdit(
                        file_path="src/other.py",
                        search_text="other = 1",
                        replace_text="other = 2",
                        line_hint=1,
                    ),
                ],
                commit_message="fix(sonar): patch service [FIXTURE-1]",
                mr_title="fix: patch service",
                mr_description="summary",
            )

    service = AnalysisService(
        tmp_path,
        build_config(
            apply_patch_in_dry_run=True,
            validation_commands=[],
        ),
    )
    monkeypatch.setattr(
        AnalysisService,
        "_build_llm_client",
        lambda self: MultiFileStructuredEditLLMClient(),
    )

    result = service.analyze_issue(
        selected_issue=build_issue(),
        dry_run=True,
    )

    assert result.patch is None
    assert result.patch_applied is False
    assert result.failure is not None
    assert result.failure.stage.value == "analysis"
    assert "Structured edit could not be rendered safely" in result.summary
    assert "touch exactly one file" in result.summary

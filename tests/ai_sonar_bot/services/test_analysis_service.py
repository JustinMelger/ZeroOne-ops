import subprocess
from pathlib import Path

from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.analysis_service import AnalysisService


def build_config(
    *,
    mock_llm_analysis_path: Path | None = None,
    mock_llm_patch_path: Path | None = None,
    apply_patch_in_dry_run: bool = False,
    validation_commands: list[str] | None = None,
    max_retry_count: int = 1,
) -> AppConfig:
    return AppConfig(
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
        mock_llm_patch_path=mock_llm_patch_path,
        apply_patch_in_dry_run=apply_patch_in_dry_run,
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
    patch_path = tmp_path / "patch.json"
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
    patch_path.write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-1",\n'
            '  "files_touched": ["src/service.py"],\n'
            '  "unified_diff": "diff --git a/src/service.py b/src/service.py\\n'
            "--- a/src/service.py\\n"
            "+++ b/src/service.py\\n"
            "@@ -1 +1 @@\\n"
            "-value = 1\\n"
            '+value = 2\\n",\n'
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
            mock_llm_patch_path=patch_path,
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
    patch_path = tmp_path / "patch.json"
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
    patch_path.write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-1",\n'
            '  "files_touched": ["src/service.py"],\n'
            '  "unified_diff": "diff --git a/src/service.py b/src/service.py\\n'
            "--- a/src/service.py\\n"
            "+++ b/src/service.py\\n"
            "@@ -1 +1 @@\\n"
            "-value = 1\\n"
            '+value = 2\\n",\n'
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
            mock_llm_patch_path=patch_path,
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
    patch_path = tmp_path / "patch.json"
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
    patch_path.write_text(
        (
            "{\n"
            '  "issue_key": "FIXTURE-1",\n'
            '  "files_touched": ["src/service.py"],\n'
            '  "unified_diff": "diff --git a/src/service.py b/src/service.py\\n'
            "--- a/src/service.py\\n"
            "+++ b/src/service.py\\n"
            "@@ -1 +1 @@\\n"
            "-value = 1\\n"
            '+value = 2\\n",\n'
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
            mock_llm_patch_path=patch_path,
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
    assert (tmp_path / "src" / "service.py").read_text(encoding="utf-8") == "value = 1\n"

from pathlib import Path

from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.remediation import RemediationWorkItem
from ai_sonar_bot.services.remediation_context_builder import RemediationContextBuilder


def build_config(*, max_file_bytes: int = 200_000) -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["LOW"],
        supported_issue_types=["CODE_SMELL"],
        validation_commands=[],
        analysis=AnalysisConfig(max_file_bytes=max_file_bytes),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_work_item(
    *,
    file_path: str = "src/service.py",
    line: int | None = 2,
) -> RemediationWorkItem:
    return RemediationWorkItem(
        dashboard_item_id="sonar:1",
        source_type="sonarqube",
        source_ref="AX123",
        title="python:S1125 in src/service.py",
        status="open",
        message="Replace boolean equality with direct truthiness.",
        file_path=file_path,
        line=line,
    )


def test_build_returns_context_for_normalized_work_item(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    builder = RemediationContextBuilder(tmp_path, build_config())

    context = builder.build(build_work_item())

    assert context is not None
    assert context.issue_key == "AX123"
    assert context.file_path == "src/service.py"
    assert "   2: b = 2" in context.snippet.content


def test_build_returns_none_when_work_item_file_is_missing(tmp_path: Path) -> None:
    builder = RemediationContextBuilder(tmp_path, build_config())

    context = builder.build(build_work_item(file_path="src/missing.py"))

    assert context is None

from pathlib import Path

from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.remediation import RemediationExecutionTarget
from ai_sonar_bot.services.context_builder import ContextBuilder


def build_config(max_file_bytes: int = 200_000) -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["MAJOR"],
        supported_issue_types=["BUG"],
        validation_commands=[],
        analysis=AnalysisConfig(
            context_lines_before=1,
            context_lines_after=1,
            max_file_bytes=max_file_bytes,
        ),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main"),
    )


def test_build_returns_full_file_when_under_size_limit(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    target = source_dir / "service.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")

    builder = ContextBuilder(tmp_path, build_config())

    context = builder.build(
        RemediationExecutionTarget(
            item_id="AX1",
            source_type="sonarqube",
            source_ref="AX1",
            title="python:S2259 in src/service.py",
            status="OPEN",
            message="Issue",
            file_path="src/service.py",
            line=2,
            rule_id="python:S2259",
            severity="MAJOR",
            issue_type="BUG",
            component="sample-project:src/service.py",
            project="sample-project",
        )
    )

    assert context is not None
    assert context.full_file_included is True
    assert context.truncated is False
    assert context.snippet.start_line == 1
    assert "   2: line2" in context.snippet.content


def test_build_returns_focused_window_when_file_is_over_limit(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    target = source_dir / "service.py"
    target.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    builder = ContextBuilder(tmp_path, build_config(max_file_bytes=1))

    context = builder.build(
        RemediationExecutionTarget(
            item_id="AX2",
            source_type="sonarqube",
            source_ref="AX2",
            title="python:S2259 in src/service.py",
            status="OPEN",
            message="Issue",
            file_path="src/service.py",
            line=3,
            rule_id="python:S2259",
            severity="MAJOR",
            issue_type="BUG",
            component="sample-project:src/service.py",
            project="sample-project",
        )
    )

    assert context is not None
    assert context.full_file_included is False
    assert context.truncated is True
    assert context.snippet.start_line == 2
    assert context.snippet.end_line == 4
    assert "   2: line2" in context.snippet.content
    assert "   4: line4" in context.snippet.content


def test_build_returns_none_when_file_is_missing(tmp_path: Path) -> None:
    builder = ContextBuilder(tmp_path, build_config())

    context = builder.build(
        RemediationExecutionTarget(
            item_id="AX3",
            source_type="sonarqube",
            source_ref="AX3",
            title="python:S2259 in src/missing.py",
            status="OPEN",
            message="Issue",
            file_path="src/missing.py",
            line=1,
            rule_id="python:S2259",
            severity="MAJOR",
            issue_type="BUG",
            component="sample-project:src/missing.py",
            project="sample-project",
        )
    )

    assert context is None

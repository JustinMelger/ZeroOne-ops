from pathlib import Path

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import ProjectedReviewFeedback, ProjectedReviewFinding
from zeroone_ops.services.remediation.remediation_context_builder import (
    RemediationContextBuilder,
)


def build_config(
    *,
    max_file_bytes: int = 200_000,
    repository_guidance_paths: list[str] | None = None,
) -> AppConfig:
    return AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            bootstrap_severities=["LOW"],
            analysis=AnalysisConfig(max_file_bytes=max_file_bytes),
        ),
        repository_guidance_paths=repository_guidance_paths,
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_work_item(
    *,
    file_path: str = "src/service.py",
    line: int | None = 2,
) -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="sonar:1",
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
    assert context.repository_guidance == []


def test_build_returns_none_when_work_item_file_is_missing(tmp_path: Path) -> None:
    builder = RemediationContextBuilder(tmp_path, build_config())

    context = builder.build(build_work_item(file_path="src/missing.py"))

    assert context is None


def test_build_attaches_typed_projected_review_feedback(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    builder = RemediationContextBuilder(tmp_path, build_config())

    context = builder.build(
        build_work_item().model_copy(
            update={
                "reviewed_sha": "abc123",
                "review_feedback": ProjectedReviewFeedback(
                    finding_count=1,
                    summary="Ordering changed in a shared path.",
                    findings=[
                        ProjectedReviewFinding(
                            title="Preserve ordering",
                            file_path="src/service.py",
                            evidence="Return order changed",
                            explanation="Changes the API response.",
                            suggested_follow_up="Preserve the existing ordering.",
                        )
                    ],
                ),
            }
        )
    )

    assert context is not None
    assert context.prior_review_feedback is not None
    assert context.prior_review_feedback.review_status == "findings_present"
    assert context.prior_review_feedback.review_findings_count == 1
    assert (
        context.prior_review_feedback.review_feedback_summary
        == "Ordering changed in a shared path."
    )
    assert context.prior_review_feedback.reviewed_head_sha == "abc123"
    assert len(context.prior_review_feedback.findings) == 1


def test_build_attaches_repository_guidance_when_available(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "service.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text(
        "\n".join(
            [
                "# Agent Guide",
                "",
                "Use this repository guidance for fixes and reviews.",
                "",
                "- Prefer regression tests for behavior changes.",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "technical-design-pr-review.md").write_text(
        "\n".join(
            [
                "# Technical Design",
                "",
                "Review notes should stay evidence-backed.",
                "",
                "## Standards",
                "- Prefer no findings over speculative comments.",
            ]
        ),
        encoding="utf-8",
    )
    builder = RemediationContextBuilder(tmp_path, build_config())

    context = builder.build(build_work_item())

    assert context is not None
    assert [guidance.file_path for guidance in context.repository_guidance] == [
        "AGENT.md",
        "docs/technical-design-pr-review.md",
    ]
    assert "Prefer regression tests" in context.repository_guidance[0].summary
    assert "Prefer no findings" in context.repository_guidance[1].summary


def test_build_uses_configured_repository_guidance_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    (tmp_path / "CONTRIBUTING.md").write_text(
        "# Contributing\nUse the configured remediation guidance.\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "# Agents\nThis default guidance must not be loaded.\n",
        encoding="utf-8",
    )
    builder = RemediationContextBuilder(
        tmp_path,
        build_config(repository_guidance_paths=["CONTRIBUTING.md"]),
    )

    context = builder.build(build_work_item())

    assert context is not None
    assert [guidance.file_path for guidance in context.repository_guidance] == ["CONTRIBUTING.md"]

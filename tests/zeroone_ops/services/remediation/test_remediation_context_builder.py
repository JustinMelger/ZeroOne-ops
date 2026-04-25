from pathlib import Path

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.remediation import RemediationWorkItem
from zeroone_ops.services.remediation.remediation_context_builder import (
    RemediationContextBuilder,
)


def build_config(*, max_file_bytes: int = 200_000) -> AppConfig:
    return AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            supported_severities=["LOW"],
            analysis=AnalysisConfig(max_file_bytes=max_file_bytes),
        ),
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


def test_build_attaches_prior_review_feedback_for_retry_eligible_item(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    builder = RemediationContextBuilder(tmp_path, build_config())

    context = builder.build(
        build_work_item().model_copy(
            update={
                "source_payload": {
                    "retry_eligible": True,
                    "review_status": "findings_present",
                    "review_findings_count": 2,
                    "review_feedback_summary": "Ordering changed in a shared path.",
                    "review_confidence": 0.82,
                    "review_confidence_reason": "The diff directly changes output ordering.",
                    "reviewed_head_sha": "abc123",
                    "retry_count": 1,
                }
            }
        )
    )

    assert context is not None
    assert context.prior_review_feedback is not None
    assert context.prior_review_feedback.review_status == "findings_present"
    assert context.prior_review_feedback.review_findings_count == 2
    assert (
        context.prior_review_feedback.review_feedback_summary
        == "Ordering changed in a shared path."
    )
    assert context.prior_review_feedback.retry_count == 1

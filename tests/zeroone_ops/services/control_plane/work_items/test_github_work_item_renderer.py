from datetime import UTC, datetime

from zeroone_ops.models.work_item import (
    ProjectedReviewState,
    PublicationRetryState,
    WorkItemExecutionFailure,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)

from .test_support import build_work_item


def test_render_body_includes_projected_review_section_when_present() -> None:
    renderer = GitHubWorkItemRenderer()
    work_item = build_work_item().model_copy(
        update={
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha="abc123def",
                review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
                follow_up_required=True,
            )
        }
    )

    body = renderer.render_body(work_item)

    assert "## Review Projection" in body
    assert "- Classification: `findings_present`" in body
    assert "- Reviewed SHA: `abc123def`" in body
    assert "- Follow-up required: `yes`" in body


def test_rendering_prefers_concrete_detail_for_templated_finding_titles() -> None:
    renderer = GitHubWorkItemRenderer()
    work_item = build_work_item().model_copy(
        update={
            "summary": "Unnecessary {kind} comprehension",
            "detail": "Unnecessary set comprehension (rewrite using set())",
            "source": build_work_item().source.model_copy(update={"source": "ruff-sarif"}),
            "remediation_context": build_work_item().remediation_context.model_copy(
                update={"diagnostic_code": "C416"}
            ),
        }
    )

    title = renderer.render_title(work_item)
    body = renderer.render_body(work_item)

    assert title == "ZeroOne Ops: C416 in api.py:42"
    assert "## Finding" in body
    assert "Unnecessary set comprehension (rewrite using set())" in body
    assert "- Source: Ruff SARIF" in body
    assert "Source item key" not in body
    assert "Repository scope" not in body
    assert "## Remediation PR" in body
    assert "No remediation pull request is linked yet." in body


def test_rendering_includes_distinct_detail_for_non_templated_findings() -> None:
    renderer = GitHubWorkItemRenderer()
    work_item = build_work_item().model_copy(
        update={
            "summary": "Avoid equality comparisons to True",
            "detail": "Use direct truthiness instead of == True.",
        }
    )

    body = renderer.render_body(work_item)
    visible_body = body.split("## Machine State", maxsplit=1)[0]

    assert "Avoid equality comparisons to True" in visible_body
    assert "Use direct truthiness instead of == True." in visible_body
    assert (
        "The collapsed machine state is managed by ZeroOne Ops and may be overwritten on sync."
        in visible_body
    )


def test_render_title_bounds_non_diagnostic_finding_text() -> None:
    renderer = GitHubWorkItemRenderer()
    work_item = build_work_item().model_copy(
        update={
            "summary": "A very long finding title " * 10,
            "file_path": None,
        }
    )

    title = renderer.render_title(work_item)

    assert len(title) <= 120
    assert title.endswith("...")


def test_render_title_keeps_distinct_line_suffix_when_bounded() -> None:
    work_item = build_work_item().model_copy(
        update={
            "summary": "A very long finding title " * 10,
            "file_path": "src/a-very-long-file-name.py",
            "line": 1411,
            "remediation_context": build_work_item().remediation_context.model_copy(
                update={"diagnostic_code": "C416"}
            ),
        }
    )

    title = GitHubWorkItemRenderer().render_title(work_item)

    assert len(title) <= 120
    assert title.endswith(":1411")


def test_render_title_bounds_oversized_line_suffix() -> None:
    work_item = build_work_item().model_copy(
        update={
            "line": int("9" * 130),
            "remediation_context": build_work_item().remediation_context.model_copy(
                update={"diagnostic_code": "C416"}
            ),
        }
    )

    title = GitHubWorkItemRenderer().render_title(work_item)

    assert len(title) <= 120


def test_render_body_includes_dismissal_execution_evidence() -> None:
    work_item = build_work_item(status="dismissed").model_copy(
        update={
            "execution_failure": WorkItemExecutionFailure(
                status="dismissed",
                stage="analysis",
                summary="Manual review is required for this remediation.",
                retry_count=0,
                run_id="run-43",
                occurred_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
                execution_url="https://github.example.com/octo-org/octo-repo/actions/runs/43",
            )
        }
    )

    body = GitHubWorkItemRenderer().render_body(work_item)

    assert "- Status: `dismissed`" in body
    assert "- Stage: `analysis`" in body
    assert "- Run ID: `run-43`" in body
    assert "## Recovery" not in body


def test_render_body_includes_last_execution_when_blocked() -> None:
    renderer = GitHubWorkItemRenderer()
    work_item = build_work_item().model_copy(
        update={
            "status": "blocked",
            "execution_failure": WorkItemExecutionFailure(
                stage="validation",
                summary="Validation failed after retry.",
                retry_count=1,
                run_id="run-42",
                occurred_at=datetime(2026, 7, 31, 8, 30, tzinfo=UTC),
                failed_command="uv run pytest",
                exit_code=1,
                validation_outcome="unscoped_regression",
                execution_url="https://github.example.com/octo-org/octo-repo/actions/runs/42",
            ),
        }
    )

    body = renderer.render_body(work_item)

    assert "## Last Execution" in body
    assert "- Command: `uv run pytest`" in body
    assert "- Exit code: `1`" in body
    assert "- Validation outcome: `unscoped_regression`" in body
    assert "[View workflow logs](" in body
    assert "https://github.example.com/octo-org/octo-repo/actions/runs/42" in body
    assert "## Recovery" in body
    assert "This remediation is blocked because Validation failed after retry." in body
    assert "Requeue for remediation: `/zeroone remediation requeue`" in body
    assert "Stop automation: `/zeroone remediation dismiss`" in body


def test_render_body_shows_publication_recovery_instructions_only_when_blocked() -> None:
    renderer = GitHubWorkItemRenderer()
    work_item = build_work_item().model_copy(
        update={
            "status": "blocked",
            "publication_retry": PublicationRetryState(
                branch_name="zeroone-ops/fix",
                commit_sha="abc123",
                reason="change_request_publish_failed",
            ),
        }
    )

    blocked_body = renderer.render_body(work_item)
    approved_body = renderer.render_body(work_item.model_copy(update={"status": "approved"}))

    assert "This remediation is blocked because change-request publication failed." in blocked_body
    assert "Requeue for remediation: `/zeroone remediation requeue`" in blocked_body
    assert "## Recovery" not in approved_body

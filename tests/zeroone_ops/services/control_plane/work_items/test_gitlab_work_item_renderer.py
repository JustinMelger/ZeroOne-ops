from datetime import UTC, datetime

from zeroone_ops.models.work_item import WorkItemExecutionFailure
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)

from .test_support import build_work_item


def test_render_body_uses_gitlab_merge_request_wording() -> None:
    body = GitLabWorkItemRenderer().render_body(build_work_item())

    assert "## Remediation Merge Request" in body
    assert "No remediation merge request is linked yet." in body
    assert "No remediation merge-request review has been projected yet." in body
    assert "## Recovery" not in body
    assert "zeroone-work-item-state" in body


def test_rendering_uses_my_py_sarif_source_label() -> None:
    work_item = build_work_item().model_copy(
        update={"source": build_work_item().source.model_copy(update={"source": "mypy-sarif"})}
    )

    body = GitLabWorkItemRenderer().render_body(work_item)

    assert "- Source: MyPy SARIF" in body


def test_rendering_includes_terminal_resolution_only_when_present() -> None:
    renderer = GitLabWorkItemRenderer()
    no_longer_detected = build_work_item(status="completed").model_copy(
        update={"resolution": "no_longer_detected"}
    )
    no_change_required = build_work_item(status="completed").model_copy(
        update={"resolution": "no_change_required"}
    )
    merged = build_work_item(status="completed").model_copy(update={"resolution": "merged"})

    assert "- Resolution: No longer detected" in renderer.render_body(no_longer_detected)
    assert "- Resolution: No change required" in renderer.render_body(no_change_required)
    assert "- Resolution: Merged" in renderer.render_body(merged)
    assert "- Resolution:" not in renderer.render_body(build_work_item())


def test_render_body_includes_recovery_commands_for_blocked_work_item() -> None:
    work_item = build_work_item().model_copy(
        update={
            "status": "blocked",
            "execution_failure": WorkItemExecutionFailure(
                stage="validation",
                summary="Validation failed after retry.",
                retry_count=1,
                run_id="run-42",
                occurred_at=datetime(2026, 8, 7, 10, 0, tzinfo=UTC),
                validation_outcome="unscoped_regression",
            ),
        }
    )

    body = GitLabWorkItemRenderer().render_body(work_item)

    assert "## Last Execution" in body
    assert "- Validation outcome: `unscoped_regression`" in body
    assert "## Recovery" in body
    assert "Requeue for remediation: `/zeroone remediation requeue`" in body
    assert "Stop automation: `/zeroone remediation dismiss`" in body


def test_render_body_includes_dirty_workspace_diagnostics() -> None:
    work_item = build_work_item(status="blocked").model_copy(
        update={
            "execution_failure": WorkItemExecutionFailure(
                stage="branch_preparation",
                summary=(
                    "Branch preparation failed: Repository has uncommitted or untracked changes:\n"
                    "- untracked: artifacts/mypy.sarif\n"
                    "Ignore generated runtime files or clean the workspace before retrying."
                ),
                retry_count=0,
                run_id="run-44",
                occurred_at=datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
                execution_url="https://gitlab.example.com/group/project/-/jobs/44",
            )
        }
    )

    body = GitLabWorkItemRenderer().render_body(work_item)

    assert "- Stage: `branch_preparation`" in body
    assert "- untracked: artifacts/mypy.sarif" in body
    assert "[View workflow logs](https://gitlab.example.com/group/project/-/jobs/44)" in body


def test_render_title_and_labels_are_bounded_and_provider_indexed() -> None:
    work_item = build_work_item().model_copy(
        update={"summary": "A very long finding title " * 10, "file_path": None}
    )

    renderer = GitLabWorkItemRenderer()

    assert len(renderer.render_title(work_item)) <= 120
    assert renderer.render_labels(work_item) == [
        "zeroone-work-item",
        "zeroone-status:approved",
        "zeroone-source:sonarqube",
    ]


def test_render_title_retains_line_for_similar_findings() -> None:
    work_item = build_work_item().model_copy(
        update={
            "line": 1411,
            "remediation_context": build_work_item().remediation_context.model_copy(
                update={"diagnostic_code": "no-untyped-def"}
            ),
        }
    )

    title = GitLabWorkItemRenderer().render_title(work_item)

    assert title.endswith(":1411")
    assert len(title) <= 120


def test_render_title_bounds_oversized_line_suffix() -> None:
    work_item = build_work_item().model_copy(
        update={
            "line": int("9" * 130),
            "remediation_context": build_work_item().remediation_context.model_copy(
                update={"diagnostic_code": "no-untyped-def"}
            ),
        }
    )

    title = GitLabWorkItemRenderer().render_title(work_item)

    assert len(title) <= 120

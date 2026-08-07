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
    assert "zeroone-work-item-state" in body


def test_render_body_includes_recovery_commands_for_blocked_work_items() -> None:
    work_item = build_work_item().model_copy(
        update={
            "status": "blocked",
            "execution_failure": WorkItemExecutionFailure(
                stage="validation",
                summary="Validation failed after retry.",
                retry_count=1,
                run_id="run-42",
                occurred_at=datetime(2026, 8, 7, 10, 0, tzinfo=UTC),
            ),
        }
    )

    body = GitLabWorkItemRenderer().render_body(work_item)

    assert "## Last Execution" in body
    assert "## Recovery" in body
    assert "Requeue for remediation: `/zeroone remediation requeue`" in body
    assert "Stop automation: `/zeroone remediation dismiss`" in body


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

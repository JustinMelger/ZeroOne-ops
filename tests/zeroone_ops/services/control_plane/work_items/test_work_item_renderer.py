from datetime import UTC, datetime, timedelta

import pytest

from zeroone_ops.models.work_item import (
    ProjectedReviewState,
    ReviewRevisionRequest,
    WorkItemExecutionFailure,
    WorkItemState,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)

from .test_support import build_work_item


@pytest.fixture(params=[GitHubWorkItemRenderer, GitLabWorkItemRenderer])
def renderer(request: pytest.FixtureRequest) -> GitHubWorkItemRenderer | GitLabWorkItemRenderer:
    return request.param()


@pytest.fixture
def failed_revision() -> WorkItemState:
    requested_at = datetime(2026, 9, 19, tzinfo=UTC)
    return build_work_item(status="review_feedback_required").model_copy(
        update={
            "last_revision_command": ReviewRevisionRequest(
                actor="operator",
                request_reference="comment-1",
                occurred_at=requested_at,
                reviewed_sha="abc123",
            ),
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha="abc123",
                follow_up_required=True,
            ),
            "execution_failure": WorkItemExecutionFailure(
                stage="validation",
                summary="Validation failed.",
                retry_count=0,
                run_id="revision-1",
                occurred_at=requested_at + timedelta(minutes=1),
                execution_url="https://ci.example.com/runs/1",
            ),
        }
    )


def test_failed_revision_notice_precedes_requeue_guidance(
    renderer: GitHubWorkItemRenderer | GitLabWorkItemRenderer,
    failed_revision: WorkItemState,
) -> None:
    before = failed_revision.model_dump_json()
    body = renderer.render_body(failed_revision)

    assert (
        "**Last revision failed.** Check **Last Execution**, address the cause, "
        "then post a new `/zeroone remediation requeue` command here."
    ) in body
    assert body.index("**Last revision failed.**") < body.index("Requeue for remediation:")
    assert "## Last Execution" in body
    assert "Validation failed." in body
    assert "[View workflow logs](https://ci.example.com/runs/1)" in body
    assert failed_revision.model_dump_json() == before


@pytest.mark.parametrize(
    "missing", ["execution_failure", "last_revision_command", "projected_review"]
)
def test_notice_requires_revision_failure_evidence(
    renderer: GitHubWorkItemRenderer | GitLabWorkItemRenderer,
    failed_revision: WorkItemState,
    missing: str,
) -> None:
    body = renderer.render_body(failed_revision.model_copy(update={missing: None}))

    assert "**Last revision failed.**" not in body
    assert "Requeue for remediation:" in body


@pytest.mark.parametrize(
    "scenario", ["older_failure", "different_sha", "naive_failure", "naive_command"]
)
def test_notice_omits_uncorrelated_failure_evidence(
    renderer: GitHubWorkItemRenderer | GitLabWorkItemRenderer,
    failed_revision: WorkItemState,
    scenario: str,
) -> None:
    failure = failed_revision.execution_failure
    command = failed_revision.last_revision_command
    assert failure is not None
    assert command is not None
    if scenario == "older_failure":
        failure = failure.model_copy(
            update={"occurred_at": command.occurred_at - timedelta(seconds=1)}
        )
    elif scenario == "different_sha":
        command = command.model_copy(update={"reviewed_sha": "old-sha"})
    elif scenario == "naive_failure":
        failure = failure.model_copy(
            update={"occurred_at": failure.occurred_at.replace(tzinfo=None)}
        )
    else:
        command = command.model_copy(
            update={"occurred_at": command.occurred_at.replace(tzinfo=None)}
        )
    body = renderer.render_body(
        failed_revision.model_copy(
            update={"execution_failure": failure, "last_revision_command": command}
        )
    )

    assert "**Last revision failed.**" not in body
    assert "## Last Execution" in body


@pytest.mark.parametrize("status", ["review_revision_queued", "in_progress", "completed"])
def test_notice_disappears_after_follow_up_transition(
    renderer: GitHubWorkItemRenderer | GitLabWorkItemRenderer,
    failed_revision: WorkItemState,
    status: str,
) -> None:
    body = renderer.render_body(failed_revision.model_copy(update={"status": status}))

    assert "**Last revision failed.**" not in body
    assert "Requeue for remediation:" not in body


def test_notice_accepts_equal_command_and_failure_timestamps(
    renderer: GitHubWorkItemRenderer | GitLabWorkItemRenderer,
    failed_revision: WorkItemState,
) -> None:
    failure = failed_revision.execution_failure
    command = failed_revision.last_revision_command
    assert failure is not None
    assert command is not None
    body = renderer.render_body(
        failed_revision.model_copy(
            update={
                "execution_failure": failure.model_copy(update={"occurred_at": command.occurred_at})
            }
        )
    )

    assert "**Last revision failed.**" in body

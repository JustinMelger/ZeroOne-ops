from datetime import UTC, datetime, timedelta

import pytest

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.batch_execution import (
    BatchAnalysisRejection,
    BatchAttemptEvidence,
    BatchRejectedMember,
)
from zeroone_ops.models.work_item import (
    ProjectedReviewState,
    ReviewRevisionRequest,
    WorkItemExecutionFailure,
    WorkItemSemanticSafety,
    WorkItemState,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)

from .test_batch_finding_sync_coordinator import batch_state
from .test_batch_finding_sync_coordinator import harness as harness
from .test_support import build_work_item


@pytest.fixture(params=[GitHubWorkItemRenderer, GitLabWorkItemRenderer])
def renderer(request: pytest.FixtureRequest) -> GitHubWorkItemRenderer | GitLabWorkItemRenderer:
    return request.param()


def test_validation_diagnostics_are_shared_escaped_and_round_trip(renderer):
    failure = WorkItemExecutionFailure(
        stage="validation",
        summary="Correction withheld; validation failed.",
        retry_count=0,
        run_id="validation-1",
        occurred_at=datetime(2026, 10, 26, tzinfo=UTC),
        failed_command="pytest",
        exit_code=2,
        validation_phase="post_edit",
        baseline_exit_code=0,
        diagnostic_excerpt=(
            "src/app.py:3: in <module>\nE NameError: </pre><script>bad</script> ` ```"
        ),
        execution_url="https://ci.example/run/1",
    )
    state = build_work_item(status="blocked").model_copy(update={"execution_failure": failure})
    decoded = WorkItemState.model_validate_json(state.model_dump_json())
    assert decoded.execution_failure == failure
    body = renderer.render_body(decoded).split("## Machine State")[0]
    assert "Validation phase: `post_edit`" in body
    assert "Baseline exit code: `0`" in body
    assert "Exit code: `2`" in body
    assert "### Validation Diagnostic" in body
    assert "&lt;/pre&gt;&lt;script&gt;" in body
    assert "<script>" not in body
    assert "[View workflow logs](https://ci.example/run/1)" in body


def test_historical_failure_fields_remain_optional(renderer):
    failure = WorkItemExecutionFailure.model_validate(
        {
            "stage": "validation",
            "summary": "Failed",
            "retry_count": 0,
            "run_id": "old",
            "occurred_at": "2026-01-01T00:00:00Z",
        }
    )
    assert failure.validation_phase is None
    assert failure.diagnostic_excerpt is None
    state = build_work_item(status="blocked").model_copy(update={"execution_failure": failure})
    body = renderer.render_body(state)
    assert "### Validation Diagnostic" not in body


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


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("evidence", ["accepted", "rejected", "rejected_only", "empty", "absent"])
def test_change_rationale_ux_retains_machine_state(harness, batch, evidence):
    assessment = SemanticSafetyAssessment(
        current_behavior="The module imports an unused name.",
        intended_behavior="Remove the unused import without changing runtime behavior.",
        preservation_evidence=["No references to that name remain."],
    )
    reason = "Historical semantic-safety assessment was incomplete."
    record = (
        WorkItemSemanticSafety(
            assessment=assessment if evidence in {"accepted", "rejected"} else None,
            rejection_reason=reason if evidence in {"rejected", "rejected_only"} else None,
        )
        if evidence != "absent"
        else None
    )
    state = (batch_state() if batch else build_work_item()).model_copy(
        update={"semantic_safety": record}
    )
    before = state.model_dump()
    renderer = harness[1].upsert_service.renderer
    body = renderer.render_body(state)
    visible = body.split("## Machine State", maxsplit=1)[0]
    assert ("## Change Rationale" in visible) == (evidence not in {"empty", "absent"})
    assert "## Semantic Safety" not in visible
    if evidence in {"accepted", "rejected"}:
        assert "- Intended change: Remove the unused import" in visible
        assert "- Why existing behavior should be preserved:" in visible
        assert "Model-provided explanation; not independent verification." in visible
    if evidence in {"rejected", "rejected_only"}:
        assert f"- Why remediation stopped: {reason}" in visible
    if evidence == "rejected_only":
        assert "No change rationale was available." in visible
    parsed = harness[1].upsert_service.parser.parse_work_item_state(body)
    assert parsed.semantic_safety == record
    assert state.model_dump() == before
    assert ('"semantic_safety"' in body) == (record is not None)
    if evidence in {"accepted", "rejected"}:
        assert '"intended_behavior"' in body
        assert '"preservation_evidence"' in body


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("stage", ["semantic_safety", "validation", "custom_stage"])
def test_last_execution_stage_is_display_only(harness, batch, stage):
    failure = WorkItemExecutionFailure(
        stage=stage,
        summary="Historical failure evidence is preserved.",
        retry_count=0,
        run_id="run-1",
        occurred_at=datetime(2026, 10, 24, tzinfo=UTC),
    )
    state = (batch_state() if batch else build_work_item()).model_copy(
        update={"status": "blocked", "execution_failure": failure}
    )
    body = harness[1].upsert_service.renderer.render_body(state)
    visible = body.split("## Machine State", maxsplit=1)[0]
    label = "Change rationale" if stage == "semantic_safety" else stage
    assert f"- Stage: `{label}`" in visible
    parsed = harness[1].upsert_service.parser.parse_work_item_state(body)
    assert parsed.execution_failure == failure


@pytest.mark.parametrize("current", [True, False])
def test_batch_revision_stop_notice_and_retained_rationale_are_current_only(
    harness, failed_revision, current
):
    state = batch_state(status="review_feedback_required")
    assessment = SemanticSafetyAssessment(
        current_behavior="Imports are unused.",
        intended_behavior="Remove unused imports.",
        preservation_evidence=["Names have no references."],
    )
    failure = failed_revision.execution_failure.model_copy(
        update={
            "stage": "analysis",
            "summary": "Historical generic batch failure.",
            "batch_rejection": BatchAnalysisRejection(
                reason="manual_classification",
                members=(
                    BatchRejectedMember(finding_reference="a", reason="Needs manual reasoning."),
                ),
            ),
        }
    )
    command = failed_revision.last_revision_command
    if not current:
        command = command.model_copy(update={"reviewed_sha": "superseded"})
    state = state.model_copy(
        update={
            "execution_failure": failure,
            "last_revision_command": command,
            "projected_review": failed_revision.projected_review,
            "batch_attempt": BatchAttemptEvidence(
                batch_id=state.work_item_id,
                attempt_number=1,
                run_id="earlier-run-not-current-revision",
                members=state.batch.members,
                observation_run_ids=(),
            ),
            "semantic_safety": WorkItemSemanticSafety(assessment=assessment),
        }
    )
    before = state.model_dump_json()
    renderer = harness[1].upsert_service.renderer
    body = renderer.render_body(state)
    visible = body.split("## Machine State")[0]
    assert ("### Latest Attempt" in visible) == current
    assert ("## Retained Change Rationale" in visible) == current
    assert "Historical generic batch failure." in visible
    assert "Model requested manual handling." in visible
    if current:
        assert visible.index("### Latest Attempt") < visible.index("## Members")
        assert "Recorded location: src/routes.py:10; rule: F401" in visible
        assert "Retained from earlier analysis; not produced by this failed attempt." in visible
        assert "[View workflow logs](https://ci.example.com/runs/1)" in visible
    assert "earlier-run-not-current-revision" not in visible
    parsed = harness[1].upsert_service.parser.parse_work_item_state(body)
    assert parsed.execution_failure == failure
    assert parsed.semantic_safety.assessment == assessment
    assert state.model_dump_json() == before

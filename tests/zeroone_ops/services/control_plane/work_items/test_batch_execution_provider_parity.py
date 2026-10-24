"""Run internal batch execution through both real issue adapters and shared services."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zeroone_ops.models.analysis import (
    BatchIssueAnalysis,
    SemanticSafetyAssessment,
    StructuredEditProposal,
    TextEdit,
)
from zeroone_ops.models.batch_execution import BatchAnalysisCoverage, BatchUnaddressableMember
from zeroone_ops.models.change_request import ChangeRequestInfo, ChangeRequestState
from zeroone_ops.models.config import AppConfig, GitHubConfig, GitLabConfig, RemediationConfig
from zeroone_ops.models.remediation_intake import RemediationIntakeRecord
from zeroone_ops.models.state import AppState, RepositoryState, RunStatus
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    PublicationRetryState,
    ReviewRevisionRequest,
)
from zeroone_ops.services.control_plane.work_items.remediation_intake_coordinator import (
    RemediationIntakeCoordinator,
)
from zeroone_ops.services.control_plane.work_items.remediation_work_item_selection_service import (
    is_internal_remediation_execution_eligible,
)
from zeroone_ops.services.remediation.change_request_publisher import PublishedChangeRequest
from zeroone_ops.services.remediation.control_plane import (
    GitHubRemediationControlPlane,
    GitLabRemediationControlPlane,
)
from zeroone_ops.services.remediation.execution_service import ExecutionService
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryService,
)
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
    RecoveryRequest,
)
from zeroone_ops.services.remediation.work_item_remediation_runner import WorkItemRemediationRunner
from zeroone_ops.services.shared.branch_manager import BranchManager
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore

from .test_batch_finding_sync_coordinator import (
    NOW,
    SCOPE,
    batch_state,
    finding,
    policy,
    seed,
    stored,
)
from .test_batch_finding_sync_coordinator import harness as harness


def setup_execution(harness, tmp_path, monkeypatch, *, validation_commands=None):
    client, service, storage = harness
    members = [
        finding("a").model_copy(update={"line_start": 1}),
        finding("b").model_copy(update={"line_start": 2}),
    ]
    seed(harness, batch_state(members=members, status="approved"))
    (tmp_path / "src").mkdir()
    (tmp_path / "src/routes.py").write_text("import os\nimport sys\nvalue = 1\n")
    for command in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "Test"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "add", "src/routes.py"],
        ["git", "commit", "-m", "initial"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    config = AppConfig(
        platform=client.provider,
        execution_mode="ci",
        base_branch="main",
        github=GitHubConfig(),
        gitlab=GitLabConfig(),
        remediation=RemediationConfig(
            target_branch="main", max_retry_count=0, validation_commands=validation_commands or []
        ),
    )
    control_plane = (
        GitHubRemediationControlPlane(work_item_service=service, repository_id=SCOPE)
        if client.provider == "github"
        else GitLabRemediationControlPlane(work_item_service=service, project_id=SCOPE)
    )
    engine = ExecutionService(tmp_path, config, remediation_control_plane=control_plane)
    model = Mock()
    model.analyze_issue.return_value = BatchIssueAnalysis(
        issue_key="batch",
        classification="auto_fixable",
        summary="Remove both imports",
        proposed_strategy="Remove both unused imports",
        batch_coverage=BatchAnalysisCoverage(addressable_ids=("a", "b")),
        semantic_safety=SemanticSafetyAssessment(
            current_behavior="Unused imports precede a constant.",
            intended_behavior="The constant remains unchanged.",
            preservation_evidence=["Neither imported name is used."],
        ),
    )
    model.generate_structured_edit.return_value = StructuredEditProposal(
        issue_key="batch",
        edits=[
            TextEdit(file_path="src/routes.py", search_text=f"import {name}\n", replace_text="")
            for name in ("os", "sys")
        ],
        commit_message="Remove imports",
        change_request_title="Remove imports",
        change_request_description="Remove both unused imports without changing the constant.",
    )
    monkeypatch.setattr(engine.analysis_service, "_build_llm_client", lambda: model)
    monkeypatch.setattr(
        engine.branch_manager, "push_current_branch", lambda: engine.branch_manager.current_branch()
    )
    publisher = Mock()
    publisher.publish.return_value = PublishedChangeRequest(
        info=ChangeRequestInfo(iid=9, web_url="https://example/requests/9", title="Remove imports"),
        action="created",
    )
    engine.publish_service.change_request_publisher = publisher
    state_service = RunStateService(
        config,
        StateStore(
            tmp_path / config.state.path,
            base_branch="main",
            gitlab_project_id=None,
            sonarqube_project_key=None,
        ),
        AppState(repository=RepositoryState(base_branch="main")),
    )
    runner = WorkItemRemediationRunner(
        repo_root=tmp_path,
        config=config,
        execution_service=engine,
        remediation_control_plane=control_plane,
        run_state_service=state_service,
        batch_policy=policy(),
    )

    def select(**kwargs):
        records = storage.load_inventory(repository_scope=SCOPE).open_work_items
        normalized = [
            RemediationIntakeRecord(r.work_item, r.issue_number, r.issue_url) for r in records
        ]

        def persist(state):
            existing = storage.read_work_item(repository_scope=SCOPE, issue_number=1)
            result = storage.update_existing_work_item(
                repository_scope=SCOPE, existing=existing, work_item=state
            )
            return RemediationIntakeRecord(
                result.record.work_item, result.record.issue_number, result.record.issue_url
            )

        outcome = RemediationIntakeCoordinator(
            clock=lambda: NOW,
            eligibility=is_internal_remediation_execution_eligible,
            batch_policy=policy(),
        ).select_and_claim(records=normalized, persist_work_item=persist, **kwargs)
        return SimpleNamespace(
            selected_target=outcome.selected_target,
            claimed_work_item=outcome.selected_record.work_item,
            item_count=outcome.item_count,
            message="Selected batch",
        )

    monkeypatch.setattr(runner, "_select_and_claim", select)
    return runner, state_service, engine, model, publisher


def test_complete_batch_publishes_once_and_retains_full_machine_evidence(
    harness, tmp_path, monkeypatch
):
    runner, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    original = stored(harness)
    result = runner.run(record=runs.start_run("execution"), active_dry_run=False)
    actual = stored(harness)
    assert result.status == RunStatus.CHANGE_REQUEST_CREATED
    assert actual.status == "in_progress"
    assert actual.batch.members == original.batch.members
    assert actual.linked_change_request.number == 9
    assert actual.batch_attempt.coverage.addressable_ids == ("a", "b")
    assert actual.batch_attempt.run_id == "execution"
    assert actual.semantic_safety.assessment is not None
    assert actual.claim is None
    assert (tmp_path / "src/routes.py").read_text() == "value = 1\n"
    publisher.publish.assert_called_once()
    request = publisher.publish.call_args.args[0]
    assert "## Batch Targets" in request.description
    assert "2 of 2" in request.description
    assert "No validation commands configured" in request.description
    assert engine.branch_manager.current_branch() != "main"
    assert model.analyze_issue.call_args.args[0].batch_attempt is not None


def test_unaddressable_member_rejection_survives_issue_projection_without_accepted_coverage(
    harness, tmp_path, monkeypatch
):
    runner, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    original = stored(harness)
    reason = "Needs another file.\n## fake heading\n[click](https://evil) <b>do not execute</b>"
    accepted_analysis = model.analyze_issue.return_value
    model.analyze_issue.return_value = model.analyze_issue.return_value.model_copy(
        update={
            "batch_coverage": BatchAnalysisCoverage(
                addressable_ids=("a",),
                unaddressable=(BatchUnaddressableMember(finding_id="b", reason=reason),),
            )
        }
    )

    result = runner.run(record=runs.start_run("rejected"), active_dry_run=False)

    actual = stored(harness)
    assert result.status == RunStatus.FAILED
    assert actual.status == "blocked"
    assert actual.batch == original.batch
    assert actual.batch_attempt.coverage is None
    rejection = actual.execution_failure.batch_rejection
    assert rejection.reason == "unaddressable_members"
    assert rejection.members[0].finding_reference == "b"
    assert rejection.members[0].reason == reason
    body = harness[1].upsert_service.renderer.render_body(actual).split("## Machine State")[0]
    assert "### Batch Analysis Rejection" in body
    assert "Member: b" in body
    assert "Needs another file." in body
    assert "\n## fake heading" not in body
    assert "[click](https://evil)" not in body
    assert "<b>do not execute</b>" not in body
    assert "before requeueing" in body
    assert engine.branch_manager.current_branch() == "main"
    model.generate_structured_edit.assert_not_called()
    publisher.publish.assert_not_called()

    recovery = RecoveryDecisionService().decide(
        work_item=actual,
        request=RecoveryRequest(
            action="requeue",
            actor="operator",
            request_reference="rejection-corrected",
            expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(actual),
            occurred_at=actual.execution_failure.occurred_at,
        ),
        policy_eligible=True,
    )
    assert recovery.accepted
    storage = harness[2]
    storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=storage.read_work_item(repository_scope=SCOPE, issue_number=1),
        work_item=recovery.work_item,
    )
    model.analyze_issue.return_value = accepted_analysis
    result = runner.run(record=runs.start_run("corrected"), active_dry_run=False)
    final = stored(harness)
    assert result.status == RunStatus.CHANGE_REQUEST_CREATED
    assert final.execution_failure is None
    assert final.recovery_events[-1].prior_execution_failure.batch_rejection == rejection
    visible_body = (
        harness[1].upsert_service.renderer.render_body(final).split("## Machine State")[0]
    )
    assert "### Batch Analysis Rejection" not in visible_body


def test_validation_failure_rolls_back_entire_batch_and_never_publishes(
    harness, tmp_path, monkeypatch
):
    runner, runs, _, _, publisher = setup_execution(
        harness, tmp_path, monkeypatch, validation_commands=['python -c "raise SystemExit(1)"']
    )
    result = runner.run(record=runs.start_run("execution"), active_dry_run=False)
    state = stored(harness)
    assert result.status == RunStatus.FAILED
    assert state.status == "blocked"
    assert state.execution_failure is not None
    assert state.batch_attempt.coverage.addressable_ids == ("a", "b")
    assert (tmp_path / "src/routes.py").read_text() == "import os\nimport sys\nvalue = 1\n"
    publisher.publish.assert_not_called()


def test_failed_publication_preserves_committed_attempt_and_retry_precedence(
    harness, tmp_path, monkeypatch
):
    runner, runs, _, _, publisher = setup_execution(harness, tmp_path, monkeypatch)
    publisher.publish.side_effect = RuntimeError("provider unavailable")
    result = runner.run(record=runs.start_run("execution"), active_dry_run=False)
    state = stored(harness)
    assert result.status == RunStatus.FAILED
    assert state.status == "blocked"
    assert isinstance(state.publication_retry, PublicationRetryState)
    assert state.publication_retry.batch_attempt == state.batch_attempt
    assert state.publication_retry.commit_sha
    request = RecoveryRequest(
        action="requeue",
        actor="operator",
        request_reference="command-1",
        expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(state),
        occurred_at=NOW,
    )
    decision = RecoveryDecisionService().decide(
        work_item=state, request=request, policy_eligible=False
    )
    assert decision.accepted
    assert decision.plan == "retry_publication"
    assert decision.work_item.batch_attempt == state.batch_attempt
    assert decision.work_item.publication_retry == state.publication_retry


@pytest.mark.parametrize("verified", [True, False])
def test_publication_retry_after_absence_never_reanalyzes_or_falls_back(
    harness, tmp_path, monkeypatch, verified
):
    runner, runs, _, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    publisher.publish.side_effect = RuntimeError("provider unavailable")
    runner.run(record=runs.start_run("execution"), active_dry_run=False)
    state = stored(harness)
    original_attempt = state.batch_attempt
    absent_batch = state.batch.model_copy(
        update={
            "observations": tuple(
                o.model_copy(update={"last_confirmed_presence": "absent", "freshness": "current"})
                for o in state.batch.observations
            )
        }
    )
    state = state.model_copy(update={"batch": absent_batch, "status": "approved"})
    storage = harness[2]
    storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=storage.read_work_item(repository_scope=SCOPE, issue_number=1),
        work_item=state,
    )
    lookup = Mock()
    lookup.get_branch_head_sha.return_value = (
        state.publication_retry.commit_sha if verified else "drifted"
    )
    runner.publication_retry_service = PublicationRetryService(
        branch_revision_lookup=lookup, change_request_publisher=publisher
    )
    publisher.publish.side_effect = None
    result = runner.run(record=runs.start_run("publication-retry"), active_dry_run=False)
    final = stored(harness)
    assert final.batch_attempt == original_attempt
    assert final.resolution is None
    assert model.analyze_issue.call_count == 1
    assert publisher.publish.call_count == (2 if verified else 1)
    if verified:
        assert result.status == RunStatus.CHANGE_REQUEST_CREATED
        assert final.linked_change_request.number == 9
    else:
        assert result.status == RunStatus.FAILED
        assert final.status == "blocked"
        assert final.publication_retry == state.publication_retry


def test_authorized_fresh_all_absent_recovery_completes_without_model_or_publication(
    harness, tmp_path, monkeypatch
):
    runner, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    state = stored(harness)
    absent_batch = state.batch.model_copy(
        update={
            "observations": tuple(
                o.model_copy(update={"last_confirmed_presence": "absent", "freshness": "current"})
                for o in state.batch.observations
            )
        }
    )
    blocked = state.model_copy(update={"status": "blocked", "batch": absent_batch})
    request = RecoveryRequest(
        action="requeue",
        actor="operator",
        request_reference="fresh-1",
        expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(blocked),
        occurred_at=NOW,
    )
    recovery = RecoveryDecisionService().decide(
        work_item=blocked, request=request, policy_eligible=False
    )
    assert recovery.accepted and recovery.plan == "start_fresh"
    harness[2].update_existing_work_item(
        repository_scope=SCOPE,
        existing=harness[2].read_work_item(repository_scope=SCOPE, issue_number=1),
        work_item=recovery.work_item,
    )
    result = runner.run(record=runs.start_run("fresh-recovery"), active_dry_run=False)
    final = stored(harness)
    assert result.status == RunStatus.SELECTED
    assert final.status == "completed"
    assert final.resolution == "no_longer_detected"
    assert final.attempt_number == 2
    model.analyze_issue.assert_not_called()
    publisher.publish.assert_not_called()
    assert engine.branch_manager.current_branch() == "main"


@pytest.mark.parametrize("observation_change", ["detected", "unknown", "unavailable"])
def test_all_absent_recovery_reports_refused_or_unconfirmed_completion(
    harness, tmp_path, monkeypatch, observation_change
):
    runner, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    storage = harness[2]
    initial = stored(harness)
    absent = initial.model_copy(
        update={
            "batch": initial.batch.model_copy(
                update={
                    "observations": tuple(
                        observation.model_copy(update={"last_confirmed_presence": "absent"})
                        for observation in initial.batch.observations
                    )
                }
            )
        }
    )
    storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=storage.read_work_item(repository_scope=SCOPE, issue_number=1),
        work_item=absent,
    )
    select = runner._select_and_claim

    def select_then_refresh(**kwargs):
        selection = select(**kwargs)
        if observation_change == "unavailable":
            monkeypatch.setattr(
                harness[1],
                "find_open_work_item_by_source",
                Mock(side_effect=RuntimeError("unavailable")),
            )
            return selection
        current = selection.claimed_work_item
        observations = tuple(
            observation.model_copy(
                update=(
                    {"last_confirmed_presence": "detected"}
                    if observation_change == "detected"
                    else {"freshness": "unknown"}
                )
            )
            for observation in current.batch.observations
        )
        storage.update_existing_work_item(
            repository_scope=SCOPE,
            existing=storage.read_work_item(repository_scope=SCOPE, issue_number=1),
            work_item=current.model_copy(
                update={"batch": current.batch.model_copy(update={"observations": observations})}
            ),
        )
        return selection

    monkeypatch.setattr(runner, "_select_and_claim", select_then_refresh)
    record = runs.start_run("stale-completion")
    result = runner.run(record=record, active_dry_run=False)

    final = stored(harness)
    assert result.status == RunStatus.FAILED
    assert record.failure.stage.value == "control_plane_update"
    assert "All original batch members are no longer detected" not in result.message
    assert final.status == "in_progress"
    assert final.resolution is None
    assert final.claim.run_id == "stale-completion"
    if observation_change == "detected":
        assert final.batch.observations[0].last_confirmed_presence == "detected"
    elif observation_change == "unknown":
        assert final.batch.observations[0].freshness == "unknown"
    assert engine.branch_manager.current_branch() == "main"
    model.analyze_issue.assert_not_called()
    publisher.publish.assert_not_called()


def test_all_absent_dry_run_previews_without_completion_write(harness, tmp_path, monkeypatch):
    runner, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    initial = stored(harness)
    state = initial.model_copy(
        update={
            "batch": initial.batch.model_copy(
                update={
                    "observations": tuple(
                        observation.model_copy(update={"last_confirmed_presence": "absent"})
                        for observation in initial.batch.observations
                    )
                }
            )
        }
    )
    storage = harness[2]
    storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=storage.read_work_item(repository_scope=SCOPE, issue_number=1),
        work_item=state,
    )
    harness[0].calls.clear()
    result = runner.run(record=runs.start_run("preview"), active_dry_run=True)
    assert result.status == RunStatus.SELECTED
    assert "Dry run:" in result.message
    assert "requires a live authoritative absence check" in result.message
    assert not any(
        action in {"update", "create", "close", "reopen"} for action, _ in harness[0].calls
    )
    assert stored(harness) == state
    assert engine.branch_manager.current_branch() == "main"
    model.analyze_issue.assert_not_called()
    publisher.publish.assert_not_called()


def test_internal_batch_dry_run_never_claims_or_writes(harness):
    state = batch_state(status="approved")
    seed(harness, state)
    clock = Mock(side_effect=AssertionError("clock read"))
    persist = Mock(side_effect=AssertionError("write attempted"))
    result = RemediationIntakeCoordinator(
        clock=clock, eligibility=is_internal_remediation_execution_eligible, batch_policy=policy()
    ).select_and_claim(
        records=[RemediationIntakeRecord(state, 1, "https://example/issues/1")],
        persist_work_item=persist,
        persist=False,
        run_id="preview",
    )
    assert result.selected_target.batch_attempt.members == state.batch.members
    assert result.selected_record.work_item.claim is None
    assert stored(harness) == state
    clock.assert_not_called()
    persist.assert_not_called()


def test_same_request_revision_uses_checked_out_context_and_original_batch_scope(
    harness, tmp_path, monkeypatch
):
    runner, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    runner.run(record=runs.start_run("execution"), active_dry_run=False)
    state = stored(harness)
    original_attempt = state.batch_attempt
    branch = engine.branch_manager.current_branch()
    remote = tmp_path.parent / f"{tmp_path.name}-remote.git"

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "--bare", str(remote))
    git("remote", "add", "origin", str(remote))
    (tmp_path / "AGENTS.md").write_text("Preserve revision-only guidance.\n")
    git("add", "AGENTS.md")
    git("commit", "-m", "revision guidance")
    reviewed_sha = git("rev-parse", "HEAD")
    git("push", "-u", "origin", branch)
    git("checkout", "main")
    monkeypatch.setattr(
        engine.branch_manager,
        "push_current_branch",
        BranchManager.push_current_branch.__get__(engine.branch_manager),
    )
    feedback = ProjectedReviewFeedback(
        summary="Adjust the constant",
        finding_count=1,
        findings=[
            ProjectedReviewFinding(
                title="Adjust constant",
                file_path="src/routes.py",
                line_start=1,
                evidence="value = 1",
                explanation="Expected updated constant",
                suggested_follow_up="Use value = 2",
            )
        ],
    )
    queued = state.model_copy(
        update={
            "status": "review_revision_queued",
            "claim": None,
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha=reviewed_sha,
                follow_up_required=True,
                feedback=feedback,
            ),
            "review_revision_request": ReviewRevisionRequest(
                actor="operator",
                request_reference="revision-command",
                occurred_at=NOW,
                reviewed_sha=reviewed_sha,
            ),
        }
    )
    harness[2].update_existing_work_item(
        repository_scope=SCOPE,
        existing=harness[2].read_work_item(repository_scope=SCOPE, issue_number=1),
        work_item=queued,
    )
    runner.change_request_state_lookup = lambda number: ChangeRequestState(
        iid=9,
        web_url="https://example/requests/9",
        source_branch=branch,
        head_sha=reviewed_sha,
        state="opened",
    )
    model.generate_structured_edit.return_value = StructuredEditProposal(
        issue_key="batch",
        edits=[
            TextEdit(file_path="src/routes.py", search_text="value = 1", replace_text="value = 2")
        ],
        commit_message="Adjust constant",
        change_request_title="Adjust constant",
        change_request_description="Correct the reviewed local constant.",
    )
    result = runner.run(record=runs.start_run("revision"), active_dry_run=False)
    final = stored(harness)
    assert result.status == RunStatus.CHANGE_REQUEST_CREATED
    assert final.status == "in_progress"
    assert final.linked_change_request == state.linked_change_request
    assert final.batch_attempt.members == original_attempt.members
    assert final.batch_attempt.run_id == original_attempt.run_id
    assert final.review_revision_request is None
    assert final.last_revision_command.request_reference == "revision-command"
    publisher.publish.assert_called_once()
    revision_context = model.analyze_issue.call_args.args[1]
    assert revision_context.snippet.content == "   1: value = 1"
    assert "revision-only guidance" in revision_context.repository_guidance[0].summary
    assert revision_context.prior_review_feedback.findings[0].evidence == "value = 1"
    assert git("show", f"origin/{branch}:src/routes.py") == "value = 2"


def test_link_sync_recovers_batch_evidence_after_publish_start_projection_failure(
    harness, tmp_path, monkeypatch
):
    runner, runs, _, _, publisher = setup_execution(harness, tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner.remediation_control_plane,
        "mark_publish_started",
        Mock(side_effect=RuntimeError("temporary projection failure")),
    )
    result = runner.run(record=runs.start_run("execution"), active_dry_run=False)
    state = stored(harness)
    assert result.status == RunStatus.CHANGE_REQUEST_CREATED
    assert state.linked_change_request.number == 9
    assert len(state.batch.members) == 2
    assert state.batch_attempt.coverage.addressable_ids == ("a", "b")
    assert state.semantic_safety.assessment is not None
    publisher.publish.assert_called_once()


def test_revision_missing_attempt_returns_to_feedback_required_before_model_calls(
    harness, tmp_path, monkeypatch
):
    runner, runs, _, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    state = stored(harness)
    queued = state.model_copy(
        update={
            "status": "review_revision_queued",
            "linked_change_request": ChangeRequestRef(
                number=9, web_url="https://example/requests/9"
            ),
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha="reviewed",
                follow_up_required=True,
                feedback=ProjectedReviewFeedback(
                    summary="Review feedback",
                    finding_count=1,
                    findings=[
                        ProjectedReviewFinding(
                            title="Adjust constant",
                            file_path="src/routes.py",
                            evidence="constant",
                            explanation="Incorrect constant",
                            suggested_follow_up="Adjust the constant",
                        )
                    ],
                ),
            ),
            "review_revision_request": ReviewRevisionRequest(
                actor="operator",
                request_reference="revision-command",
                occurred_at=NOW,
                reviewed_sha="reviewed",
            ),
        }
    )
    harness[2].update_existing_work_item(
        repository_scope=SCOPE,
        existing=harness[2].read_work_item(repository_scope=SCOPE, issue_number=1),
        work_item=queued,
    )
    result = runner.run(record=runs.start_run("missing-revision-evidence"), active_dry_run=False)
    final = stored(harness)
    assert result.status == RunStatus.FAILED
    assert final.status == "review_feedback_required"
    assert final.linked_change_request == queued.linked_change_request
    assert final.projected_review == queued.projected_review
    assert final.execution_failure is not None
    assert final.review_revision_request is None
    assert final.claim is None
    model.analyze_issue.assert_not_called()
    publisher.publish.assert_not_called()

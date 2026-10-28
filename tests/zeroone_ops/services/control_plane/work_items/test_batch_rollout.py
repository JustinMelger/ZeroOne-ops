"""Exercise rollout through public provider services, without provider connections."""

from unittest.mock import Mock

import pytest

from zeroone_ops.models.batch_execution import BatchAnalysisCoverage
from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.finding import FindingCollectionMetadata, FindingCollectionResult
from zeroone_ops.models.state import RunStatus
from zeroone_ops.models.work_item import PublicationRetryState
from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubOperationalSummaryRenderer,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_renderer import (
    GitLabOperationalSummaryRenderer,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    OperationalSummaryView,
)
from zeroone_ops.services.control_plane.overview.operational_summary_parser import (
    OperationalSummaryParser,
)
from zeroone_ops.services.control_plane.work_items.batch_work_item_view import (
    build_batch_work_item_view,
)
from zeroone_ops.services.control_plane.work_items.github_remediation_intake_service import (
    GitHubRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_remediation_intake_service import (
    GitLabRemediationIntakeService,
)
from zeroone_ops.services.intake.issue_intake import SyncIssueCollectionResult
from zeroone_ops.services.remediation.batch_execution_scope_service import (
    BatchExecutionScopeService,
)
from zeroone_ops.services.remediation.github_remediation_runner import GitHubRemediationRunner
from zeroone_ops.services.remediation.gitlab_remediation_runner import GitLabRemediationRunner
from zeroone_ops.services.shared.projection_payload import (
    BATCH_PAYLOAD_MAX_BYTES,
    ProjectionSizeExceeded,
    validate_batch_payload,
)
from zeroone_ops.services.workflows.finding_sync_workflow import FindingSyncWorkflow
from zeroone_ops.services.workflows.operational_summary import build_finding_sync_observation
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context

from .test_batch_execution_provider_parity import setup_execution
from .test_batch_finding_sync_coordinator import (
    SCOPE,
    batch_state,
    finding,
    policy,
    seed,
    stored,
    sync,
)
from .test_batch_finding_sync_coordinator import harness as harness


def intake(harness, loader, *, persist=True):
    client, service, _ = harness
    intake_type = (
        GitHubRemediationIntakeService
        if client.provider == "github"
        else GitLabRemediationIntakeService
    )
    return intake_type(work_item_service=service, load_batch_policy=loader).select_and_claim(
        **{"repository_id" if client.provider == "github" else "project_id": SCOPE},
        persist=persist,
        run_id="live-intake",
    )


@pytest.mark.parametrize("persist", [False, True])
def test_public_intake_loads_one_policy_snapshot_and_preserves_all_members(harness, persist):
    original = batch_state(members=[finding("a"), finding("b")], status="approved")
    seed(harness, original)
    loader = Mock(return_value=policy())
    result = intake(harness, loader, persist=persist)
    loader.assert_called_once_with()
    assert result.batch_policy == policy()
    assert len(result.selected_target.batch_attempt.members) == 2
    assert result.selected_target.batch.members == original.batch.members
    assert stored(harness).batch.members == original.batch.members
    assert (stored(harness).claim is not None) == persist


def test_policy_failure_withholds_fresh_batch_but_not_independent_single(harness):
    seed(harness, batch_state(status="approved"))
    single = batch_state(members=[finding("single", path="src/other.py")], status="approved")
    single = single.model_copy(
        update={
            "batch": None,
            "source": single.source.model_copy(update={"source_item_key": "single"}),
        }
    )
    seed(harness, single)
    loader = Mock(side_effect=RuntimeError("policy unavailable"))
    result = intake(harness, loader)
    assert result.claimed_work_item.work_item_id == single.work_item_id
    assert stored(harness, 1).claim is None
    loader.assert_called_once_with()


def test_public_provider_runner_executes_complete_batch(harness, tmp_path, monkeypatch):
    previous, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    runner_type = (
        GitHubRemediationRunner if harness[0].provider == "github" else GitLabRemediationRunner
    )
    loader = Mock(return_value=policy())
    runner = runner_type(
        repo_root=tmp_path,
        config=previous.config,
        **{"repository_id" if harness[0].provider == "github" else "project_id": SCOPE},
        work_item_service=harness[1],
        run_state_service=runs,
        execution_service=engine,
        remediation_control_plane=previous.remediation_control_plane,
        load_batch_policy=loader,
    )
    result = runner.run(record=runs.start_run("public-batch"), active_dry_run=False)
    assert result.status == RunStatus.CHANGE_REQUEST_CREATED
    assert stored(harness).batch_attempt.coverage.addressable_ids == ("a", "b")
    assert stored(harness).linked_change_request.number == 9
    assert len(model.analyze_issue.call_args.args[0].batch_attempt.members) == 2
    publisher.publish.assert_called_once()
    loader.assert_called_once_with()


def test_batch_view_keeps_policy_unknown_and_observations_distinct():
    state = batch_state(members=[finding("a"), finding("b")])
    observations = state.batch.observations
    state = state.model_copy(
        update={
            "batch": state.batch.model_copy(
                update={
                    "observations": (
                        observations[0],
                        observations[1].model_copy(
                            update={
                                "last_confirmed_presence": "absent",
                                "freshness": "unknown",
                            }
                        ),
                    )
                }
            )
        }
    )
    view = build_batch_work_item_view(state)
    assert (view.original, view.detected, view.absent, view.unknown_freshness) == (2, 1, 1, 1)
    assert view.planned_targeted is None and view.policy_excluded is None
    evaluated = build_batch_work_item_view(state, policy("high"))
    assert (evaluated.planned_targeted, evaluated.policy_excluded) == (0, 1)


def test_batch_renderer_is_bounded_and_retains_authoritative_members(harness):
    members = [
        finding(f"id-{i}").model_copy(update={"summary": "<details>|`[link]" * 30})
        for i in range(12)
    ]
    state = batch_state(members=members)
    renderer = harness[1].upsert_service.renderer
    body = renderer.render_body(state)
    visible = body.split("## Machine State")[0]
    assert renderer.render_title(state) == "ZeroOne Ops: F401 - 12 findings in routes.py"
    assert "2 display rows omitted" in visible
    assert "Policy-excluded: not evaluated" in visible
    assert "<details>|`[link]" not in visible
    assert visible.count("| detected | current |") == 10
    parsed = harness[1].upsert_service.parser.parse_work_item_state(body)
    assert parsed.batch == state.batch


@pytest.mark.parametrize("persist", [False, True])
def test_oversized_new_batch_is_backlog_without_create(harness, persist):
    member = finding().model_copy(update={"summary": "x" * 65_000})
    result = sync(harness, [member], persist=persist)
    assert result.backlog_reason_counts == {"projection_size_exceeded": 1}
    assert result.projection_warning_count == 1
    assert result.promoted_count == 0
    assert harness[0].create_attempts == 0


def test_payload_limit_counts_utf8_bytes_without_truncation():
    value = "é" * (BATCH_PAYLOAD_MAX_BYTES // 2)
    assert validate_batch_payload(value) is value
    with pytest.raises(ProjectionSizeExceeded):
        validate_batch_payload(value + "a")


def test_summary_total_uses_inventory_not_batch_work_item_units(harness):
    findings = [finding(f"id-{i}") for i in range(23)]
    result = sync(harness, findings)
    observation = build_finding_sync_observation(result)
    assert (observation.total_findings, observation.promoted_work_items) == (23, 1)
    assert (observation.promoted_findings, observation.backlog_only_findings) == (5, 18)


def test_oversized_claim_prevents_analysis_and_publication(harness, tmp_path, monkeypatch):
    previous, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    state = stored(harness).model_copy(update={"detail": "x" * 65_000})
    body = "## Machine State\n\n" + "\n".join(
        harness[1].upsert_service.renderer._render_state_block(state)
    )
    field = "body" if harness[0].provider == "github" else "description"
    harness[0].issues[1] = harness[0].issues[1].model_copy(update={field: body})
    before = dict(harness[0].issues)
    with pytest.raises(ProjectionSizeExceeded):
        intake(harness, Mock(return_value=policy()))
    monkeypatch.setattr(
        previous,
        "_select_and_claim",
        lambda **kwargs: intake(harness, Mock(return_value=policy())),
    )
    result = previous.run(record=runs.start_run("oversized-claim"), active_dry_run=False)
    assert result.status == RunStatus.FAILED
    assert "Batch claim withheld" in result.message
    assert harness[0].issues == before
    assert stored(harness).claim is None
    model.analyze_issue.assert_not_called()
    publisher.publish.assert_not_called()


def test_existing_oversized_projection_keeps_closed_authority(harness):
    original = batch_state(status="capacity_deferred")
    seed(harness, original, is_open=False)
    large = original.model_copy(update={"detail": "x" * 65_000})
    field = "body" if harness[0].provider == "github" else "description"
    harness[0].issues[1] = (
        harness[0]
        .issues[1]
        .model_copy(
            update={
                field: "## Machine State\n\n"
                + "\n".join(harness[1].upsert_service.renderer._render_state_block(large))
            }
        )
    )
    before = dict(harness[0].issues)
    result = sync(harness, [finding()])
    assert result.projection_warning_count == 1
    assert harness[0].issues == before
    assert not harness[0].open[1]
    assert not any(action in {"update", "reopen"} for action, _ in harness[0].calls)


def test_oversized_description_never_pushes_or_publishes(harness, tmp_path, monkeypatch):
    runner, runs, engine, model, publisher = setup_execution(harness, tmp_path, monkeypatch)
    proposal = model.generate_structured_edit.return_value
    model.generate_structured_edit.return_value = proposal.model_copy(
        update={
            "change_request_description": "x" * 65_000,
        }
    )
    push = Mock()
    monkeypatch.setattr(engine.branch_manager, "push_current_branch", push)
    result = runner.run(record=runs.start_run("oversized-publish"), active_dry_run=False)
    assert result.status == RunStatus.FAILED
    push.assert_not_called()
    publisher.publish.assert_not_called()
    assert stored(harness).status == "blocked"


def test_full_issue_body_byte_boundary_is_checked_after_serialization(harness):
    renderer = harness[1].upsert_service.renderer
    state = batch_state().model_copy(update={"detail": ""})
    overhead = len(renderer.render_body(state).encode("utf-8"))
    state = state.model_copy(update={"detail": "x" * (BATCH_PAYLOAD_MAX_BYTES - overhead)})
    assert len(renderer.render_body(state).encode("utf-8")) == BATCH_PAYLOAD_MAX_BYTES
    with pytest.raises(ProjectionSizeExceeded):
        renderer.render_body(state.model_copy(update={"detail": state.detail + "é"}))


def test_policy_failure_has_no_claim_or_clock_read_when_only_fresh_batches_exist(harness):
    seed(harness, batch_state(status="approved"))
    loader = Mock(side_effect=RuntimeError("secret-provider-details"))
    before = dict(harness[0].issues)
    result = intake(harness, loader)
    assert result.selected_target is None
    assert harness[0].issues == before
    assert harness[0].calls == []


def test_batch_closed_between_selection_and_claim_is_not_recreated(harness):
    seed(harness, batch_state(status="approved"))

    def close_during_policy_lookup():
        harness[0].open[1] = False
        return policy()

    with pytest.raises(RuntimeError, match="Selected open batch is unavailable"):
        intake(harness, close_during_policy_lookup)
    assert harness[0].create_attempts == 0
    assert stored(harness).claim is None


def test_batch_changed_between_selection_and_claim_is_not_overwritten(harness):
    original = batch_state(status="approved")
    seed(harness, original)

    def refresh_during_policy_lookup():
        changed = original.model_copy(
            update={
                "batch": original.batch.model_copy(
                    update={
                        "observations": tuple(
                            o.model_copy(update={"freshness": "unknown"})
                            for o in original.batch.observations
                        ),
                    }
                )
            }
        )
        storage = harness[2]
        storage.update_existing_work_item(
            repository_scope=SCOPE,
            existing=storage.read_work_item(repository_scope=SCOPE, issue_number=1),
            work_item=changed,
        )
        return policy()

    with pytest.raises(RuntimeError, match="Batch changed before claim"):
        intake(harness, refresh_during_policy_lookup)
    assert stored(harness).batch.observations[0].freshness == "unknown"
    assert stored(harness).claim is None


def test_recorded_publication_scope_never_requires_policy_lookup(harness):
    original = batch_state(status="approved")
    attempt = BatchExecutionScopeService().resolve(original, policy()).attempt
    attempt = attempt.model_copy(update={"coverage": BatchAnalysisCoverage(addressable_ids=("a",))})
    retry = PublicationRetryState(
        branch_name="zeroone/remediation/a",
        commit_sha="a" * 40,
        reason="change_request_publish_failed",
        batch_attempt=attempt,
    )
    original = original.model_copy(update={"batch_attempt": attempt, "publication_retry": retry})
    seed(harness, original)
    seed(harness, batch_state(members=[finding("other", path="src/other.py")], status="approved"))
    loader = Mock(side_effect=AssertionError("Recorded scope must not load policy"))
    result = intake(harness, loader)
    assert result.selected_target.batch_attempt == attempt
    assert result.claimed_work_item.publication_retry == retry
    loader.assert_not_called()


def test_batch_summary_counters_roundtrip_with_explicit_units(harness):
    result = sync(harness, [finding(str(i)) for i in range(23)])
    observation = build_finding_sync_observation(result)
    renderer = (
        GitHubOperationalSummaryRenderer()
        if harness[0].provider == "github"
        else GitLabOperationalSummaryRenderer()
    )
    body = renderer.render(
        OperationalSummaryView(
            policy_issue_url=None,
            work_item_counts={},
            active_change_requests=[],
            recent_outcomes=[],
            latest_finding_sync=observation,
        )
    )
    assert OperationalSummaryParser().parse_latest_finding_sync(body) == observation
    assert "Promoted work items: `1`" in body
    assert "Promoted finding members: `5`" in body
    assert "Findings: `23`" in body
    assert "id-0" not in body


def test_repeated_batch_sync_summary_excludes_active_members(harness):
    findings = [finding(str(i)) for i in range(23)]
    sync(harness, findings)
    result = sync(harness, findings)
    observation = build_finding_sync_observation(result)
    renderer = (
        GitHubOperationalSummaryRenderer()
        if harness[0].provider == "github"
        else GitLabOperationalSummaryRenderer()
    )
    body = renderer.render(
        OperationalSummaryView(
            policy_issue_url=None,
            work_item_counts={"approved": 1},
            active_change_requests=[],
            recent_outcomes=[],
            latest_finding_sync=observation,
        )
    )
    assert OperationalSummaryParser().parse_latest_finding_sync(body) == observation
    assert observation.backlog_only_findings == 18
    assert observation.total_findings == 23
    assert "Promoted work items: `0`" in body
    assert "Promoted finding members: `0`" in body
    assert "owned" not in observation.backlog_reason_counts


def test_workflow_output_and_summary_publication_exclude_active_backlog(
    harness, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    provider = harness[0].provider
    findings = [finding("a"), finding("b")]
    sync(harness, findings)
    connection = (
        GitHubConnectionConfig(
            api_url="https://example/api",
            server_url="https://example",
            token="test",
            repository=SCOPE,
        )
        if provider == "github"
        else GitLabConnectionConfig(url="https://example", token="test", project_id=SCOPE)
    )
    client_type = "GitHubWorkItemClient" if provider == "github" else "GitLabWorkItemClient"
    monkeypatch.setattr(
        f"zeroone_ops.services.workflows.finding_sync_workflow.{client_type}",
        lambda config: harness[0],
    )
    summary_publisher = Mock(return_value=None)
    policy_builder = Mock(return_value=Mock(load_policy_state=Mock(return_value=policy())))
    workflow = FindingSyncWorkflow(
        config=AppConfig.model_validate(
            {
                "platform": provider,
                "base_branch": "main",
                "remediation": {"target_branch": "main"},
                **({"gitlab": {"control_plane_mode": "issues"}} if provider == "gitlab" else {}),
            }
        ),
        dry_run=False,
        build_run_id=lambda: "repeat-sync",
        build_context=build_workflow_run_context,
        load_github_config=lambda: connection,
        load_gitlab_config=lambda: connection,
        build_github_policy_issue_service=policy_builder,
        build_gitlab_policy_issue_service=policy_builder,
        publish_github_summary=summary_publisher,
        publish_gitlab_summary=summary_publisher,
    )
    monkeypatch.setattr(
        workflow,
        "_collect",
        lambda context: SyncIssueCollectionResult(
            finding_collection=FindingCollectionResult(
                findings=findings,
                metadata=FindingCollectionMetadata(
                    source_id="finding_sync", managed_source_ids=["ruff-sarif"]
                ),
            ),
            issue_count=2,
            message="synced",
        ),
    )
    summary = workflow.run()
    assert summary.status == RunStatus.SYNCED
    assert "0 findings remain backlog-only" in summary.message
    assert "0 selected finding members" in summary.message
    assert "backlog reasons: none" in summary.message
    observation = summary_publisher.call_args.kwargs["latest_finding_sync"]
    assert observation.total_findings == 2
    assert observation.promoted_work_items == 0
    assert observation.backlog_only_findings == 0

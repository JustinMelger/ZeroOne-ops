from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_batch import (
    BatchMemberObservation,
    FindingBatchGroup,
    WorkItemBatch,
)
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.policy import (
    PolicyIssueClassStateEntry,
    PolicySeverityStateEntry,
    PolicyState,
)
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemClaim,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.intake.finding_batch_ownership import (
    is_safe_unstarted_batch,
    retains_finding_batch_ownership,
)
from zeroone_ops.services.intake.finding_batch_promotion_service import FindingBatchPromotionService

SCOPE = "team/repo"
NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _finding(
    identifier="a",
    *,
    source="ruff-sarif",
    severity="medium",
    path="src/routes.py",
    rule="F401",
    **requirements,
):
    return NormalizedFinding(
        finding_id=identifier,
        source_id=source,
        severity=severity,
        title="Unused import",
        summary=f"Unused import {identifier}",
        repository_path=path,
        line_start=10,
        remediation_context=RemediationContext(
            category="static_analysis_fix", diagnostic_code=rule, **requirements
        ),
    )


def _record(
    number=1,
    *,
    members=None,
    status="candidate",
    is_open=True,
    scope=SCOPE,
    presence="detected",
    freshness="current",
    **changes,
):
    members = members or (_finding(),)
    first = members[0]
    identifier = f"00000000000040008000{number:012d}"
    batch = WorkItemBatch(
        group=FindingBatchGroup(
            repository_scope=scope,
            file_path=first.repository_path,
            source_id=first.source_id,
            rule_id=first.remediation_context.diagnostic_code,
        ),
        members=members,
        observations=tuple(
            BatchMemberObservation(
                finding_id=member.finding_id,
                last_confirmed_presence=presence,
                freshness=freshness,
                sync_run_id="current",
                observed_at=NOW,
                last_confirmed_sync_run_id="confirmed",
                last_confirmed_finding=member,
            )
            for member in members
        ),
    )
    state = WorkItemState(
        work_item_id=f"work-{identifier}",
        kind="remediation",
        status=status,
        source=WorkItemSourceRef(
            source=first.source_id, source_item_key=f"batch-v1:{identifier}", repository_scope=scope
        ),
        file_path=first.repository_path,
        severity=first.severity,
        summary="Batch",
        remediation_context=first.remediation_context,
        batch=batch,
    ).model_copy(update=changes)
    return FindingSyncRecord(
        work_item=state,
        issue_number=number,
        issue_url=f"https://example/issues/{number}",
        is_open=is_open,
    )


def _single(number=1, *, finding=None, **changes):
    finding = finding or _finding()
    is_open = changes.pop("is_open", True)
    scope = changes.pop("scope", SCOPE)
    state = WorkItemState(
        work_item_id=f"single-{number}",
        kind="remediation",
        status=changes.pop("status", "candidate"),
        source=WorkItemSourceRef(
            source=finding.source_id,
            source_item_key=finding.finding_id,
            repository_scope=scope,
        ),
        file_path=finding.repository_path,
        severity=finding.severity,
        summary=finding.title,
        remediation_context=finding.remediation_context,
        **changes,
    )
    return FindingSyncRecord(
        work_item=state,
        issue_number=number,
        issue_url=f"https://example/issues/{number}",
        is_open=is_open,
    )


def _policy(*severities):
    return PolicyState(
        severity_policy=[
            PolicySeverityStateEntry(severity=severity, enabled=True)
            for severity in (severities or ("low", "medium", "high"))
        ]
    )


def _plan(findings=(), records=(), **changes):
    options = dict(
        findings=findings,
        records=records,
        repository_scope=SCOPE,
        policy_state=_policy(),
        max_active_work_items=5,
    )
    return FindingBatchPromotionService().plan(**(options | changes))


def _reasons(plan):
    return {decision.identity[2]: decision.reason for decision in plan.decisions}


def test_default_ten_members_and_thirteen_overflow_consume_one_slot():
    findings = [_finding(f"f{number:02d}") for number in range(23)]
    plan = _plan(list(reversed(findings)))
    assert len(plan.selected_new) == 1
    assert [member.finding_id for member in plan.selected_new[0].members] == [
        f"f{number:02d}" for number in range(10)
    ]
    assert list(_reasons(plan).values()).count("selected") == 10
    assert list(_reasons(plan).values()).count("batch_overflow") == 13
    assert plan == _plan(findings)


@pytest.mark.parametrize("limit", [1, 10])
def test_one_new_unit_per_group_and_incompatible_requirements_fall_back_to_singles(limit):
    findings = [_finding("b", constraints="keep comments"), _finding("a")]
    plan = _plan(findings, max_findings_per_work_item=limit)
    assert len(plan.selected_new) == 1
    assert [member.finding_id for member in plan.selected_new[0].members] == ["a"]
    assert _reasons(plan)["b"] == "group_reserved"


def test_limit_one_disables_multifinding_even_when_requirements_match():
    plan = _plan([_finding("b"), _finding("a")], max_findings_per_work_item=1)
    assert len(plan.selected_new) == 1
    assert len(plan.selected_new[0].members) == 1


def test_requirements_normalization_preserves_evidence_and_command_order():
    a = _finding("a", acceptance_criteria=["a", "b", "a"])
    b = _finding("b", acceptance_criteria=["b", "a"])
    b.remediation_context.category = "lint_fix"
    assert len(_plan([a, b]).selected_new[0].members) == 2
    a.remediation_context.validation_commands = ["one", "two"]
    b.remediation_context.validation_commands = ["two", "one"]
    assert len(_plan([a, b]).selected_new[0].members) == 1


def test_source_priority_precedes_severity_and_other_groups_compete():
    findings = [
        _finding("high", source="mypy-sarif", severity="high"),
        _finding("medium", source="semgrep-sarif"),
        _finding("low", severity="low", path="src/other.py"),
    ]
    plan = _plan(findings, max_active_work_items=1, source_priorities={"semgrep-sarif": 10})
    assert plan.selected_new[0].members[0].source_id == "semgrep-sarif"
    assert len(_plan(findings).selected_new) == 3


def test_ties_use_group_and_member_identity_and_highest_member_severity():
    findings = [
        _finding("b", severity="low"),
        _finding("a", severity="high"),
        _finding("c", path="src/z.py", severity="high"),
    ]
    plan = _plan(findings, max_active_work_items=1)
    assert [member.finding_id for member in plan.selected_new[0].members] == ["a", "b"]


def test_dismissal_suppresses_only_exact_members_and_releases_group():
    dismissed = _record(status="dismissed", is_open=False)
    plan = _plan([_finding("a"), _finding("b")], [dismissed])
    assert _reasons(plan) == {"a": "dismissed", "b": "selected"}
    assert len(plan.selected_new[0].members) == 1


@pytest.mark.parametrize("is_open", [True, False])
def test_single_dismissal_is_scoped_by_repository_source_and_identity(is_open):
    records = [_single(status="dismissed", is_open=is_open)]
    findings = [_finding("a"), _finding("b"), _finding("a", source="mypy-sarif")]
    plan = _plan(findings, records)
    assert len(plan.selected_new) == 2
    assert _plan([_finding()], [_single(scope="other/repo", status="dismissed")]).selected_new


def test_policy_filters_members_before_grouping():
    plan = _plan([_finding("a", severity="high"), _finding("b")], policy_state=_policy("medium"))
    assert _reasons(plan) == {"a": "severity_disabled", "b": "selected"}
    assert len(plan.selected_new[0].members) == 1


def test_rule_exclusion_is_applied_before_batching_and_scoped_to_source():
    policy = _policy()
    policy.issue_class_exclusions.append(
        PolicyIssueClassStateEntry(source="ruff-sarif", issue_key="F401", reason="Noisy")
    )
    plan = _plan([_finding(), _finding("other", source="semgrep-sarif")], policy_state=policy)
    assert _reasons(plan) == {"a": "issue_class_excluded", "other": "selected"}


def test_policy_ineligible_active_work_still_consumes_its_protected_slot():
    active = _record(status="approved", members=(_finding(severity="high"),))
    plan = _plan(
        [_finding("other", path="src/other.py")],
        [active],
        policy_state=_policy("medium"),
        max_active_work_items=1,
    )
    assert plan.active_work_item_count == 1
    assert not plan.selected_new


@pytest.mark.parametrize(
    "status", ["approved", "in_progress", "review_feedback_required", "review_revision_queued"]
)
def test_active_units_remain_capacity_consumers_without_demotion(status):
    record = _record(status=status)
    plan = _plan([_finding("new", path="src/other.py")], [record, record], max_active_work_items=1)
    assert plan.active_work_item_count == 1
    assert not plan.selected_new
    assert not plan.selected_existing
    assert record.work_item.status == status


def test_existing_singles_are_not_consolidated_and_use_individual_slots():
    findings = [_finding("a"), _finding("b"), _finding("c")]
    records = [
        _single(number, finding=finding, status="approved")
        for number, finding in enumerate(findings, 1)
    ]
    plan = _plan([*findings, _finding("d")], records)
    assert plan.active_work_item_count == 3
    assert not plan.selected_new
    assert not plan.conflicts
    assert _reasons(plan)["d"] == "group_reserved"


@pytest.mark.parametrize("status", ["candidate", "policy_deferred", "capacity_deferred"])
def test_existing_units_compete_with_new_groups_without_membership_expansion(status):
    existing = _record(status=status, is_open=status == "candidate")
    plan = _plan([_finding(), _finding("new"), _finding("other", path="src/other.py")], [existing])
    assert len(plan.selected_existing) == 1
    assert len(plan.selected_new) == 1
    assert len(plan.selected_existing[0].existing_record.work_item.batch.members) == 1
    assert _reasons(plan)["new"] == "group_reserved"


def test_candidate_singles_compete_equally_with_new_work():
    single = _single(status="candidate")
    plan = _plan(
        [_finding(), _finding("higher", source="semgrep-sarif")],
        [single],
        max_active_work_items=1,
        source_priorities={"semgrep-sarif": 1},
    )
    assert plan.selected_new
    assert not plan.selected_existing
    assert single.work_item.status == "candidate"


def test_existing_candidate_singles_keep_separate_capacity_slots_in_the_same_group():
    findings = [_finding("a"), _finding("b")]
    records = [_single(number, finding=finding) for number, finding in enumerate(findings, 1)]
    plan = _plan(findings, records)
    assert len(plan.selected_existing) == 2
    assert not plan.conflicts
    assert not plan.selected_new


def test_absent_but_stale_members_never_return_to_executable_scope():
    record = _record(
        presence="absent", freshness="unknown", status="capacity_deferred", is_open=False
    )
    plan = _plan(records=[record])
    assert not plan.selected_existing
    assert record.work_item.batch.observations[0].last_confirmed_presence == "absent"
    detected = _record(freshness="unknown", status="capacity_deferred", is_open=False)
    assert _plan(records=[detected]).selected_existing


def test_mixed_observations_and_policy_narrow_existing_scope_without_resizing():
    members = (_finding("a"), _finding("b"), _finding("c", severity="high"))
    record = _record(members=members, status="capacity_deferred", is_open=False)
    observations = list(record.work_item.batch.observations)
    observations[1] = observations[1].model_copy(
        update={"last_confirmed_presence": "absent", "freshness": "unknown"}
    )
    record.work_item.batch = record.work_item.batch.model_copy(
        update={"observations": tuple(observations)}
    )
    plan = _plan(records=[record], policy_state=_policy("medium"))
    assert [member.finding_id for member in plan.selected_existing[0].members] == ["a"]
    assert len(plan.selected_existing[0].existing_record.work_item.batch.members) == 3


@pytest.mark.parametrize("status", ["candidate", "policy_deferred", "capacity_deferred"])
def test_current_severity_rejection_cannot_be_overridden_by_stored_observation(status):
    record = _record(status=status, is_open=status == "candidate")
    original = record.work_item.model_dump_json()
    plan = _plan([_finding(severity="high")], [record], policy_state=_policy("medium"))
    assert not plan.selected_existing
    assert not plan.selected_new
    assert _reasons(plan)["a"] == "severity_disabled"
    assert record.work_item.model_dump_json() == original


def test_current_finding_metadata_controls_policy_and_severity_ranking():
    first = _record(
        1, members=(_finding("a", severity="high"),), status="capacity_deferred", is_open=False
    )
    second = _record(
        2, members=(_finding("b", path="src/other.py"),), status="capacity_deferred", is_open=False
    )
    current = [_finding("a", severity="low"), _finding("b", path="src/other.py")]
    plan = _plan(current, [first, second], max_active_work_items=1)
    assert plan.selected_existing[0].existing_record.issue_number == 2
    assert _reasons(plan)["a"] == "promotion_capacity_exhausted"
    permitted = _plan([_finding("a", severity="medium")], [first], policy_state=_policy("medium"))
    assert permitted.selected_existing[0].members[0].severity == "medium"
    assert first.work_item.batch.observations[0].last_confirmed_finding.severity == "high"


def test_safe_manual_closure_releases_batch_but_not_historical_single_ownership():
    closed = _record(status="approved", is_open=False)
    assert is_safe_unstarted_batch(closed.work_item)
    assert not retains_finding_batch_ownership(closed)
    assert _plan([_finding()], [closed]).selected_new
    assert not _plan([_finding()], [_single(status="approved", is_open=False)]).selected_new


@pytest.mark.parametrize(
    "status",
    [
        "blocked",
        "in_progress",
        "review_feedback_required",
        "review_revision_queued",
        "capacity_deferred",
        "policy_deferred",
    ],
)
def test_protected_closed_work_reserves_group(status):
    closed = _record(status=status, is_open=False)
    assert not is_safe_unstarted_batch(closed.work_item)
    assert not _plan([_finding("new")], [closed]).selected_new


def test_claim_or_link_prevents_manual_closure_release():
    for changes in (
        dict(claim=WorkItemClaim(claimed_at=NOW)),
        dict(linked_change_request=ChangeRequestRef(number=1, web_url="https://example/mr/1")),
        dict(attempt_number=2),
    ):
        closed = _record(status="approved", is_open=False, **changes)
        assert retains_finding_batch_ownership(closed)
        assert not _plan([_finding("new")], [closed]).selected_new


def test_terminal_completion_releases_group_without_ancestry_lookup():
    assert _plan([_finding()], [_record(status="completed", is_open=False)]).selected_new


@pytest.mark.parametrize("linked", [False, True])
def test_reopened_overlap_pauses_ambiguous_pickup(linked):
    old = _record(1)
    replacement = _record(
        2,
        linked_change_request=ChangeRequestRef(number=10, web_url="https://example/mr/10")
        if linked
        else None,
    )
    plan = _plan([_finding(), _finding("new")], [old, replacement])
    assert not plan.selected_new
    assert not plan.selected_existing
    assert plan.conflicts[0].issue_numbers == (1, 2)
    assert _reasons(plan) == {"a": "ownership_conflict", "new": "ownership_conflict"}


def test_conflict_references_are_bounded_and_inventory_duplicates_count_once():
    records = [_record(number) for number in range(1, 14)]
    plan = _plan([_finding()], [*records, records[0]])
    assert plan.conflicts[0].issue_numbers == tuple(range(1, 11))
    assert plan.conflicts[0].omitted_issue_count == 3


def test_conflict_collection_is_bounded_without_releasing_omitted_ownership():
    records = [
        _record(2 * group + offset, members=(_finding(f"group-{group}", path=f"src/{group}.py"),))
        for group in range(12)
        for offset in (1, 2)
    ]
    plan = _plan(records=records)
    assert len(plan.conflicts) == 10
    assert plan.omitted_conflict_count == 2
    assert not plan.selected_existing


def test_overlapping_singles_without_grouping_evidence_are_still_ambiguous():
    finding = _finding(rule=None)
    plan = _plan([finding], [_single(1, finding=finding), _single(2, finding=finding)])
    assert _reasons(plan)["a"] == "ownership_conflict"
    assert not plan.selected_existing


def test_same_group_reopened_work_conflicts_even_when_members_do_not_overlap():
    plan = _plan(
        [_finding("a"), _finding("b")],
        [_record(1, members=(_finding("a"),)), _record(2, members=(_finding("b"),))],
    )
    assert plan.conflicts
    assert not plan.selected_existing


def test_inconsistent_duplicate_inventory_is_a_conflict_not_a_new_slot():
    record = _record(status="approved")
    changed = _record(status="candidate")
    plan = _plan([_finding()], [record, changed])
    assert plan.conflicts
    assert plan.active_work_item_count == 1
    assert not plan.selected_existing


def test_duplicate_durable_batch_identity_conflicts_across_disjoint_groups():
    first = _record(1, members=(_finding("a", path="src/a.py"),))
    second = _record(2, members=(_finding("b", path="src/b.py"),))
    state = second.work_item.model_dump(mode="json")
    state["work_item_id"] = first.work_item.work_item_id
    state["source"]["source_item_key"] = first.work_item.source.source_item_key
    second = FindingSyncRecord(
        work_item=WorkItemState.model_validate(state),
        issue_number=second.issue_number,
        issue_url=second.issue_url,
        is_open=second.is_open,
    )
    plan = _plan([_finding("a", path="src/a.py"), _finding("b", path="src/b.py")], [first, second])
    assert not plan.selected_existing
    assert not plan.selected_new
    assert plan.conflicts[0].issue_numbers == (1, 2)
    assert set(_reasons(plan).values()) == {"ownership_conflict"}


def test_same_work_item_id_conflicts_even_when_source_identities_differ():
    first = _single(1, finding=_finding("a"))
    second = _single(2, finding=_finding("b", path="src/b.py", source="mypy-sarif"))
    second = FindingSyncRecord(
        work_item=second.work_item.model_copy(
            update={"work_item_id": first.work_item.work_item_id}
        ),
        issue_number=second.issue_number,
        issue_url=second.issue_url,
        is_open=second.is_open,
    )
    plan = _plan(
        [_finding("a"), _finding("b", path="src/b.py", source="mypy-sarif")], [first, second]
    )
    assert plan.conflicts[0].issue_numbers == (1, 2)
    assert not plan.selected_existing


def test_missing_grouping_evidence_retains_single_finding_handling():
    findings = [_finding("a", rule=None), _finding("b", rule=None)]
    plan = _plan(findings)
    assert len(plan.selected_new) == 2
    assert all(unit.group is None and len(unit.members) == 1 for unit in plan.selected_new)


def test_missing_category_uses_singletons_without_bypassing_group_reservation():
    findings = [_finding("a"), _finding("b")]
    for finding in findings:
        finding.remediation_context.category = None
    plan = _plan(findings)
    assert len(plan.selected_new) == 1
    assert len(plan.selected_new[0].members) == 1
    reserved = _record(members=(_finding("owned"),), status="blocked")
    assert not _plan(findings, [reserved]).selected_new


def test_planner_is_deterministic_and_has_no_identity_or_clock_side_effects():
    finding = _finding()
    record = _record(
        members=(_finding("owned", path="src/owned.py"),), status="capacity_deferred", is_open=False
    )
    before_finding = finding.model_dump_json()
    before_state = record.work_item.model_dump_json()
    with (
        patch("uuid.uuid4", side_effect=AssertionError("ID allocation")),
        patch("time.time", side_effect=AssertionError("clock read")),
    ):
        plan = _plan([finding], [record])
        assert plan == _plan([finding], [record])
    assert finding.model_dump_json() == before_finding
    assert record.work_item.model_dump_json() == before_state
    plan.selected_new[0].members[0].summary = "mutated output"
    plan.selected_existing[0].existing_record.work_item.summary = "mutated output"
    assert finding.model_dump_json() == before_finding
    assert record.work_item.model_dump_json() == before_state
    with pytest.raises(FrozenInstanceError):
        plan.active_work_item_count = 100


def test_empty_inventory_and_no_available_capacity():
    assert not _plan().selected_new
    plan = _plan(
        [_finding()],
        [_record(status="approved", members=(_finding("active", path="src/active.py"),))],
        max_active_work_items=1,
    )
    assert _reasons(plan)["a"] == "promotion_capacity_exhausted"


def test_invalid_planner_limits_and_conflicting_findings_fail_explicitly():
    with pytest.raises(ValueError, match="positive"):
        _plan(max_findings_per_work_item=0)
    with pytest.raises(ValueError, match="Conflicting normalized"):
        _plan([_finding(), _finding(severity="high")])

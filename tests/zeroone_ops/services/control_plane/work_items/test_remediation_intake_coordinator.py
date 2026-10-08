"""Characterize shared intake behavior through both provider wrappers."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from unittest.mock import Mock

import pytest

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.remediation_intake import RemediationIntakeRecord
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    WorkItemClaim,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.work_items.github_remediation_intake_service import (
    GitHubRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_remediation_intake_service import (
    GitLabRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
)
from zeroone_ops.services.control_plane.work_items.remediation_intake_coordinator import (
    RemediationIntakeCoordinator,
)

from .test_support import build_work_item

Provider = Literal["github", "gitlab"]
CREATED_AT = datetime(2026, 9, 1, tzinfo=UTC)
CLAIMED_AT = datetime(2026, 9, 2, tzinfo=UTC)


def _work_item(identifier: str = "work-1", *, queued: bool = False) -> WorkItemState:
    work_item = build_work_item().model_copy(
        update={
            "work_item_id": identifier,
            "source": WorkItemSourceRef(
                source="sonarqube",
                source_item_key=identifier,
                repository_scope="octo-org/octo-repo",
            ),
        }
    )
    if not queued:
        return work_item
    return work_item.model_copy(
        update={
            "status": "review_revision_queued",
            "linked_change_request": ChangeRequestRef(number=17, web_url="https://example/pr/17"),
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha="reviewed-sha",
                follow_up_required=True,
                feedback=ProjectedReviewFeedback(
                    summary="Preserve the error response.",
                    finding_count=1,
                    findings=[
                        ProjectedReviewFinding(
                            title="Preserve errors",
                            file_path="src/api.py",
                            line_start=42,
                            evidence="The branch returns success.",
                            explanation="Clients cannot identify failures.",
                            suggested_follow_up="Keep the error response.",
                        )
                    ],
                ),
            ),
        }
    )


def _provider_service(
    provider: Provider,
    entries: list[tuple[int, datetime | None, WorkItemState]],
) -> tuple[GitHubRemediationIntakeService | GitLabRemediationIntakeService, Mock, Mock]:
    clock = Mock(return_value=CLAIMED_AT)
    if provider == "github":
        lookups = [
            GitHubWorkItemLookupResult(
                issue=GitHubIssueInfo(
                    id=number,
                    number=number,
                    title=state.summary,
                    body="machine state",
                    web_url=f"https://example/issues/{number}",
                    created_at=created_at,
                ),
                work_item=state,
            )
            for number, created_at, state in entries
        ]
        boundary = Mock(spec=GitHubWorkItemService)
        result_type = GitHubWorkItemUpsertResult
        service = GitHubRemediationIntakeService(work_item_service=boundary, clock=clock)
    else:
        lookups = [
            GitLabWorkItemLookupResult(
                issue=GitLabIssueInfo(
                    id=number,
                    iid=number,
                    title=state.summary,
                    description="machine state",
                    web_url=f"https://example/issues/{number}",
                    created_at=created_at,
                ),
                work_item=state,
            )
            for number, created_at, state in entries
        ]
        boundary = Mock(spec=GitLabWorkItemService)
        result_type = GitLabWorkItemUpsertResult
        service = GitLabRemediationIntakeService(work_item_service=boundary, clock=clock)
    boundary.list_open_work_items.return_value = lookups

    def persist_claim(**kwargs):
        work_item = kwargs["work_item"]
        selected = next(
            lookup for lookup in lookups if lookup.work_item.identity_key == work_item.identity_key
        )
        return result_type(issue=selected.issue, action="updated", work_item=work_item)

    boundary.upsert_work_item.side_effect = persist_claim
    clock.assert_not_called()
    return service, boundary, clock


def _select(service, provider: Provider, *, persist: bool = True):
    scope = (
        {"repository_id": "octo-org/octo-repo"}
        if provider == "github"
        else {"project_id": "group/project"}
    )
    return service.select_and_claim(**scope, persist=persist, run_id="run-123")


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("empty", [False, True])
def test_provider_empty_selection_counts_inventory_and_avoids_clock_and_writes(
    provider: Provider,
    empty: bool,
) -> None:
    entries = (
        [] if empty else [(11, CREATED_AT, _work_item().model_copy(update={"status": "blocked"}))]
    )
    service, boundary, clock = _provider_service(provider, entries)

    result = _select(service, provider)

    assert result.selected_target is None
    assert result.claimed_work_item is None
    assert result.issue is None
    assert result.item_count == len(entries)
    provider_name = "GitHub" if provider == "github" else "GitLab"
    assert (
        result.message == f"No eligible approved {provider_name} remediation work items were found."
    )
    boundary.list_open_work_items.assert_called_once()
    boundary.upsert_work_item.assert_not_called()
    clock.assert_not_called()


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("ranking", ["revision", "severity", "created", "number", "missing_time"])
def test_provider_selection_keeps_existing_ranking(provider: Provider, ranking: str) -> None:
    first = _work_item("first")
    second = _work_item("second")
    first_time = second_time = CREATED_AT
    if ranking == "revision":
        second = _work_item("second", queued=True).model_copy(update={"severity": "low"})
    elif ranking == "severity":
        first = first.model_copy(update={"severity": "low"})
    elif ranking == "created":
        first_time += timedelta(days=1)
    elif ranking == "missing_time":
        first_time = None
    service, boundary, _ = _provider_service(
        provider, [(12, first_time, first), (11, second_time, second)]
    )

    result = _select(service, provider, persist=False)

    assert result.selected_target is not None
    assert result.selected_target.item_id == "second"
    assert result.item_count == 2
    boundary.list_open_work_items.assert_called_once()


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize(
    "exclusion",
    [
        "linked_approved",
        "missing_path",
        "escaping_path",
        "absolute_path",
        "blocked",
        "candidate",
        "in_progress",
        "dismissed",
        "policy_deferred",
        "capacity_deferred",
        "feedback_required",
        "claimed_revision",
        "missing_link",
        "missing_review",
        "missing_feedback",
    ],
)
def test_provider_excludes_currently_ineligible_work(provider: Provider, exclusion: str) -> None:
    work_item = _work_item(
        queued=exclusion
        in {
            "claimed_revision",
            "missing_link",
            "missing_review",
            "missing_feedback",
        }
    )
    updates = {
        "linked_approved": {
            "linked_change_request": ChangeRequestRef(number=17, web_url="https://example/pr/17")
        },
        "missing_path": {"file_path": None},
        "escaping_path": {"file_path": "../outside.py"},
        "absolute_path": {"file_path": "/outside.py"},
        "feedback_required": {"status": "review_feedback_required"},
        "claimed_revision": {"claim": WorkItemClaim(claimed_at=CREATED_AT, run_id="earlier")},
        "missing_link": {"linked_change_request": None},
        "missing_review": {"projected_review": None},
    }.get(exclusion, {"status": exclusion})
    if exclusion == "missing_feedback":
        updates = {
            "projected_review": work_item.projected_review.model_copy(update={"feedback": None})
        }
    work_item = work_item.model_copy(update=updates)
    service, boundary, clock = _provider_service(provider, [(11, CREATED_AT, work_item)])

    result = _select(service, provider)

    assert result.selected_target is None
    assert result.item_count == 1
    boundary.upsert_work_item.assert_not_called()
    clock.assert_not_called()


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("persist", [False, True])
def test_provider_claim_and_dry_run_contracts(
    provider: Provider, queued: bool, persist: bool
) -> None:
    work_item = _work_item(queued=queued)
    snapshot = work_item.model_dump()
    fields = work_item.model_fields_set.copy()
    service, boundary, clock = _provider_service(provider, [(11, CREATED_AT, work_item)])

    result = _select(service, provider, persist=persist)

    assert result.item_count == 1
    assert result.message == ""
    assert result.selected_target is not None
    assert result.claimed_work_item is not None
    assert result.selected_target.work_item_url == result.issue.web_url
    assert result.selected_target.work_item_url == "https://example/issues/11"
    assert work_item.model_dump() == snapshot
    assert work_item.model_fields_set == fields
    if persist:
        clock.assert_called_once_with()
        boundary.upsert_work_item.assert_called_once()
        assert result.claimed_work_item.claim.claimed_at == CLAIMED_AT
        assert result.claimed_work_item.claim.run_id == "run-123"
        assert result.claimed_work_item.status == (
            "review_revision_queued" if queued else "in_progress"
        )
    else:
        clock.assert_not_called()
        boundary.upsert_work_item.assert_not_called()
        assert result.claimed_work_item is work_item
        assert result.selected_target.status == work_item.status
    if queued:
        assert result.selected_target.review_feedback == work_item.projected_review.feedback
        assert result.selected_target.reviewed_sha == "reviewed-sha"


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_preserves_eligibility_of_approved_work_with_a_claim(provider: Provider) -> None:
    work_item = _work_item().model_copy(
        update={"claim": WorkItemClaim(claimed_at=CREATED_AT, run_id="earlier")}
    )
    service, _, clock = _provider_service(provider, [(11, CREATED_AT, work_item)])

    result = _select(service, provider)

    assert result.claimed_work_item.claim.run_id == "run-123"
    clock.assert_called_once_with()
    assert work_item.claim.run_id == "earlier"


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("queued", [False, True])
def test_provider_returns_actual_persistence_response(provider: Provider, queued: bool) -> None:
    service, boundary, _ = _provider_service(
        provider, [(11, CREATED_AT, _work_item(queued=queued))]
    )
    original_response = boundary.upsert_work_item.side_effect

    def authoritative_response(**kwargs):
        response = original_response(**kwargs)
        issue = response.issue.model_copy(update={"web_url": "https://example/authoritative/11"})
        state = response.work_item.model_copy(update={"summary": "Authoritative summary"})
        return type(response)(issue=issue, action="updated", work_item=state)

    boundary.upsert_work_item.side_effect = authoritative_response
    result = _select(service, provider)

    assert result.issue.web_url == "https://example/authoritative/11"
    assert result.selected_target.work_item_url == result.issue.web_url
    assert result.claimed_work_item.summary == "Authoritative summary"
    assert result.selected_target.title == "Authoritative summary"
    if queued:
        assert (
            result.selected_target.review_feedback
            == result.claimed_work_item.projected_review.feedback
        )


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("operation", ["listing", "persistence", "target"])
def test_provider_propagates_failures_without_retry(provider: Provider, operation: str) -> None:
    service, boundary, clock = _provider_service(provider, [(11, CREATED_AT, _work_item())])
    if operation == "listing":
        boundary.list_open_work_items.side_effect = RuntimeError("listing failed")
    elif operation == "persistence":
        boundary.upsert_work_item.side_effect = RuntimeError("persistence failed")
    else:
        original_response = boundary.upsert_work_item.side_effect

        def missing_file_response(**kwargs):
            response = original_response(**kwargs)
            return type(response)(
                issue=response.issue,
                action="updated",
                work_item=response.work_item.model_copy(update={"file_path": None}),
            )

        boundary.upsert_work_item.side_effect = missing_file_response
    expected_error = ValueError if operation == "target" else RuntimeError
    with pytest.raises(expected_error):
        _select(service, provider)
    boundary.list_open_work_items.assert_called_once()
    if operation == "listing":
        boundary.upsert_work_item.assert_not_called()
        clock.assert_not_called()
    else:
        boundary.upsert_work_item.assert_called_once()
        clock.assert_called_once_with()


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("persist", [False, True])
def test_coordinator_selection_and_claim_use_normalized_records(
    queued: bool, persist: bool
) -> None:
    work_item = _work_item(queued=queued)
    snapshot = work_item.model_dump()
    fields = work_item.model_fields_set.copy()
    record = RemediationIntakeRecord(
        work_item=work_item,
        issue_number=11,
        issue_url="https://example/issues/11",
        created_at=CREATED_AT,
    )
    authoritative = RemediationIntakeRecord(
        work_item=work_item.model_copy(
            update={
                "status": "review_revision_queued" if queued else "in_progress",
                "claim": WorkItemClaim(claimed_at=CLAIMED_AT, run_id="run-123"),
                "summary": "Persisted summary",
            }
        ),
        issue_number=11,
        issue_url="https://example/authoritative/11",
    )
    clock = Mock(return_value=CLAIMED_AT)
    write = Mock(return_value=authoritative)
    coordinator = RemediationIntakeCoordinator(clock=clock)
    clock.assert_not_called()

    outcome = coordinator.select_and_claim(
        records=[record], persist_work_item=write, persist=persist, run_id="run-123"
    )

    assert outcome.item_count == 1
    assert outcome.selected_record is (authoritative if persist else record)
    assert outcome.selected_target.work_item_url == outcome.selected_record.issue_url
    assert work_item.model_dump() == snapshot
    assert work_item.model_fields_set == fields
    if persist:
        clock.assert_called_once_with()
        write.assert_called_once_with(
            work_item.model_copy(
                update={
                    "status": "review_revision_queued" if queued else "in_progress",
                    "claim": WorkItemClaim(claimed_at=CLAIMED_AT, run_id="run-123"),
                }
            )
        )
        assert outcome.selected_target.title == "Persisted summary"
    else:
        clock.assert_not_called()
        write.assert_not_called()
    if queued:
        assert outcome.selected_target.review_feedback == work_item.projected_review.feedback


@pytest.mark.parametrize("empty", [False, True])
def test_coordinator_empty_selection_never_claims(empty: bool) -> None:
    records = (
        []
        if empty
        else [
            RemediationIntakeRecord(
                work_item=_work_item().model_copy(update={"status": "blocked"}),
                issue_number=11,
                issue_url="https://example/issues/11",
            )
        ]
    )
    clock = Mock(side_effect=AssertionError("Clock must not run"))
    write = Mock(side_effect=AssertionError("Write must not run"))

    outcome = RemediationIntakeCoordinator(clock=clock).select_and_claim(
        records=records,
        persist_work_item=write,
    )

    assert outcome.item_count == len(records)
    assert outcome.selected_record is None
    assert outcome.selected_target is None
    clock.assert_not_called()
    write.assert_not_called()


def test_coordinator_claim_accepts_missing_run_id() -> None:
    record = RemediationIntakeRecord(
        work_item=_work_item(),
        issue_number=11,
        issue_url="https://example/issues/11",
    )
    write = Mock(
        side_effect=lambda state: RemediationIntakeRecord(
            work_item=state,
            issue_number=11,
            issue_url=record.issue_url,
        )
    )

    outcome = RemediationIntakeCoordinator(clock=lambda: CLAIMED_AT).select_and_claim(
        records=[record],
        persist_work_item=write,
    )

    assert outcome.selected_record.work_item.claim.run_id is None
    assert outcome.selected_record.work_item.claim.claimed_at == CLAIMED_AT

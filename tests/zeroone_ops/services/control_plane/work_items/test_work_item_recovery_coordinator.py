"""Characterize authorized command processing through both provider services."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from zeroone_ops.models.github import GitHubIssueComment, GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    PublicationRetryState,
    RecoveryEvent,
    ReviewRevisionRequest,
)
from zeroone_ops.models.work_item_recovery import AuthorizedWorkItemCommandEvent
from zeroone_ops.services.control_plane.github_comment_authorization_service import (
    GitHubCommentAuthorizationService,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items import (
    work_item_recovery_coordinator,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_service import (
    GitHubWorkItemCommentClient,
    GitHubWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_service import (
    GitLabWorkItemNoteClient,
    GitLabWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
)

from .test_support import build_work_item

SCOPE = "octo-org/octo-repo"
EVENT_TIME = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _reference(provider, number=21):
    return f"github-comment-{number}" if provider == "github" else f"gitlab-note-{number}"


def _event(
    provider, *, number=21, body="/zeroone remediation requeue", timestamp=None, actor="operator"
):
    event_type = GitHubIssueComment if provider == "github" else GitLabIssueNote
    return event_type(
        id=number, body=body, created_at=timestamp or EVENT_TIME.isoformat(), author_username=actor
    )


def _boundary(provider, *, state=None, events=None):
    state = build_work_item(status="blocked") if state is None else state
    events = [_event(provider)] if events is None else events
    if provider == "github":
        issue = GitHubIssueInfo(
            id=11, number=11, web_url="https://example/11", title="Work", body=""
        )
        existing = GitHubWorkItemLookupResult(issue=issue, work_item=state)
        client = Mock(spec=GitHubWorkItemCommentClient)
        client.list_issue_comments.return_value = events
        authorization = Mock(spec=GitHubCommentAuthorizationService)
        authorization.authorized_comments.side_effect = lambda **kwargs: kwargs["comments"]
        boundary = Mock(spec=GitHubWorkItemService)
        boundary.list_open_work_items.return_value = [existing]
        result_type = GitHubWorkItemUpsertResult
        service = GitHubWorkItemRecoveryService(
            comment_client=client,
            comment_authorization_service=authorization,
            work_item_service=boundary,
        )
    else:
        issue = GitLabIssueInfo(
            id=11, iid=11, web_url="https://example/11", title="Work", description=""
        )
        existing = GitLabWorkItemLookupResult(issue=issue, work_item=state)
        client = Mock(spec=GitLabWorkItemNoteClient)
        client.list_issue_notes.return_value = events
        authorization = Mock(spec=GitLabPolicyNoteAuthorizationService)
        authorization.authorized_notes.side_effect = lambda **kwargs: kwargs["notes"]
        boundary = Mock(spec=GitLabWorkItemService)
        result_type = GitLabWorkItemUpsertResult
        service = GitLabWorkItemRecoveryService(
            note_client=client,
            note_authorization_service=authorization,
            work_item_service=boundary,
        )
    boundary.update_existing_work_item.side_effect = lambda **kwargs: result_type(
        issue=kwargs["existing"].issue.model_copy(update={"web_url": "https://example/persisted"}),
        work_item=kwargs["work_item"],
        action="updated",
    )
    return service, existing, boundary, client, authorization


def _process(service, provider, existing, *, persist=True, eligible=True, event_id=21):
    if provider == "github":
        return service.process(
            repository_id=SCOPE,
            issue_number=11,
            comment_id=event_id,
            policy_eligible=eligible,
            persist=persist,
        )
    return service.process(
        project_id=SCOPE,
        existing=existing,
        policy_eligible=eligible,
        persist=persist,
    )


def _review_state():
    return build_work_item(status="review_feedback_required").model_copy(
        update={
            "linked_change_request": ChangeRequestRef(number=7, web_url="https://example/pr/7"),
            "review_action_required_at": EVENT_TIME - timedelta(hours=1),
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha="abc123",
                follow_up_required=True,
                feedback=ProjectedReviewFeedback(
                    summary="Preserve behavior",
                    finding_count=1,
                    findings=[
                        ProjectedReviewFinding(
                            title="Preserve response",
                            file_path="src/api.py",
                            evidence="Changed response",
                            explanation="Breaks clients",
                            suggested_follow_up="Preserve response",
                        ),
                    ],
                ),
            ),
        }
    )


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize(
    "case",
    [
        "requeue",
        "dismiss",
        "unmatched",
        "malformed",
        "missing_actor",
        "invalid_time",
        "naive_time",
        "missing_time",
        "stale",
        "equal",
        "replay",
        "queued_receipt",
        "historical_receipt",
        "policy_disabled",
        "publication_retry",
        "review_requeue",
    ],
)
def test_provider_command_characterization(provider, persist, case):
    state = build_work_item(status="blocked")
    event = _event(provider)
    eligible = case != "policy_disabled"
    if case == "dismiss":
        event = event.model_copy(update={"body": "/zeroone remediation dismiss"})
        eligible = False
    elif case == "unmatched":
        event = event.model_copy(update={"body": "Thanks"})
    elif case == "malformed":
        event = event.model_copy(update={"body": "/zeroone remediation retry"})
    elif case == "missing_actor":
        event = event.model_copy(update={"author_username": None})
    elif case in {"invalid_time", "naive_time", "missing_time"}:
        event = event.model_copy(
            update={
                "created_at": {
                    "invalid_time": "not-a-time",
                    "naive_time": "2026-09-01T12:00:00",
                    "missing_time": None,
                }[case]
            }
        )
    elif case in {"stale", "equal", "replay"}:
        receipt = RecoveryEvent(
            action="requeue",
            actor="operator",
            request_reference=_reference(provider) if case == "replay" else "previous",
            occurred_at=EVENT_TIME + (timedelta(hours=1) if case == "stale" else timedelta()),
            previous_status="blocked",
            resulting_status="approved",
            previous_attempt_number=1,
            resulting_attempt_number=2,
        )
        state = state.model_copy(update={"recovery_events": [receipt]})
    elif case in {"queued_receipt", "historical_receipt"}:
        receipt = ReviewRevisionRequest(
            actor="operator",
            request_reference=_reference(provider),
            occurred_at=EVENT_TIME - timedelta(hours=1),
            reviewed_sha="abc123",
        )
        field = "review_revision_request" if case == "queued_receipt" else "last_revision_command"
        state = state.model_copy(update={field: receipt})
    elif case == "publication_retry":
        eligible = False
        state = state.model_copy(
            update={
                "publication_retry": PublicationRetryState(
                    branch_name="zeroone-ops/chore/retry",
                    commit_sha="abc123",
                    reason="change_request_publish_failed",
                )
            }
        )
    elif case == "review_requeue":
        state = _review_state()
    snapshot = state.model_dump()
    fields = state.model_fields_set.copy()
    service, existing, boundary, _, _ = _boundary(provider, state=state, events=[event])

    result = _process(service, provider, existing, persist=persist, eligible=eligible)

    accepted = case in {"requeue", "dismiss", "publication_retry", "review_requeue"}
    ignored = case in {"unmatched", "replay", "queued_receipt", "historical_receipt"}
    assert result.matched_command_count == int(case != "unmatched")
    assert result.accepted_command_count == int(accepted)
    assert result.rejected_command_count == int(not accepted and not ignored)
    assert boundary.update_existing_work_item.call_count == int(persist and accepted)
    assert state.model_dump() == snapshot
    assert state.model_fields_set == fields
    assert result.issue.web_url == (
        "https://example/persisted" if persist and accepted else existing.issue.web_url
    )
    if accepted:
        expected_status = (
            "dismissed"
            if case == "dismiss"
            else ("review_revision_queued" if case == "review_requeue" else "approved")
        )
        assert result.work_item.status == expected_status
    else:
        assert result.work_item is state
    if provider == "github":
        assert result.comment_count == result.authorized_comment_count == 1
    else:
        assert result.note_count == result.authorized_note_count == 1


def test_github_missing_work_item_performs_no_comment_or_authorization_read():
    service, existing, boundary, client, authorization = _boundary("github")
    boundary.list_open_work_items.return_value = []
    result = _process(service, "github", existing)
    assert result.issue is result.work_item is None
    assert result.comment_count == result.authorized_comment_count == 0
    assert (
        result.matched_command_count
        == result.accepted_command_count
        == result.rejected_command_count
        == 0
    )
    client.list_issue_comments.assert_not_called()
    authorization.authorized_comments.assert_not_called()
    boundary.update_existing_work_item.assert_not_called()


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_authorization_discovery_boundaries_remain_provider_local(provider):
    events = [_event(provider, number=20), _event(provider, number=21, body="Thanks")]
    service, existing, boundary, _, authorization = _boundary(provider, events=events)
    method = (
        authorization.authorized_comments
        if provider == "github"
        else authorization.authorized_notes
    )
    method.side_effect = None
    method.return_value = []
    result = _process(service, provider, existing)
    argument = "comments" if provider == "github" else "notes"
    assert method.call_args.kwargs[argument] == (events[1:] if provider == "github" else events)
    assert result.matched_command_count == result.accepted_command_count == 0
    boundary.update_existing_work_item.assert_not_called()
    assert (result.comment_count if provider == "github" else result.note_count) == 2


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("operation", ["discovery", "authorization", "persistence"])
def test_provider_failures_propagate_without_retry(provider, operation):
    service, existing, boundary, client, authorization = _boundary(provider)
    discovery = client.list_issue_comments if provider == "github" else client.list_issue_notes
    authorize = (
        authorization.authorized_comments
        if provider == "github"
        else authorization.authorized_notes
    )
    failure = {
        "discovery": discovery,
        "authorization": authorize,
        "persistence": boundary.update_existing_work_item,
    }[operation]
    failure.side_effect = RuntimeError("provider failed")
    with pytest.raises(RuntimeError, match="provider failed"):
        _process(service, provider, existing)
    failure.assert_called_once()
    if operation != "persistence":
        boundary.update_existing_work_item.assert_not_called()


@pytest.mark.parametrize("persist", [False, True])
def test_gitlab_ordered_commands_use_authoritative_response_before_next_decision(persist):
    first = _event("gitlab", number=21)
    second = _event(
        "gitlab",
        number=22,
        body="/zeroone remediation dismiss",
        timestamp=(EVENT_TIME + timedelta(minutes=1)).isoformat(),
    )
    service, existing, boundary, _, _ = _boundary("gitlab", events=[second, first])
    original_write = boundary.update_existing_work_item.side_effect

    def still_blocked(**kwargs):
        result = original_write(**kwargs)
        return type(result)(
            issue=result.issue,
            work_item=result.work_item.model_copy(update={"status": "blocked"}),
            action="updated",
        )

    boundary.update_existing_work_item.side_effect = still_blocked
    result = _process(service, "gitlab", existing, persist=persist)
    assert result.accepted_command_count == (2 if persist else 1)
    assert result.rejected_command_count == (0 if persist else 1)
    assert result.work_item.status == ("blocked" if persist else "approved")
    if persist:
        first_call, second_call = boundary.update_existing_work_item.call_args_list
        assert first_call.kwargs["existing"] is existing
        assert second_call.kwargs["existing"].issue.web_url == "https://example/persisted"
        assert second_call.kwargs["existing"].work_item.status == "blocked"
        assert (
            second_call.kwargs["existing"].work_item.recovery_events[-1].request_reference
            == "gitlab-note-21"
        )
    else:
        boundary.update_existing_work_item.assert_not_called()


def test_gitlab_equal_timestamps_use_event_id_then_reject_after_accepted_transition():
    first = _event("gitlab", number=21, body="/zeroone remediation dismiss")
    second = _event("gitlab", number=22)
    service, existing, boundary, _, _ = _boundary("gitlab", events=[second, first])
    result = _process(service, "gitlab", existing)
    assert result.accepted_command_count == result.rejected_command_count == 1
    assert boundary.update_existing_work_item.call_args.kwargs["work_item"].status == "dismissed"


def test_gitlab_persistence_failure_stops_remaining_notes():
    service, existing, boundary, _, _ = _boundary(
        "gitlab",
        events=[
            _event("gitlab"),
            _event("gitlab", number=22, timestamp=(EVENT_TIME + timedelta(minutes=1)).isoformat()),
        ],
    )
    parser = Mock(wraps=service.command_parser)
    service.command_parser = parser
    boundary.update_existing_work_item.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        _process(service, "gitlab", existing)
    parser.parse.assert_called_once()
    boundary.update_existing_work_item.assert_called_once()


def _coordinator():
    service, _, _, _, _ = _boundary("github")
    return work_item_recovery_coordinator.WorkItemRecoveryCoordinator(
        command_parser=service.command_parser,
        command_decision_service=service.command_decision_service,
    )


def _normalized_event(*, number=21, body="/zeroone remediation requeue", timestamp=None):
    return AuthorizedWorkItemCommandEvent(
        provider_event_id=number,
        request_reference=f"event-{number}",
        body=body,
        actor="operator",
        created_at=timestamp or EVENT_TIME.isoformat(),
    )


@pytest.mark.parametrize("persist", [False, True])
def test_coordinator_replay_in_same_batch_is_matched_without_rejection(persist):
    state = build_work_item(status="blocked")
    snapshot = state.model_dump()
    persistence = Mock(return_value=state)
    event = _normalized_event()
    result = _coordinator().process(
        work_item=state,
        events=[event, event],
        policy_eligible=True,
        persist=persist,
        persist_work_item=persistence,
    )
    assert result.matched_command_count == 2
    assert result.accepted_command_count == 1
    assert result.rejected_command_count == 0
    assert persistence.call_count == int(persist)
    assert result.work_item is state if persist else result.work_item.status == "approved"
    assert state.model_dump() == snapshot


@pytest.mark.parametrize("persist", [False, True])
def test_coordinator_orders_offset_timestamps_then_event_ids(persist):
    state = build_work_item(status="blocked")
    persistence = Mock(side_effect=lambda state: state)
    events = [
        _normalized_event(number=22),
        _normalized_event(
            number=21,
            body="/zeroone remediation dismiss",
            timestamp="2026-09-01T14:00:00+02:00",
        ),
    ]
    result = _coordinator().process(
        work_item=state,
        events=events,
        policy_eligible=True,
        persist=persist,
        persist_work_item=persistence,
    )
    assert result.work_item.status == "dismissed"
    assert result.work_item.recovery_events[-1].request_reference == "event-21"
    assert result.accepted_command_count == result.rejected_command_count == 1
    assert persistence.call_count == int(persist)


def test_coordinator_invalid_timestamps_sort_last_and_are_rejected():
    persistence = Mock()
    result = _coordinator().process(
        work_item=build_work_item(status="blocked"),
        events=[
            _normalized_event(number=20, timestamp="invalid"),
            _normalized_event(number=21),
        ],
        policy_eligible=True,
        persist=False,
        persist_work_item=persistence,
    )
    assert result.work_item.status == "approved"
    assert result.accepted_command_count == result.rejected_command_count == 1
    persistence.assert_not_called()


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-09-01T12:00:00"])
@pytest.mark.parametrize("persist", [False, True])
def test_coordinator_invalid_timestamp_is_rejected_without_sorting_failure(timestamp, persist):
    state = build_work_item(status="blocked")
    persistence = Mock()
    result = _coordinator().process(
        work_item=state,
        events=[
            AuthorizedWorkItemCommandEvent(
                provider_event_id=21,
                request_reference="event-21",
                body="/zeroone remediation requeue",
                actor="operator",
                created_at=timestamp,
            )
        ],
        policy_eligible=True,
        persist=persist,
        persist_work_item=persistence,
    )
    assert result.work_item is state
    assert result.matched_command_count == result.rejected_command_count == 1
    assert result.accepted_command_count == 0
    persistence.assert_not_called()


def test_coordinator_invalid_events_follow_extreme_valid_dates_in_event_id_order():
    coordinator = _coordinator()
    parser = Mock(wraps=coordinator.command_parser)
    coordinator.command_parser = parser
    persistence = Mock()
    events = [
        _normalized_event(number=23, body="invalid-23", timestamp="invalid"),
        _normalized_event(number=21, body="last-valid", timestamp="9999-12-31T23:59:59-12:00"),
        _normalized_event(number=20, body="first-valid", timestamp="0001-01-01T00:00:00+14:00"),
        _normalized_event(number=22, body="invalid-22", timestamp="invalid"),
    ]
    coordinator.process(
        work_item=build_work_item(status="blocked"),
        events=events,
        policy_eligible=True,
        persist=True,
        persist_work_item=persistence,
    )
    assert [call.args[0] for call in parser.parse.call_args_list] == [
        "first-valid",
        "last-valid",
        "invalid-22",
        "invalid-23",
    ]
    persistence.assert_not_called()


def test_coordinator_empty_inventory_returns_original_state():
    state = build_work_item(status="blocked")
    persistence = Mock()
    result = _coordinator().process(
        work_item=state,
        events=[],
        policy_eligible=True,
        persist=True,
        persist_work_item=persistence,
    )
    assert result.work_item is state
    assert (
        result.matched_command_count
        == result.accepted_command_count
        == result.rejected_command_count
        == 0
    )
    persistence.assert_not_called()

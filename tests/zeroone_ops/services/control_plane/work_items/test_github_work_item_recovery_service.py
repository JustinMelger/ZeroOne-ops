from datetime import UTC, datetime

from zeroone_ops.models.github import GitHubIssueComment, GitHubIssueInfo
from zeroone_ops.models.work_item import (
    PublicationRetryState,
    RecoveryEvent,
    WorkItemExecutionFailure,
)
from zeroone_ops.services.control_plane.github_comment_authorization_service import (
    GitHubCommentAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_service import (
    GitHubWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
)

from .test_support import build_work_item


class FakeCommentClient:
    def __init__(self, comments: list[GitHubIssueComment], permission: str = "admin") -> None:
        self.comments = comments
        self.permission = permission

    def list_issue_comments(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> list[GitHubIssueComment]:
        del repository_id, issue_number
        return list(self.comments)

    def get_repository_permission(self, *, repository_id: str, username: str) -> str:
        del repository_id, username
        return self.permission


class FakeWorkItemService:
    def __init__(self, result: GitHubWorkItemLookupResult | None) -> None:
        self.result = result
        self.updated: list[GitHubWorkItemLookupResult] = []

    def list_open_work_items(self, *, repository_id: str) -> list[GitHubWorkItemLookupResult]:
        del repository_id
        return [] if self.result is None else [self.result]

    def update_existing_work_item(
        self,
        *,
        repository_id: str,
        existing: GitHubWorkItemLookupResult,
        work_item: object,
    ) -> GitHubWorkItemUpsertResult:
        del repository_id
        assert work_item is not None
        updated = existing.work_item.model_validate(work_item)
        issue = existing.issue.model_copy()
        self.result = GitHubWorkItemLookupResult(issue=issue, work_item=updated)
        self.updated.append(self.result)
        return GitHubWorkItemUpsertResult(issue=issue, action="updated", work_item=updated)


def build_existing(*, status: str = "blocked") -> GitHubWorkItemLookupResult:
    return GitHubWorkItemLookupResult(
        issue=GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title="ZeroOne Ops: C416 in api.py",
            body="machine state",
        ),
        work_item=build_work_item(status=status),
    )


def build_comment(*, body: str, comment_id: int = 21) -> GitHubIssueComment:
    return GitHubIssueComment(
        id=comment_id,
        body=body,
        author_username="operator",
        created_at="2026-08-07T09:00:00Z",
    )


def build_service(
    *,
    existing: GitHubWorkItemLookupResult | None,
    comments: list[GitHubIssueComment],
    permission: str = "admin",
) -> tuple[GitHubWorkItemRecoveryService, FakeWorkItemService]:
    comment_client = FakeCommentClient(comments, permission=permission)
    work_item_service = FakeWorkItemService(existing)
    return (
        GitHubWorkItemRecoveryService(
            comment_client=comment_client,
            comment_authorization_service=GitHubCommentAuthorizationService(comment_client),
            work_item_service=work_item_service,  # type: ignore[arg-type]
        ),
        work_item_service,
    )


def test_process_ignores_unauthorized_and_non_work_item_comments() -> None:
    service, work_item_service = build_service(
        existing=build_existing(),
        comments=[build_comment(body="/zeroone remediation dismiss")],
        permission="write",
    )

    result = service.process(
        repository_id="octo-org/octo-repo",
        issue_number=11,
        comment_id=21,
        policy_eligible=True,
        persist=True,
    )

    assert result.authorized_comment_count == 0
    assert result.accepted_command_count == 0
    assert work_item_service.updated == []


def test_process_dismisses_a_blocked_work_item_once() -> None:
    service, work_item_service = build_service(
        existing=build_existing(),
        comments=[build_comment(body="/zeroone remediation dismiss")],
    )

    result = service.process(
        repository_id="octo-org/octo-repo",
        issue_number=11,
        comment_id=21,
        policy_eligible=False,
        persist=True,
    )

    assert result.accepted_command_count == 1
    assert result.work_item is not None
    assert result.work_item.status == "dismissed"
    assert result.work_item.recovery_events[-1].request_reference == "github-comment-21"
    assert len(work_item_service.updated) == 1


def test_process_queues_fresh_retry_without_running_publication() -> None:
    existing = build_existing()
    existing = existing.__class__(
        issue=existing.issue,
        work_item=existing.work_item.model_copy(
            update={
                "execution_failure": WorkItemExecutionFailure(
                    stage="validation",
                    summary="Validation failed.",
                    retry_count=1,
                    run_id="run-1",
                    occurred_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
                )
            }
        ),
    )
    service, _ = build_service(
        existing=existing,
        comments=[build_comment(body="/zeroone remediation retry")],
    )

    result = service.process(
        repository_id="octo-org/octo-repo",
        issue_number=11,
        comment_id=21,
        policy_eligible=True,
        persist=True,
    )

    assert result.accepted_command_count == 1
    assert result.work_item is not None
    assert result.work_item.status == "approved"
    assert result.work_item.attempt_number == 2
    assert result.work_item.execution_failure is None


def test_process_queues_verified_publication_retry_for_the_remediation_runner() -> None:
    existing = build_existing()
    existing = existing.__class__(
        issue=existing.issue,
        work_item=existing.work_item.model_copy(
            update={
                "publication_retry": PublicationRetryState(
                    branch_name="zeroone-ops/fix",
                    commit_sha="abc123",
                    reason="change_request_publish_failed",
                )
            }
        ),
    )
    service, work_item_service = build_service(
        existing=existing,
        comments=[build_comment(body="/zeroone remediation retry")],
    )

    result = service.process(
        repository_id="octo-org/octo-repo",
        issue_number=11,
        comment_id=21,
        policy_eligible=False,
        persist=True,
    )

    assert result.accepted_command_count == 1
    assert result.work_item is not None
    assert result.work_item.status == "approved"
    assert result.work_item.publication_retry is not None
    assert result.work_item.publication_retry.branch_name == "zeroone-ops/fix"
    assert result.work_item.linked_change_request is None
    assert len(work_item_service.updated) == 1


def test_process_rejects_replayed_commands() -> None:
    existing = build_existing()
    event = RecoveryEvent(
        action="dismiss",
        actor="operator",
        request_reference="github-comment-21",
        occurred_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
        previous_status="blocked",
        resulting_status="dismissed",
        previous_attempt_number=1,
        resulting_attempt_number=1,
    )
    existing = existing.__class__(
        issue=existing.issue,
        work_item=existing.work_item.model_copy(update={"recovery_events": [event]}),
    )
    service, work_item_service = build_service(
        existing=existing,
        comments=[build_comment(body="/zeroone remediation dismiss")],
    )

    result = service.process(
        repository_id="octo-org/octo-repo",
        issue_number=11,
        comment_id=21,
        policy_eligible=True,
        persist=True,
    )

    assert result.accepted_command_count == 0
    assert result.rejected_command_count == 0
    assert work_item_service.updated == []


def test_process_ignores_historical_command_when_a_new_comment_triggers_the_run() -> None:
    service, work_item_service = build_service(
        existing=build_existing(),
        comments=[
            build_comment(body="/zeroone remediation dismiss", comment_id=21),
            build_comment(body="Thanks, investigating this now.", comment_id=22),
        ],
    )

    result = service.process(
        repository_id="octo-org/octo-repo",
        issue_number=11,
        comment_id=22,
        policy_eligible=True,
        persist=True,
    )

    assert result.comment_count == 2
    assert result.authorized_comment_count == 1
    assert result.matched_command_count == 0
    assert result.accepted_command_count == 0
    assert work_item_service.updated == []

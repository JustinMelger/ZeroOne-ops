from collections import deque
from datetime import UTC, datetime
from typing import Literal

import httpx
import pytest

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.review import (
    ChangeRequestDiffRefs,
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PriorReviewInlineComment,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewComment,
)
from zeroone_ops.models.review_overview import ReviewOverviewEnvelope, ReviewOverviewPass
from zeroone_ops.providers.review.platform import ReviewPlatformClientError
from zeroone_ops.services.review.publish.review_overview_codec import (
    OVERVIEW_START,
    ReviewOverviewError,
    decode_overview,
    encode_overview,
)
from zeroone_ops.services.review.publish.review_overview_coordinator import (
    ReviewOverviewCoordinator,
    review_pass_identity,
)

REPOSITORY = "acme/service"
REQUEST = 17
HEAD = "head-1"
NEXT_HEAD = "head-2"
BOT = "review-bot"


def _artifact() -> PublishableReviewArtifact:
    return PublishableReviewArtifact(
        classification="findings_present",
        summary="The error path reports success.",
        findings=[
            PublishableReviewFinding(
                severity="high",
                file_path="src/api.py",
                line_start=42,
                title="Preserve the error response.",
                evidence="The error branch returns success.",
                explanation="Callers cannot detect failure.",
                suggested_follow_up="Return an error response.",
                stable_identity="finding-1",
            )
        ],
    )


def _context(head_sha: str = HEAD) -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=REQUEST,
        title="Fix error handling",
        source_branch="fix/error",
        target_branch="main",
        web_url="https://example.com/pull/17",
        head_sha=head_sha,
        diff_refs=ChangeRequestDiffRefs(
            base_sha="base-sha", start_sha="start-sha", head_sha=head_sha
        ),
    )


def _envelope() -> ReviewOverviewEnvelope:
    completed = ReviewOverviewPass(
        pass_id="previous-pass",
        projection_reference="previous-pass",
        run_id="previous-run",
        head_sha=HEAD,
        diff_refs=_context().diff_refs,
        sequence=1,
        completed_at=datetime(2026, 11, 2, tzinfo=UTC),
        artifact=_artifact(),
    )
    return ReviewOverviewEnvelope(
        platform="github",
        repository_id=REPOSITORY,
        change_request_number=REQUEST,
        complete_passes=[completed],
        history=[completed.summary()],
    )


def _note(envelope: ReviewOverviewEnvelope | None = None) -> ReviewComment:
    return ReviewComment(
        id=10,
        web_url="https://example.com/pull/17#note-10",
        author_username=BOT,
        body=encode_overview(envelope or _envelope()),
    )


class FakeOverviewClient:
    """Provide exact-request transport with controllable reads and ambiguous writes."""

    def __init__(
        self, comments: list[ReviewComment] | None = None, *, head_sha: str = HEAD
    ) -> None:
        self.comments = list(comments or [])
        self.reads: deque[list[ReviewComment] | ReviewPlatformClientError | httpx.HTTPError] = (
            deque()
        )
        self.username = BOT
        self.identity_error = False
        self.identity_exception: httpx.HTTPError | None = None
        self.state_exception: ReviewPlatformClientError | httpx.HTTPError | None = None
        self.events: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self.write_outcome: Literal["success", "lost_response", "raw_lost_response", "rejected"] = (
            "success"
        )
        self.persist_writes = True
        self.response_fault: (
            Literal[
                "wrong_body",
                "old_body",
                "wrong_author",
                "missing_author",
                "zero_id",
                "negative_id",
                "wrong_update_id",
            ]
            | None
        ) = None
        self.request = ChangeRequestState(
            iid=REQUEST,
            web_url="https://example.com/pull/17",
            source_branch="fix/error",
            head_sha=head_sha,
            state="opened",
        )

    def get_current_user_username(self) -> str:
        self.events.append("identity")
        if self.identity_exception is not None:
            raise self.identity_exception
        if self.identity_error:
            raise ReviewPlatformClientError("Identity lookup denied.")
        return self.username

    def allows_machine_safe_comment_fallback(self) -> bool:
        pytest.fail("Overview authority must not use the legacy author fallback.")

    def list_change_request_comments(
        self, *, repository_id: str, change_request_number: int
    ) -> list[ReviewComment]:
        assert (repository_id, change_request_number) == (REPOSITORY, REQUEST)
        self.events.append("list")
        if self.reads:
            response = self.reads.popleft()
            if isinstance(response, (ReviewPlatformClientError, httpx.HTTPError)):
                raise response
            return list(response)
        return list(self.comments)

    def get_change_request_state(
        self, *, repository_id: str, change_request_number: int
    ) -> ChangeRequestState:
        assert (repository_id, change_request_number) == (REPOSITORY, REQUEST)
        self.events.append("state")
        if self.state_exception is not None:
            raise self.state_exception
        return self.request

    def create_change_request_comment(
        self, *, repository_id: str, change_request_number: int, body: str
    ) -> ReviewComment:
        assert (repository_id, change_request_number) == (REPOSITORY, REQUEST)
        self.events.append("create")
        self.writes.append(("create", body))
        return self._apply_write(100, body)

    def update_change_request_comment(
        self, *, repository_id: str, change_request_number: int, note_id: int, body: str
    ) -> ReviewComment:
        assert (repository_id, change_request_number) == (REPOSITORY, REQUEST)
        assert any(note.id == note_id for note in self.comments)
        self.events.append("update")
        self.writes.append(("update", body))
        return self._apply_write(note_id, body)

    def _apply_write(self, note_id: int, body: str) -> ReviewComment:
        if self.write_outcome == "rejected":
            raise ReviewPlatformClientError("Write rejected.")
        note = ReviewComment(
            id=note_id,
            web_url=f"https://example.com/pull/17#note-{note_id}",
            author_username=BOT,
            body=body,
        )
        if self.persist_writes:
            self.comments = [comment for comment in self.comments if comment.id != note_id] + [note]
        if self.write_outcome == "lost_response":
            raise ReviewPlatformClientError("Response lost after remote commit.")
        if self.write_outcome == "raw_lost_response":
            raise httpx.ReadTimeout("Response lost after remote commit.")
        if self.response_fault == "wrong_body":
            return note.model_copy(update={"body": "Unrelated success response."})
        if self.response_fault == "old_body":
            return note.model_copy(update={"body": _note().body})
        if self.response_fault == "wrong_author":
            return note.model_copy(update={"author_username": "human"})
        if self.response_fault == "missing_author":
            return note.model_copy(update={"author_username": None})
        if self.response_fault == "zero_id":
            return note.model_copy(update={"id": 0})
        if self.response_fault == "negative_id":
            return note.model_copy(update={"id": -1})
        if self.response_fault == "wrong_update_id":
            return note.model_copy(update={"id": note_id + 1})
        return note

    def get_change_request(
        self, *, repository_id: str, change_request_number: int
    ) -> ChangeRequestReviewCandidate:
        pytest.fail("Overview coordination must not load the full request diff.")

    def create_change_request_inline_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> ReviewComment:
        pytest.fail("Overview coordination must not publish inline comments.")


def _publish(
    client: FakeOverviewClient,
    *,
    run_id: str = "new-run",
    platform: Literal["github", "gitlab"] = "github",
    head_sha: str = HEAD,
) -> tuple[ReviewComment, ReviewOverviewEnvelope]:
    return ReviewOverviewCoordinator(client, platform).publish(
        repository_id=REPOSITORY,
        context=_context(head_sha),
        artifact=_artifact(),
        run_id=run_id,
        inline_decisions=[],
    )


def test_discovery_accepts_only_unique_verified_bot_authority() -> None:
    authoritative = _note()
    human_copy = authoritative.model_copy(update={"id": 11, "author_username": "human"})
    foreign_malformed = human_copy.model_copy(update={"id": 12, "body": OVERVIEW_START})
    ordinary_bot = authoritative.model_copy(update={"id": 13, "body": "Ordinary bot reply."})
    unknown_author = authoritative.model_copy(update={"id": 14, "author_username": None})
    client = FakeOverviewClient(
        [human_copy, foreign_malformed, ordinary_bot, unknown_author, authoritative]
    )

    note, envelope = ReviewOverviewCoordinator(client, "github").discover(
        repository_id=REPOSITORY, change_request_number=REQUEST
    )

    assert note == authoritative
    assert envelope == _envelope()
    assert client.events == ["identity", "list"]
    assert client.writes == []


@pytest.mark.parametrize(
    "corruption", ["malformed", "duplicate", "platform", "repository", "request"]
)
def test_invalid_bot_authority_blocks_publication(corruption: str) -> None:
    envelope = _envelope()
    if corruption == "platform":
        envelope = envelope.model_copy(update={"platform": "gitlab"})
    elif corruption == "repository":
        envelope = envelope.model_copy(update={"repository_id": "other/repo"})
    elif corruption == "request":
        envelope = envelope.model_copy(update={"change_request_number": REQUEST + 1})
    notes = [_note(envelope)]
    if corruption == "malformed":
        notes = [notes[0].model_copy(update={"body": OVERVIEW_START + "broken"})]
    elif corruption == "duplicate":
        notes.append(notes[0].model_copy(update={"id": 11}))
    client = FakeOverviewClient(notes)

    with pytest.raises(ReviewOverviewError):
        _publish(client)

    assert client.comments == notes
    assert client.writes == []


@pytest.mark.parametrize(
    "failure", ["identity_denied", "identity_empty", "identity_whitespace", "comments_denied"]
)
def test_inaccessible_discovery_never_means_confirmed_absence(failure: str) -> None:
    client = FakeOverviewClient()
    client.identity_error = failure == "identity_denied"
    if failure == "identity_empty":
        client.username = ""
    elif failure == "identity_whitespace":
        client.username = " \t\n"
    elif failure == "comments_denied":
        client.reads.append(ReviewPlatformClientError("Comments inaccessible."))

    with pytest.raises(ReviewOverviewError):
        _publish(client)

    assert client.writes == []


def test_confirmed_absence_creates_only_after_request_and_authority_recheck() -> None:
    human = _note().model_copy(update={"author_username": "human"})
    client = FakeOverviewClient([human])

    note, envelope = _publish(client)

    assert client.events == ["identity", "list", "state", "identity", "list", "create", "identity"]
    assert [kind for kind, _ in client.writes] == ["create"]
    assert decode_overview(note.body) == envelope
    assert human in client.comments
    assert envelope.history[0].sequence == 1
    assert envelope.complete_passes[0].projection_reference == envelope.history[0].pass_id


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "state,head", [("closed", NEXT_HEAD), ("merged", NEXT_HEAD), ("opened", "new-head")]
)
def test_request_guard_prevents_create_and_update(existing: bool, state: str, head: str) -> None:
    client = FakeOverviewClient([_note()] if existing else [])
    original = list(client.comments)
    client.request = client.request.model_copy(update={"state": state, "head_sha": head})

    with pytest.raises(ReviewOverviewError, match="closed or head changed"):
        _publish(client, head_sha=NEXT_HEAD)

    assert client.writes == []
    assert client.comments == original
    assert client.events == ["identity", "list", "state"]


@pytest.mark.parametrize("race", ["appeared", "disappeared", "replaced", "edited", "inaccessible"])
def test_read_before_write_rejects_changed_authority(race: str) -> None:
    original = _note()
    initial = [] if race == "appeared" else [original]
    client = FakeOverviewClient(initial, head_sha=NEXT_HEAD)
    client.reads.append(initial)
    if race == "disappeared":
        client.reads.append([])
    elif race == "replaced":
        client.reads.append([original.model_copy(update={"id": 999})])
    elif race == "edited":
        client.reads.append(
            [_note(_envelope().model_copy(update={"execution_notice": "Other run."}))]
        )
    elif race == "inaccessible":
        client.reads.append(ReviewPlatformClientError("Second read failed."))
    else:
        client.reads.append([original])

    expected_error = (
        "discovery failed" if race == "inaccessible" else "authority changed before publication"
    )
    with pytest.raises(ReviewOverviewError, match=expected_error):
        _publish(client, head_sha=NEXT_HEAD)

    assert client.writes == []
    assert client.comments == initial
    assert client.events == ["identity", "list", "state", "identity", "list"]


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("outcome", ["lost_response", "rejected"])
def test_uncertain_write_rediscovered_without_retry(
    existing: bool, outcome: Literal["lost_response", "rejected"]
) -> None:
    client = FakeOverviewClient([_note()] if existing else [], head_sha=NEXT_HEAD)
    original = list(client.comments)
    client.write_outcome = outcome

    if outcome == "lost_response":
        note, envelope = _publish(client, head_sha=NEXT_HEAD)
        assert note in client.comments
        assert decode_overview(note.body) == envelope
    else:
        with pytest.raises(ReviewOverviewError, match="could not be confirmed"):
            _publish(client, head_sha=NEXT_HEAD)
        assert client.comments == original

    assert len(client.writes) == 1
    assert client.events[-2:] == ["identity", "list"]
    assert client.events.count("list") == 3


@pytest.mark.parametrize("change", ["summary", "classification", "finding", "identity", "count"])
def test_metadata_cannot_change_finalized_meaning(change: str) -> None:
    client = FakeOverviewClient([_note()])
    artifact = _artifact()
    if change == "summary":
        artifact.summary = "Different conclusion."
    elif change == "classification":
        artifact.classification = "manual_review_only"
    elif change == "finding":
        artifact.findings[0].evidence = "Different evidence."
    elif change == "identity":
        artifact.findings[0].stable_identity = "different-finding"
    else:
        artifact.findings = []

    with pytest.raises(ReviewOverviewError, match="cannot change finalized review meaning"):
        ReviewOverviewCoordinator(client, "github").write_metadata(
            repository_id=REPOSITORY,
            change_request_number=REQUEST,
            head_sha=HEAD,
            pass_id="previous-pass",
            artifact=artifact,
        )

    assert client.writes == []
    assert client.comments == [_note()]


def test_metadata_updates_transport_without_changing_pass_identity_or_history() -> None:
    envelope = _envelope()
    artifact = _artifact()
    artifact.findings[0].inline_comment = PriorReviewInlineComment(
        comment_id="inline-1",
        comment_url="https://example.com/inline/1",
        status="published",
        anchor_file_path="src/api.py",
        anchor_line_start=42,
    )
    client = FakeOverviewClient([_note(envelope)])

    note = ReviewOverviewCoordinator(client, "github").write_metadata(
        repository_id=REPOSITORY,
        change_request_number=REQUEST,
        head_sha=HEAD,
        pass_id="previous-pass",
        artifact=artifact,
        projection_pending=False,
        projection_warning="Projection receipt repaired.",
    )

    updated = decode_overview(note.body)
    assert updated is not None
    assert updated.history == envelope.history
    assert updated.complete_passes[0] == envelope.complete_passes[0].model_copy(
        update={
            "artifact": artifact,
            "projection_pending": False,
            "projection_warning": "Projection receipt repaired.",
        }
    )
    assert note.id == 10
    assert [kind for kind, _ in client.writes] == ["update"]


def test_stale_metadata_pass_id_cannot_replace_current_authority() -> None:
    client = FakeOverviewClient([_note()])

    with pytest.raises(ReviewOverviewError, match="authority changed or is unavailable"):
        ReviewOverviewCoordinator(client, "github").write_metadata(
            repository_id=REPOSITORY,
            change_request_number=REQUEST,
            head_sha=HEAD,
            pass_id="stale-pass",
            projection_pending=False,
        )

    assert client.writes == []


def test_same_run_retains_identity_and_does_not_add_or_rewrite_history() -> None:
    client = FakeOverviewClient()
    first_note, first = _publish(client)
    client.events.clear()
    client.writes.clear()

    note, repeated = _publish(client)

    assert note == first_note
    assert repeated == first
    assert client.writes == []
    assert client.events == ["identity", "list"]


def test_pass_identity_is_independent_of_transport_note_id() -> None:
    first_client = FakeOverviewClient(head_sha=NEXT_HEAD)
    first_note, first = _publish(first_client, head_sha=NEXT_HEAD)
    second_client = FakeOverviewClient([_note()], head_sha=NEXT_HEAD)
    second_note, second = _publish(second_client, head_sha=NEXT_HEAD)

    assert first_note.id != second_note.id
    assert first.complete_passes[0].pass_id == second.complete_passes[0].pass_id
    assert (
        first.complete_passes[0].projection_reference
        == second.complete_passes[0].projection_reference
    )


def test_new_runs_retain_two_complete_passes_and_five_summaries() -> None:
    client = FakeOverviewClient()
    published: list[ReviewOverviewEnvelope] = []
    for number in range(7):
        head_sha = f"head-{number}"
        client.request = client.request.model_copy(update={"head_sha": head_sha})
        _, envelope = _publish(client, run_id=f"run-{number}", head_sha=head_sha)
        published.append(envelope)
        assert envelope.complete_passes[0].head_sha == head_sha
        assert envelope.complete_passes[0].diff_refs == _context(head_sha).diff_refs

    current = published[-1]
    assert len(current.complete_passes) == 2
    assert current.complete_passes[1] == published[-2].complete_passes[0]
    assert current.history == [envelope.history[0] for envelope in reversed(published[-5:])]
    assert current.complete_passes[0].sequence == 7
    assert len({envelope.history[0].pass_id for envelope in published}) == 7
    assert [kind for kind, _ in client.writes] == ["create", *(["update"] * 6)]


@pytest.mark.parametrize("existing", [False, True])
def test_failure_notice_preserves_completed_history_and_never_creates(existing: bool) -> None:
    client = FakeOverviewClient([_note()] if existing else [])
    coordinator = ReviewOverviewCoordinator(client, "github")

    coordinator.record_failure(
        repository_id=REPOSITORY,
        change_request_number=REQUEST,
        head_sha=HEAD,
        message="Failure detail. " * 200,
    )

    if not existing:
        assert client.writes == []
        assert client.comments == []
        return
    updated = decode_overview(client.comments[0].body)
    assert updated is not None
    assert updated.complete_passes == _envelope().complete_passes
    assert updated.history == _envelope().history
    assert updated.execution_notice == ("Failure detail. " * 200)[:2000]
    assert [kind for kind, _ in client.writes] == ["update"]


def test_failed_publication_preserves_previous_completed_history() -> None:
    previous = _envelope()
    client = FakeOverviewClient([_note(previous)], head_sha=NEXT_HEAD)
    client.write_outcome = "rejected"

    with pytest.raises(ReviewOverviewError, match="could not be confirmed"):
        _publish(client, head_sha=NEXT_HEAD)

    assert decode_overview(client.comments[0].body) == previous
    assert len(client.writes) == 1


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("existing", [False, True])
def test_provider_scope_is_preserved_on_create_and_update(
    platform: Literal["github", "gitlab"], existing: bool
) -> None:
    previous = _envelope().model_copy(update={"platform": platform})
    client = FakeOverviewClient([_note(previous)] if existing else [], head_sha=NEXT_HEAD)

    note, envelope = _publish(client, platform=platform, head_sha=NEXT_HEAD)

    assert envelope.platform == platform
    assert envelope.repository_id == REPOSITORY
    assert envelope.change_request_number == REQUEST
    assert envelope.complete_passes[0].head_sha == NEXT_HEAD
    assert envelope.complete_passes[0].diff_refs == _context(NEXT_HEAD).diff_refs
    assert decode_overview(note.body) == envelope
    assert [kind for kind, _ in client.writes] == ["update" if existing else "create"]
    if existing:
        assert envelope.complete_passes[1] == previous.complete_passes[0]


def _write_receipt(client: FakeOverviewClient, operation: str) -> None:
    coordinator = ReviewOverviewCoordinator(client, "github")
    if operation == "metadata":
        coordinator.write_metadata(
            repository_id=REPOSITORY,
            change_request_number=REQUEST,
            head_sha=HEAD,
            pass_id="previous-pass",
            projection_pending=False,
        )
    else:
        coordinator.record_failure(
            repository_id=REPOSITORY,
            change_request_number=REQUEST,
            head_sha=HEAD,
            message="Execution failed.",
        )


@pytest.mark.parametrize("operation", ["metadata", "failure_notice"])
@pytest.mark.parametrize("state,head", [("closed", HEAD), ("merged", HEAD), ("opened", "new-head")])
def test_receipt_writes_obey_request_guards(operation: str, state: str, head: str) -> None:
    client = FakeOverviewClient([_note()])
    client.request = client.request.model_copy(update={"state": state, "head_sha": head})

    with pytest.raises(ReviewOverviewError, match="closed or head changed"):
        _write_receipt(client, operation)

    assert client.writes == []
    assert client.comments == [_note()]


@pytest.mark.parametrize("operation", ["metadata", "failure_notice"])
def test_receipt_writes_recheck_authority_before_updating(operation: str) -> None:
    client = FakeOverviewClient([_note()])
    changed = _note(_envelope().model_copy(update={"execution_notice": "Concurrent writer."}))
    client.reads.extend([[_note()], [changed]])

    with pytest.raises(ReviewOverviewError, match="authority changed before publication"):
        _write_receipt(client, operation)

    assert client.writes == []


@pytest.mark.parametrize("operation", ["metadata", "failure_notice"])
@pytest.mark.parametrize("outcome", ["lost_response", "rejected"])
def test_receipt_write_failure_preserves_history_without_retry(
    operation: str, outcome: Literal["lost_response", "rejected"]
) -> None:
    previous = _envelope()
    client = FakeOverviewClient([_note(previous)])
    client.write_outcome = outcome

    if outcome == "lost_response":
        _write_receipt(client, operation)
    else:
        with pytest.raises(ReviewOverviewError, match="could not be confirmed"):
            _write_receipt(client, operation)

    persisted = decode_overview(client.comments[0].body)
    assert persisted is not None
    assert persisted.history == previous.history
    assert len(client.writes) == 1
    assert client.events[-2:] == ["identity", "list"]
    if outcome == "rejected":
        assert persisted == previous
    elif operation == "failure_notice":
        assert persisted.complete_passes == previous.complete_passes
    else:
        assert persisted.complete_passes[0].projection_pending is False


@pytest.mark.parametrize("recovery", ["inaccessible", "conflicting"])
def test_uncertain_write_with_unconfirmed_rediscovery_never_retries(recovery: str) -> None:
    previous = _note()
    client = FakeOverviewClient([previous], head_sha=NEXT_HEAD)
    client.write_outcome = "lost_response"
    client.reads.extend([[previous], [previous]])
    if recovery == "inaccessible":
        client.reads.append(ReviewPlatformClientError("Recovery read denied."))
    else:
        client.reads.append([previous])

    expected_error = "discovery failed" if recovery == "inaccessible" else "could not be confirmed"
    with pytest.raises(ReviewOverviewError, match=expected_error):
        _publish(client, head_sha=NEXT_HEAD)

    assert len(client.writes) == 1
    assert client.events[-2:] == ["identity", "list"]


def test_same_head_different_run_cannot_create_another_completed_pass() -> None:
    client = FakeOverviewClient()
    note, completed = _publish(client, run_id="first-run")
    client.events.clear()
    client.writes.clear()

    with pytest.raises(ReviewOverviewError, match="already has a completed review; reuse its pass"):
        _publish(client, run_id="different-run")

    assert client.writes == []
    assert client.events == ["identity", "list"]
    assert client.comments == [note]
    assert decode_overview(note.body) == completed


@pytest.mark.parametrize("change", ["summary", "finding"])
def test_same_pass_cannot_be_assigned_different_artifact(change: str) -> None:
    client = FakeOverviewClient()
    note, completed = _publish(client)
    client.events.clear()
    client.writes.clear()
    artifact = _artifact()
    if change == "summary":
        artifact.summary = "A different conclusion."
    else:
        artifact.findings[0].evidence = "A different error path."

    with pytest.raises(ReviewOverviewError, match="identity cannot be assigned new meaning"):
        ReviewOverviewCoordinator(client, "github").publish(
            repository_id=REPOSITORY,
            context=_context(),
            artifact=artifact,
            run_id="new-run",
            inline_decisions=[],
        )

    assert client.writes == []
    assert client.events == ["identity", "list"]
    assert client.comments == [note]
    assert decode_overview(note.body) == completed


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_restore_valid_factory_identity_preserves_completed_pass(
    platform: Literal["github", "gitlab"],
) -> None:
    identity = review_pass_identity(
        platform=platform,
        repository_id=REPOSITORY,
        change_request_number=REQUEST,
        head_sha=HEAD,
        run_id="original-run",
    )
    completed = (
        _envelope()
        .complete_passes[0]
        .model_copy(
            update={
                "pass_id": identity,
                "projection_reference": identity,
                "run_id": "original-run",
                "projection_pending": False,
            }
        )
    )
    before = completed.model_dump()
    client = FakeOverviewClient()

    note, restored = ReviewOverviewCoordinator(client, platform).restore(
        repository_id=REPOSITORY,
        change_request_number=REQUEST,
        review_pass=completed,
    )

    assert client.events == ["identity", "list", "state", "identity", "list", "create", "identity"]
    assert [kind for kind, _ in client.writes] == ["create"]
    assert decode_overview(note.body) == restored
    assert restored.platform == platform
    assert restored.repository_id == REPOSITORY
    assert restored.change_request_number == REQUEST
    assert restored.complete_passes == [completed.model_copy(update={"projection_pending": True})]
    assert restored.history == [completed.summary()]
    assert completed.model_dump() == before


@pytest.mark.parametrize("mismatch", ["repository", "platform", "request", "original_run"])
def test_restore_scope_mismatch_rejected_before_any_provider_access(mismatch: str) -> None:
    identity = review_pass_identity(
        platform="gitlab" if mismatch == "platform" else "github",
        repository_id="other/repository" if mismatch == "repository" else REPOSITORY,
        change_request_number=REQUEST + 1 if mismatch == "request" else REQUEST,
        head_sha=HEAD,
        run_id="original-run",
    )
    completed = (
        _envelope()
        .complete_passes[0]
        .model_copy(
            update={
                "pass_id": identity,
                "projection_reference": identity,
                "run_id": "different-run" if mismatch == "original_run" else "original-run",
            }
        )
    )
    client = FakeOverviewClient()
    client.identity_error = True

    with pytest.raises(ReviewOverviewError, match="recovery scope could not be verified"):
        ReviewOverviewCoordinator(client, "github").restore(
            repository_id=REPOSITORY,
            change_request_number=REQUEST,
            review_pass=completed,
        )

    assert client.events == []
    assert client.writes == []
    assert client.comments == []


@pytest.mark.parametrize("existing", [False, True])
def test_raw_read_timeout_after_committed_write_recovers_without_retry(existing: bool) -> None:
    client = FakeOverviewClient([_note()] if existing else [], head_sha=NEXT_HEAD)
    client.write_outcome = "raw_lost_response"

    note, envelope = _publish(client, head_sha=NEXT_HEAD)

    assert note in client.comments
    assert decode_overview(note.body) == envelope
    assert note.author_username == BOT
    assert note.id == (10 if existing else 100)
    assert [kind for kind, _ in client.writes] == ["update" if existing else "create"]
    assert client.events[-2:] == ["identity", "list"]
    assert client.events.count("list") == 3


@pytest.mark.parametrize("stage", ["identity", "discovery", "authority_recheck", "head"])
def test_raw_http_read_failures_are_normalized_before_any_write(stage: str) -> None:
    client = FakeOverviewClient([_note()], head_sha=NEXT_HEAD)
    error = httpx.ReadTimeout("Provider read timed out.")
    expected_error = "discovery failed"
    if stage == "identity":
        client.identity_exception = error
    elif stage == "discovery":
        client.reads.append(error)
    elif stage == "authority_recheck":
        client.reads.extend([[_note()], error])
    else:
        client.state_exception = error
        expected_error = "request verification failed"

    with pytest.raises(ReviewOverviewError, match=expected_error) as raised:
        _publish(client, head_sha=NEXT_HEAD)

    assert raised.value.__cause__ is error
    assert client.writes == []
    assert client.comments == [_note()]


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize(
    "fault", ["wrong_body", "old_body", "wrong_author", "missing_author", "zero_id", "negative_id"]
)
def test_invalid_success_response_requires_confirmed_authority_before_returning(
    existing: bool,
    committed: bool,
    fault: Literal[
        "wrong_body", "old_body", "wrong_author", "missing_author", "zero_id", "negative_id"
    ],
) -> None:
    client = FakeOverviewClient([_note()] if existing else [], head_sha=NEXT_HEAD)
    original = list(client.comments)
    client.persist_writes = committed
    client.response_fault = fault

    if committed:
        note, envelope = _publish(client, head_sha=NEXT_HEAD)
        assert note in client.comments
        assert decode_overview(note.body) == envelope
        assert note.author_username == BOT
        assert note.id == (10 if existing else 100)
    else:
        with pytest.raises(ReviewOverviewError, match="write could not be confirmed"):
            _publish(client, head_sha=NEXT_HEAD)
        assert client.comments == original

    assert [kind for kind, _ in client.writes] == ["update" if existing else "create"]
    assert client.events[-2:] == ["identity", "list"]
    assert client.events.count("list") == 3


@pytest.mark.parametrize("committed", [False, True])
def test_update_success_with_wrong_positive_id_requires_rediscovery(committed: bool) -> None:
    client = FakeOverviewClient([_note()], head_sha=NEXT_HEAD)
    client.persist_writes = committed
    client.response_fault = "wrong_update_id"

    if committed:
        note, envelope = _publish(client, head_sha=NEXT_HEAD)
        assert note.id == 10
        assert decode_overview(note.body) == envelope
    else:
        with pytest.raises(ReviewOverviewError, match="write could not be confirmed"):
            _publish(client, head_sha=NEXT_HEAD)
        assert client.comments == [_note()]

    assert [kind for kind, _ in client.writes] == ["update"]
    assert client.events[-2:] == ["identity", "list"]
    assert client.events.count("list") == 3

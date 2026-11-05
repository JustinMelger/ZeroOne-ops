from dataclasses import dataclass
from typing import Literal

import pytest

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
    ReviewClassification,
    ReviewComment,
    ReviewInlineCommentDecision,
)
from zeroone_ops.models.review_overview import ReviewOverviewEnvelope
from zeroone_ops.models.reviewed_commit import ReviewedCommitMetadata
from zeroone_ops.providers.review.platform import ReviewPlatformClientError
from zeroone_ops.services.review.publish import review_overview_codec as codec
from zeroone_ops.services.review.publish.review_finalization_service import (
    ReviewFinalizationResult,
    ReviewFinalizationService,
)
from zeroone_ops.services.review.publish.review_overview_coordinator import (
    ReviewOverviewCoordinator,
)
from zeroone_ops.services.review.publish.review_publisher import ReviewPublisher

from .support import build_artifact, build_context

REPOSITORY = "group/project"
BOT = "review-bot"
RUN = "review-run-17"
WORKFLOW_URL = "https://example.com/actions/runs/17"


class RecordingReviewClient:
    """Keep durable provider state distinct from attempted writes and inline receipts."""

    def __init__(self, context: ChangeRequestReviewContext, note_id: int = 101) -> None:
        self.context = context
        self.note_id = note_id
        self.comments: list[ReviewComment] = []
        self.events: list[str] = []
        self.durable_writes: list[ReviewOverviewEnvelope] = []
        self.failed_writes: set[int] = set()
        self.write_count = 0
        self.inline_calls = 0
        self.inline_bodies: list[str] = []
        self.discovery_error = False
        self.inline_error = False
        self.commit_reads: list[str] = []

    def get_reviewed_commit(self, *, repository_id: str, head_sha: str) -> ReviewedCommitMetadata:
        assert repository_id == REPOSITORY
        self.commit_reads.append(head_sha)
        return ReviewedCommitMetadata(head_sha=head_sha, title="Fix the reviewed branch")

    def get_current_user_username(self) -> str:
        return BOT

    def allows_machine_safe_comment_fallback(self) -> bool:
        pytest.fail("Overview publication must not fall back to legacy authority.")

    def list_change_request_comments(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> list[ReviewComment]:
        self._assert_scope(repository_id, change_request_number)
        if self.discovery_error:
            raise ReviewPlatformClientError("Comment history unavailable.")
        return [comment.model_copy(deep=True) for comment in self.comments]

    def get_change_request_state(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        self._assert_scope(repository_id, change_request_number)
        return ChangeRequestState(
            iid=change_request_number,
            head_sha=self.context.head_sha,
            state="opened",
            source_branch=self.context.source_branch,
            web_url=self.context.web_url,
        )

    def get_change_request(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestReviewCandidate:
        pytest.fail("Publication must not fetch model context or the full request diff.")

    def create_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
    ) -> ReviewComment:
        self._assert_scope(repository_id, change_request_number)
        assert not self.comments, "An existing overview must never produce a fallback comment."
        return self._write("overview_create", body)

    def update_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        note_id: int,
        body: str,
    ) -> ReviewComment:
        self._assert_scope(repository_id, change_request_number)
        assert self.comments and self.comments[0].id == note_id == self.note_id
        return self._write("overview_update", body)

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
        self._assert_scope(repository_id, change_request_number)
        assert self.context.diff_refs is not None
        assert (base_sha, start_sha, head_sha) == (
            self.context.diff_refs.base_sha,
            self.context.diff_refs.start_sha,
            self.context.head_sha,
        )
        assert (old_path, new_path, new_line) == ("src/service.py", "src/service.py", 1)
        assert body
        durable = self.current_overview()
        assert durable.complete_passes[0].projection_pending
        assert self.durable_writes, "Inline publication requires an earlier durable overview."
        self.events.append("inline")
        self.inline_calls += 1
        self.inline_bodies.append(body)
        if self.inline_error:
            raise ReviewPlatformClientError("Inline publication denied.")
        return ReviewComment(
            id=800,
            web_url="https://example.com/discussion/800",
            body=body,
            author_username=BOT,
        )

    def current_overview(self) -> ReviewOverviewEnvelope:
        assert len(self.comments) == 1
        envelope = codec.decode_overview(self.comments[0].body)
        assert envelope is not None
        return envelope

    def _write(self, event: str, body: str) -> ReviewComment:
        self.write_count += 1
        if self.write_count in self.failed_writes:
            self.events.append(f"{event}_failed")
            raise ReviewPlatformClientError("Provider rejected the write.")
        envelope = codec.decode_overview(body)
        assert envelope is not None
        note = ReviewComment(
            id=self.note_id,
            body=body,
            author_username=BOT,
            web_url=f"https://example.com/note/{self.note_id}",
        )
        self.comments = [note]
        self.durable_writes.append(envelope)
        self.events.append(event)
        return note.model_copy(deep=True)

    def _assert_scope(self, repository_id: str, change_request_number: int) -> None:
        assert repository_id == REPOSITORY
        assert change_request_number == self.context.change_request_number


@dataclass(frozen=True)
class ProjectionCall:
    artifact: PublishableReviewArtifact
    pass_id: str | None
    note_id: int | None
    note_url: str | None
    durable_overview: ReviewOverviewEnvelope


@dataclass(frozen=True)
class ProjectionReceipt:
    action: Literal["updated"] = "updated"
    warning: str | None = None


class RecordingProjection:
    def __init__(self, client: RecordingReviewClient) -> None:
        self.client = client
        self.calls: list[ProjectionCall] = []
        self.error: RuntimeError | None = None
        self.warning: str | None = None

    def project_review(
        self,
        *,
        repository_id: str,
        context: ChangeRequestReviewContext,
        reviewed_sha: str,
        artifact: PublishableReviewArtifact | None = None,
        classification: ReviewClassification | None = None,
        review_note_id: int | None = None,
        review_note_url: str | None = None,
        review_pass_id: str | None = None,
    ) -> ProjectionReceipt:
        assert repository_id == REPOSITORY
        assert reviewed_sha == context.head_sha
        assert artifact is not None
        assert classification is None
        durable = self.client.current_overview()
        assert durable.complete_passes[0].projection_pending
        assert durable.complete_passes[0].pass_id == review_pass_id
        self.calls.append(
            ProjectionCall(
                artifact.model_copy(deep=True),
                review_pass_id,
                review_note_id,
                review_note_url,
                durable,
            )
        )
        self.client.events.append("projection")
        if self.error is not None:
            raise self.error
        return ProjectionReceipt(warning=self.warning)


@dataclass
class PublicationHarness:
    client: RecordingReviewClient
    coordinator: ReviewOverviewCoordinator
    publisher: ReviewPublisher
    projection: RecordingProjection
    context: ChangeRequestReviewContext
    artifact: PublishableReviewArtifact
    decisions: list[ReviewInlineCommentDecision]

    def finalize(self, *, dry_run: bool = False) -> ReviewFinalizationResult:
        return ReviewFinalizationService(
            review_publisher=self.publisher,
            overview_coordinator=self.coordinator,
            review_projection_factory=lambda: self.projection,
            workflow_url=WORKFLOW_URL,
        ).finalize(
            run_id=RUN,
            repository_id=REPOSITORY,
            active_dry_run=dry_run,
            change_request=ChangeRequestReviewCandidate.model_validate(self.context.model_dump()),
            context=self.context,
            artifact=self.artifact,
            inline_comment_decisions=self.decisions,
        )


@pytest.mark.parametrize(
    "conflict",
    [
        "duplicate",
        "malformed",
        "changed_pass",
        "deleted",
        "head_changed",
        "closed",
        "state_unavailable",
    ],
)
def test_authority_conflict_after_inline_publication_withholds_projection(
    publication: PublicationHarness, monkeypatch: pytest.MonkeyPatch, conflict: str
) -> None:
    publish_inline = publication.client.create_change_request_inline_comment

    def publish_then_change_authority(**kwargs):
        inline = publish_inline(**kwargs)
        note = publication.client.comments[0]
        if conflict == "duplicate":
            publication.client.comments.append(note.model_copy(update={"id": note.id + 1}))
        elif conflict == "malformed":
            publication.client.comments[0] = note.model_copy(
                update={"body": "<!-- zeroone:review-overview:v1\ninvalid -->"}
            )
        elif conflict == "changed_pass":
            envelope = codec.decode_overview(note.body)
            current = envelope.complete_passes[0].model_copy(update={"pass_id": "another-pass"})
            replacement = envelope.model_copy(
                update={"complete_passes": [current], "history": [current.summary()]}
            )
            publication.client.comments[0] = note.model_copy(
                update={"body": codec.encode_overview(replacement)}
            )
        elif conflict == "deleted":
            publication.client.comments.clear()
        else:

            def changed_request(**kwargs):
                if conflict == "state_unavailable":
                    raise ReviewPlatformClientError("Request state unavailable.")
                return ChangeRequestState(
                    iid=publication.context.change_request_number,
                    head_sha="another-head"
                    if conflict == "head_changed"
                    else publication.context.head_sha,
                    state="closed" if conflict == "closed" else "opened",
                    source_branch=publication.context.source_branch,
                    web_url=publication.context.web_url,
                )

            monkeypatch.setattr(publication.client, "get_change_request_state", changed_request)
        return inline

    monkeypatch.setattr(
        publication.client, "create_change_request_inline_comment", publish_then_change_authority
    )
    before = publication.artifact.model_dump(mode="json")

    result = publication.finalize()

    assert result.error_message is None
    assert result.projection_warning is not None
    assert "projection is withheld" in result.publish_warning
    assert result.projection_retry_pending
    assert result.overview_pass.projection_pending
    assert result.overview_pass.artifact.findings[0].inline_comment.comment_id == "800"
    assert result.inline_comment_decisions[0].new_comment_id == "800"
    assert result.overview_pass.inline_decisions == result.inline_comment_decisions
    assert not publication.projection.calls
    assert publication.client.inline_calls == 1
    assert publication.client.write_count == len(publication.client.durable_writes) == 1
    assert publication.artifact.model_dump(mode="json") == before


@pytest.fixture(params=["github", "gitlab"])
def publication(request: pytest.FixtureRequest) -> PublicationHarness:
    context = build_context()
    artifact = build_artifact()
    finding = artifact.findings[0]
    client = RecordingReviewClient(context)
    coordinator = ReviewOverviewCoordinator(client, request.param)
    return PublicationHarness(
        client,
        coordinator,
        ReviewPublisher(client, overview_coordinator=coordinator),
        RecordingProjection(client),
        context,
        artifact,
        [
            ReviewInlineCommentDecision(
                finding_identity=finding.stable_identity,
                severity=finding.severity,
                file_path=finding.file_path,
                line_start=finding.line_start,
                line_end=finding.line_end,
                inline_comments_enabled=True,
                location_trust="trusted",
                existing_inline_comment_found=False,
                anchor_reuse_decision="new",
                anchor_reuse_reason="New trusted changed-line anchor.",
            )
        ],
    )


def test_real_finalization_stages_durable_pending_before_inline_and_projection(
    publication: PublicationHarness,
) -> None:
    before = publication.artifact.model_dump(mode="json")
    decisions_before = [decision.model_dump() for decision in publication.decisions]

    result = publication.finalize()

    assert publication.client.events == [
        "overview_create",
        "inline",
        "overview_update",
        "projection",
        "overview_update",
    ]
    initial, inline_receipt, projection_receipt = publication.client.durable_writes
    assert initial.complete_passes[0].artifact == publication.artifact
    assert initial.complete_passes[0].projection_pending
    assert initial.complete_passes[0].artifact.findings[0].inline_comment is None
    assert inline_receipt.complete_passes[0].projection_pending
    assert inline_receipt.complete_passes[0].artifact == result.artifact
    assert not projection_receipt.complete_passes[0].projection_pending
    assert result.error_message is result.publish_warning is result.projection_warning is None
    assert not result.projection_retry_pending
    assert result.projection_retry_warning is None
    assert result.overview_pass == projection_receipt.complete_passes[0]
    assert result.review_pass_id == result.overview_pass.pass_id
    assert result.overview_pass.run_id == RUN
    assert result.overview_pass.workflow_url == WORKFLOW_URL
    assert all(
        envelope.history == initial.history for envelope in publication.client.durable_writes
    )
    assert result.artifact.findings[0].inline_comment is not None
    assert result.artifact.findings[0].inline_comment.comment_id == "800"
    assert result.inline_comment_decisions[0].new_comment_id == "800"
    assert result.inline_comment_decisions[0].authoritative_note_id == result.note_id
    assert result.review_result == result.artifact.to_review_result()
    assert publication.artifact.model_dump(mode="json") == before
    assert [decision.model_dump() for decision in publication.decisions] == decisions_before


@pytest.mark.parametrize("failed_writes", [{2}, {3}, {2, 3}])
def test_metadata_failure_is_warning_and_local_pass_preserves_actual_inline_artifact(
    publication: PublicationHarness,
    failed_writes: set[int],
) -> None:
    before = publication.artifact.model_dump(mode="json")
    publication.client.failed_writes = failed_writes

    result = publication.finalize()

    assert result.error_message is None
    assert result.publish_warning is not None
    assert "metadata" in result.publish_warning
    assert len(publication.projection.calls) == publication.client.inline_calls == 1
    assert result.note_id == publication.client.note_id
    assert result.overview_pass is not None
    assert (
        result.overview_pass.artifact == result.artifact == publication.projection.calls[0].artifact
    )
    assert result.overview_pass.artifact.findings[0].inline_comment is not None
    assert result.overview_pass.artifact.findings[0].inline_comment.comment_id == "800"
    assert result.overview_pass.inline_decisions == result.inline_comment_decisions
    assert result.projection_warning is None
    assert result.overview_pass.projection_pending == (3 in failed_writes)
    assert result.projection_retry_pending == (3 in failed_writes)
    assert result.overview_pass.projection_warning == result.projection_retry_warning
    durable = publication.client.current_overview()
    if {2, 3}.issubset(failed_writes):
        assert durable.complete_passes[0].artifact.findings[0].inline_comment is None
    else:
        assert durable.complete_passes[0].artifact == result.artifact
        assert durable.complete_passes[0].inline_decisions == result.inline_comment_decisions
    if 3 not in failed_writes:
        assert durable.complete_passes[0] == result.overview_pass
        assert publication.client.events == [
            "overview_create",
            "inline",
            "overview_update_failed",
            "projection",
            "overview_update",
        ]
        before_projection = publication.projection.calls[0].durable_overview.complete_passes[0]
        assert before_projection.projection_pending
        assert before_projection.artifact.findings[0].inline_comment is None
        assert durable.history == publication.client.durable_writes[0].history
    if 3 in failed_writes:
        assert durable.complete_passes[0].projection_pending
        assert "pending repair evidence" in result.publish_warning
        assert result.projection_retry_warning is not None
        assert "pending repair evidence" in result.projection_retry_warning
    else:
        assert result.projection_retry_warning is None
    assert publication.artifact.model_dump(mode="json") == before


@pytest.mark.parametrize("failure", ["exception", "decision_warning"])
def test_projection_failure_preserves_pending_and_receipt_without_republishing_inline(
    publication: PublicationHarness,
    failure: str,
) -> None:
    if failure == "exception":
        publication.projection.error = RuntimeError("Issue projection unavailable.")
    else:
        publication.projection.warning = "Work item could not be updated."

    result = publication.finalize()

    assert result.error_message is None
    assert result.projection_warning is not None
    assert result.projection_retry_pending
    assert result.projection_retry_warning == result.projection_warning
    assert publication.client.inline_calls == 1
    persisted = publication.client.current_overview().complete_passes[0]
    assert persisted.projection_pending
    assert persisted.projection_warning == result.projection_warning
    assert persisted == result.overview_pass
    assert persisted.pass_id == result.review_pass_id


def test_inline_discussion_preserves_accepted_reasoning_with_safe_escaping(
    publication: PublicationHarness,
) -> None:
    finding = publication.artifact.findings[0]
    finding.evidence = "<!-- evidence --> <script>run()</script> & customer"
    finding.explanation = "`tenant_id` < expected & [foreign]"
    finding.suggested_follow_up = "Add *tenant* tests for `<tag>`."
    before = publication.artifact.model_dump(mode="json")

    result = publication.finalize()

    assert result.error_message is None
    assert publication.client.inline_bodies == [
        "Missing test coverage.\n\n"
        "Evidence: &lt;!-- evidence --&gt; &lt;script&gt;run()&lt;/script&gt; &amp; customer\n\n"
        r"Impact: \`tenant\_id\` &lt; expected &amp; \[foreign\]"
        "\n\n"
        r"Suggested follow-up: Add \*tenant\* tests for \`&lt;tag&gt;\`.",
    ]
    assert publication.artifact.model_dump(mode="json") == before
    assert result.artifact.findings[0].evidence == finding.evidence
    assert result.artifact.findings[0].explanation == finding.explanation
    assert result.artifact.findings[0].suggested_follow_up == finding.suggested_follow_up


def test_initial_publication_failure_prevents_inline_projection_and_receipts(
    publication: PublicationHarness,
) -> None:
    publication.client.failed_writes = {1}
    before = publication.artifact.model_dump(mode="json")

    result = publication.finalize()

    assert result.error_message is not None
    assert "overview publish failed" in result.error_message
    assert result.publish_warning is None
    assert result.note_id is None
    assert result.review_pass_id is None
    assert result.overview_pass is None
    assert publication.client.events == ["overview_create_failed"]
    assert publication.client.comments == []
    assert publication.client.durable_writes == []
    assert publication.client.inline_calls == 0
    assert publication.projection.calls == []
    assert publication.artifact.model_dump(mode="json") == before


@pytest.mark.parametrize(
    "classification", ["findings_present", "no_findings", "manual_review_only"]
)
def test_malformed_authority_is_publication_failure_not_an_empty_review(
    publication: PublicationHarness,
    classification: ReviewClassification,
) -> None:
    publication.artifact = build_artifact(classification=classification)
    publication.client.comments = [
        ReviewComment(
            id=101,
            author_username=BOT,
            body=codec.OVERVIEW_START + "broken evidence",
        )
    ]
    before = [comment.model_dump() for comment in publication.client.comments]

    result = publication.finalize()

    assert result.error_message is not None
    assert "malformed" in result.error_message
    assert result.review_pass_id is None
    assert result.overview_pass is None
    assert result.artifact.classification == classification
    assert publication.client.events == []
    assert publication.projection.calls == []
    assert [comment.model_dump() for comment in publication.client.comments] == before


def test_inaccessible_history_never_triggers_legacy_or_empty_history_fallback(
    publication: PublicationHarness,
) -> None:
    publication.client.discovery_error = True

    result = publication.finalize()

    assert result.error_message is not None
    assert "discovery failed" in result.error_message
    assert publication.client.events == []
    assert publication.projection.calls == []


@pytest.mark.parametrize("classification", ["no_findings", "manual_review_only"])
def test_valid_zero_finding_artifact_is_a_completed_pass_not_malformed_authority(
    publication: PublicationHarness,
    classification: ReviewClassification,
) -> None:
    publication.artifact = build_artifact(classification=classification)
    publication.decisions = []
    before = publication.artifact.model_dump(mode="json")

    result = publication.finalize()

    assert result.error_message is None
    assert result.review_pass_id is not None
    assert result.overview_pass is not None
    assert result.overview_pass.artifact.classification == classification
    assert result.overview_pass.artifact.findings == []
    assert publication.client.current_overview().history[0].findings_count == 0
    assert publication.client.inline_calls == 0
    assert len(publication.projection.calls) == 1
    assert publication.artifact.model_dump(mode="json") == before


def test_overflow_preserves_existing_body_without_inline_projection_or_fallback(
    publication: PublicationHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_note, previous = publication.coordinator.publish(
        repository_id=REPOSITORY,
        context=publication.context,
        artifact=publication.artifact,
        run_id="previous-run",
        inline_decisions=[],
    )
    assert previous_note.body is not None
    previous_body = previous_note.body
    budget = len(previous_body.encode("utf-8"))
    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", budget)
    assert publication.context.diff_refs is not None
    publication.context = publication.context.model_copy(
        update={
            "head_sha": "next-head",
            "diff_refs": publication.context.diff_refs.model_copy(update={"head_sha": "next-head"}),
        }
    )
    publication.client.context = publication.context
    publication.client.events.clear()
    before = publication.artifact.model_dump(mode="json")

    result = publication.finalize()

    assert result.error_message is not None
    assert "payload budget" in result.error_message
    assert publication.client.comments[0].body == previous_body
    assert publication.client.current_overview() == previous
    assert publication.client.write_count == 1
    assert publication.client.events == []
    assert publication.client.inline_calls == 0
    assert publication.projection.calls == []
    assert publication.artifact.model_dump(mode="json") == before


@pytest.mark.parametrize("note_id", [101, 909])
def test_finalization_projects_logical_pass_receipt_not_transport_identity(
    publication: PublicationHarness,
    note_id: int,
) -> None:
    publication.client.note_id = note_id

    result = publication.finalize()

    call = publication.projection.calls[0]
    assert result.review_pass_id is not None
    assert call.pass_id == result.review_pass_id
    assert call.pass_id != str(note_id)
    assert call.note_id == result.note_id == note_id
    assert call.note_url == result.note_url == f"https://example.com/note/{note_id}"
    assert call.durable_overview.complete_passes[0].pass_id == result.review_pass_id
    assert result.overview_pass is not None
    assert result.overview_pass.projection_reference == result.review_pass_id
    assert call.artifact == result.artifact


def test_inline_failure_is_warning_after_initial_overview_not_publication_failure(
    publication: PublicationHarness,
) -> None:
    publication.client.inline_error = True

    result = publication.finalize()

    assert result.error_message is None
    assert result.publish_warning is not None
    assert result.inline_comment_decisions[0].anchor_reuse_reason == "inline_publish_failed"
    assert result.artifact.findings[0].inline_comment is None
    assert result.overview_pass is not None
    assert result.overview_pass.artifact == result.artifact
    assert len(publication.projection.calls) == 1
    assert publication.client.events[0:2] == ["overview_create", "inline"]


def test_dry_run_avoids_all_real_publication_side_effects(publication: PublicationHarness) -> None:
    result = publication.finalize(dry_run=True)

    assert result.error_message is None
    assert result.review_pass_id is None
    assert result.overview_pass is None
    assert publication.client.comments == []
    assert publication.client.commit_reads == []
    assert publication.client.events == []
    assert publication.projection.calls == []

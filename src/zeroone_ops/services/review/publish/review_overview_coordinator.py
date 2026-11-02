"""Coordinate exact-request overview authority and guarded provider writes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

import httpx

from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
    ReviewComment,
)
from zeroone_ops.models.review_overview import ReviewOverviewEnvelope, ReviewOverviewPass
from zeroone_ops.models.state import ReviewInlineCommentDecision
from zeroone_ops.providers.review.platform import (
    ChangeRequestReviewPlatformProtocol,
    ReviewPlatformClientError,
)
from zeroone_ops.services.review.publish.review_overview_codec import (
    ReviewOverviewError,
    decode_overview,
)
from zeroone_ops.services.review.publish.review_overview_renderer import render_overview


def review_pass_identity(
    *,
    platform: str,
    repository_id: str,
    change_request_number: int,
    head_sha: str,
    run_id: str,
) -> str:
    """Bind a logical pass to its original run and exact repository/request scope."""
    return str(
        uuid5(
            NAMESPACE_URL,
            repr((platform, repository_id, change_request_number, head_sha, run_id)),
        )
    )


class ReviewOverviewCoordinator:
    """Keep publication identity and verified bot-owned transport separate."""

    def __init__(
        self, client: ChangeRequestReviewPlatformProtocol, platform: Literal["github", "gitlab"]
    ) -> None:
        """Retain transport without loading credentials or reading provider state."""
        self.client = client
        self.platform = platform

    def discover(
        self, *, repository_id: str, change_request_number: int
    ) -> tuple[ReviewComment | None, ReviewOverviewEnvelope | None]:
        """Resolve unique valid authority using complete exact-request discovery."""
        try:
            username = self.client.get_current_user_username()
            if not username:
                raise ReviewOverviewError("Verified review bot identity is unavailable.")
            comments = self.client.list_change_request_comments(
                repository_id=repository_id, change_request_number=change_request_number
            )
        except (ReviewPlatformClientError, httpx.HTTPError) as error:
            raise ReviewOverviewError("Review overview discovery failed.") from error
        matches: list[tuple[ReviewComment, ReviewOverviewEnvelope]] = []
        for comment in comments:
            if comment.author_username != username:
                continue
            envelope = decode_overview(comment.body)
            if envelope is None:
                continue
            if (
                envelope.platform != self.platform
                or envelope.repository_id != repository_id
                or envelope.change_request_number != change_request_number
            ):
                raise ReviewOverviewError("Managed review overview has mismatched request scope.")
            matches.append((comment, envelope))
        if len(matches) > 1:
            raise ReviewOverviewError("Multiple verified review overviews prevent publication.")
        return matches[0] if matches else (None, None)

    def publish(
        self,
        *,
        repository_id: str,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
        run_id: str,
        inline_decisions: list[ReviewInlineCommentDecision],
        workflow_url: str | None = None,
    ) -> tuple[ReviewComment, ReviewOverviewEnvelope]:
        """Stage complete finalized evidence before inline or projection side effects."""
        note, previous = self.discover(
            repository_id=repository_id, change_request_number=context.change_request_number
        )
        pass_id = review_pass_identity(
            platform=self.platform,
            repository_id=repository_id,
            change_request_number=context.change_request_number,
            head_sha=context.head_sha,
            run_id=run_id,
        )
        if previous is not None and previous.complete_passes[0].pass_id == pass_id:
            if note is None:
                raise ReviewOverviewError("Existing review overview transport is unavailable.")
            if previous.complete_passes[0].artifact != artifact:
                raise ReviewOverviewError(
                    "Completed review identity cannot be assigned new meaning."
                )
            return note, previous
        if previous is not None and previous.complete_passes[0].head_sha == context.head_sha:
            raise ReviewOverviewError("This head already has a completed review; reuse its pass.")
        completed = ReviewOverviewPass(
            pass_id=pass_id,
            projection_reference=pass_id,
            run_id=run_id,
            head_sha=context.head_sha,
            sequence=1 if previous is None else previous.history[0].sequence + 1,
            completed_at=datetime.now(UTC),
            diff_refs=context.diff_refs,
            artifact=artifact.model_copy(deep=True),
            inline_decisions=[decision.model_copy(deep=True) for decision in inline_decisions],
            workflow_url=workflow_url,
            verified_work_item_url=(
                None
                if context.remediation_context is None
                else context.remediation_context.verified_work_item_url
            ),
        )
        envelope = ReviewOverviewEnvelope(
            platform=self.platform,
            repository_id=repository_id,
            change_request_number=context.change_request_number,
            complete_passes=[completed, *(previous.complete_passes[:1] if previous else [])],
            history=[completed.summary(), *(previous.history[:4] if previous else [])],
        )
        return self._write(
            repository_id=repository_id,
            head_sha=context.head_sha,
            expected_note=note,
            expected_envelope=previous,
            envelope=envelope,
        ), envelope

    def write_metadata(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        head_sha: str,
        pass_id: str,
        artifact: PublishableReviewArtifact | None = None,
        inline_decisions: list[ReviewInlineCommentDecision] | None = None,
        projection_pending: bool | None = None,
        projection_warning: str | None = None,
    ) -> ReviewComment:
        """Update publication receipts for the same logical pass without adding history."""
        note, envelope = self.discover(
            repository_id=repository_id, change_request_number=change_request_number
        )
        if note is None or envelope is None or envelope.complete_passes[0].pass_id != pass_id:
            raise ReviewOverviewError(
                "Current review overview authority changed or is unavailable."
            )
        current = envelope.complete_passes[0]
        updates: dict[str, object] = {}
        if artifact is not None:
            # Only inline transport references may change after the first durable write.
            original = current.artifact.model_dump(exclude={"findings"})
            replacement = artifact.model_dump(exclude={"findings"})
            original_findings = [
                finding.model_dump(exclude={"inline_comment"})
                for finding in current.artifact.findings
            ]
            replacement_findings = [
                finding.model_dump(exclude={"inline_comment"}) for finding in artifact.findings
            ]
            if original != replacement or original_findings != replacement_findings:
                raise ReviewOverviewError(
                    "Publication metadata cannot change finalized review meaning."
                )
            updates["artifact"] = artifact.model_copy(deep=True)
        if inline_decisions is not None:
            updates["inline_decisions"] = [
                decision.model_copy(deep=True) for decision in inline_decisions
            ]
        if projection_pending is not None:
            updates.update(
                projection_pending=projection_pending, projection_warning=projection_warning
            )
        updated_pass = ReviewOverviewPass.model_validate({**current.model_dump(), **updates})
        updated = ReviewOverviewEnvelope.model_validate(
            {
                **envelope.model_dump(),
                "complete_passes": [updated_pass, *envelope.complete_passes[1:]],
            }
        )
        return self._write(
            repository_id=repository_id,
            head_sha=head_sha,
            expected_note=note,
            expected_envelope=envelope,
            envelope=updated,
        )

    def restore(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        review_pass: ReviewOverviewPass,
    ) -> tuple[ReviewComment, ReviewOverviewEnvelope]:
        """Recreate confirmed missing transport from complete evidence, keeping its receipt."""
        expected_identity = review_pass_identity(
            platform=self.platform,
            repository_id=repository_id,
            change_request_number=change_request_number,
            head_sha=review_pass.head_sha,
            run_id=review_pass.run_id,
        )
        if review_pass.pass_id != expected_identity:
            raise ReviewOverviewError("Local review recovery scope could not be verified.")
        note, existing = self.discover(
            repository_id=repository_id, change_request_number=change_request_number
        )
        if note is not None or existing is not None:
            raise ReviewOverviewError("Review overview appeared before transport restoration.")
        restored = review_pass.model_copy(deep=True, update={"projection_pending": True})
        envelope = ReviewOverviewEnvelope(
            platform=self.platform,
            repository_id=repository_id,
            change_request_number=change_request_number,
            complete_passes=[restored],
            history=[restored.summary()],
        )
        return self._write(
            repository_id=repository_id,
            head_sha=review_pass.head_sha,
            expected_note=None,
            expected_envelope=None,
            envelope=envelope,
        ), envelope

    def record_failure(
        self, *, repository_id: str, change_request_number: int, head_sha: str, message: str
    ) -> None:
        """Attach a bounded execution notice without creating a completed pass."""
        note, envelope = self.discover(
            repository_id=repository_id, change_request_number=change_request_number
        )
        if note is None or envelope is None:
            return
        updated = ReviewOverviewEnvelope.model_validate(
            {**envelope.model_dump(), "execution_notice": message[:2000]}
        )
        self._write(
            repository_id=repository_id,
            head_sha=head_sha,
            expected_note=note,
            expected_envelope=envelope,
            envelope=updated,
        )

    def _write(
        self,
        *,
        repository_id: str,
        head_sha: str,
        expected_note: ReviewComment | None,
        expected_envelope: ReviewOverviewEnvelope | None,
        envelope: ReviewOverviewEnvelope,
    ) -> ReviewComment:
        body = render_overview(envelope)
        try:
            request = self.client.get_change_request_state(
                repository_id=repository_id, change_request_number=envelope.change_request_number
            )
        except (ReviewPlatformClientError, httpx.HTTPError) as error:
            raise ReviewOverviewError("Review request verification failed.") from error
        if request.state != "opened" or request.head_sha != head_sha:
            raise ReviewOverviewError(
                "Review overview write withheld: request closed or head changed."
            )
        note, current = self.discover(
            repository_id=repository_id, change_request_number=envelope.change_request_number
        )
        if current != expected_envelope or (None if note is None else note.id) != (
            None if expected_note is None else expected_note.id
        ):
            raise ReviewOverviewError("Review overview authority changed before publication.")
        try:
            if note is None:
                response = self.client.create_change_request_comment(
                    repository_id=repository_id,
                    change_request_number=envelope.change_request_number,
                    body=body,
                )
            else:
                response = self.client.update_change_request_comment(
                    repository_id=repository_id,
                    change_request_number=envelope.change_request_number,
                    note_id=note.id,
                    body=body,
                )
            username = self.client.get_current_user_username()
            if (
                response.id <= 0
                or (note is not None and response.id != note.id)
                or response.author_username != username
                or decode_overview(response.body) != envelope
            ):
                raise ReviewOverviewError(
                    "Review overview response did not confirm intended authority."
                )
            return response
        except (ReviewOverviewError, ReviewPlatformClientError, httpx.HTTPError) as error:
            # A lost response may conceal a successful write; never retry it blindly.
            recovered_note, recovered = self.discover(
                repository_id=repository_id, change_request_number=envelope.change_request_number
            )
            if recovered_note is not None and recovered == envelope:
                return recovered_note
            raise ReviewOverviewError("Review overview write could not be confirmed.") from error

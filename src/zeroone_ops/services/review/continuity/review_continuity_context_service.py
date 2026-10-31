"""Load authoritative review references and bounded earlier-review context."""

from __future__ import annotations

import logging

import httpx

from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    PriorReviewContext,
    PriorReviewPass,
    ReviewComment,
)
from zeroone_ops.providers.review.platform import (
    ChangeRequestReviewPlatformProtocol,
    ReviewPlatformClientError,
)
from zeroone_ops.services.review.continuity.review_prior_comment_loader import (
    ChangeRequestPriorCommentLoader,
    extract_machine_safe_review_note_payload,
)
from zeroone_ops.services.review.continuity.review_prior_comment_parser import (
    ChangeRequestPriorCommentParser,
)
from zeroone_ops.services.review.state.review_state_service import ReviewStateService

_UNRESOLVED_BOT_AUTHOR_USERNAME = object()
AUTHORITATIVE_REVIEW_CLASSIFICATIONS = frozenset(
    {"no_findings", "findings_present", "manual_review_only"}
)


class ReviewContinuityContextService:
    """Resolve review references with one shared per-runner author cache."""

    def __init__(
        self,
        *,
        review_client: ChangeRequestReviewPlatformProtocol,
        review_state_service: ReviewStateService,
        logger: logging.Logger,
        prior_context_service: ChangeRequestPriorCommentLoader | None = None,
        prior_note_parser: ChangeRequestPriorCommentParser | None = None,
    ) -> None:
        """Retain dependencies without reading provider or persisted state."""
        self.review_client = review_client
        self.review_state_service = review_state_service
        self.logger = logger
        self.prior_context_service = prior_context_service
        self.prior_note_parser = prior_note_parser or ChangeRequestPriorCommentParser()
        self._resolved_bot_author_username: str | None | object = _UNRESOLVED_BOT_AUTHOR_USERNAME

    def _resolve_prior_comment_author_username(
        self,
        *,
        run_id: str,
        change_request_number: int,
        current_head_sha: str,
    ) -> str | None:
        """Resolve and cache the current review-platform username behind the active token."""
        if self._resolved_bot_author_username is not _UNRESOLVED_BOT_AUTHOR_USERNAME:
            return self._resolved_bot_author_username  # type: ignore[return-value]
        try:
            resolved_username = self.review_client.get_current_user_username()
        except Exception:
            self.logger.warning(
                "review current user lookup failed; prior-comment author filter disabled",
                extra={
                    "run_id": run_id,
                    "change_request_number": change_request_number,
                    "head_sha": current_head_sha,
                },
            )
            self._resolved_bot_author_username = None
            return None
        self._resolved_bot_author_username = resolved_username
        self.logger.info(
            f"review current user resolved (username={resolved_username})",
            extra={
                "run_id": run_id,
                "change_request_number": change_request_number,
                "head_sha": current_head_sha,
                "bot_author_username": resolved_username,
            },
        )
        return resolved_username

    def load_prior_review_context(
        self,
        *,
        run_id: str,
        repository_id: str,
        change_request_number: int,
        current_head_sha: str,
    ) -> PriorReviewContext | None:
        """Load prior review context from the latest earlier machine-safe review comment."""
        prior_context_service = self.prior_context_service or ChangeRequestPriorCommentLoader(
            self.review_client,
            bot_author_username=self._resolve_prior_comment_author_username(
                run_id=run_id,
                change_request_number=change_request_number,
                current_head_sha=current_head_sha,
            ),
        )
        try:
            selection_result = prior_context_service.select_latest_prior_review_note(
                repository_id=repository_id,
                change_request_number=change_request_number,
                current_head_sha=current_head_sha,
            )
        except Exception:  # pragma: no cover - exercised via integration stubs
            self.logger.warning(
                "review prior comment lookup failed; omitting continuity context",
                extra={
                    "run_id": run_id,
                    "change_request_number": change_request_number,
                    "head_sha": current_head_sha,
                },
            )
            return None
        if selection_result.selected_note is None:
            self.logger.info(
                (
                    "review prior comment not found "
                    f"[reason={selection_result.reason_code} "
                    f"considered={selection_result.considered_note_count} "
                    f"author={selection_result.author_matched_note_count} "
                    f"machine={selection_result.machine_safe_note_count} "
                    f"parseable={selection_result.parseable_note_count} "
                    f"current_sha={selection_result.current_sha_skipped_count}]"
                ),
                extra={
                    "run_id": run_id,
                    "change_request_number": change_request_number,
                    "head_sha": current_head_sha,
                    "considered_note_count": selection_result.considered_note_count,
                    "author_matched_note_count": selection_result.author_matched_note_count,
                    "machine_safe_note_count": selection_result.machine_safe_note_count,
                    "parseable_note_count": selection_result.parseable_note_count,
                    "current_sha_skipped_count": selection_result.current_sha_skipped_count,
                    "reason_code": selection_result.reason_code,
                },
            )
            return None

        try:
            parse_result = self.prior_note_parser.parse_note(
                note=selection_result.selected_note,
                expected_change_request_number=change_request_number,
            )
        except Exception:  # pragma: no cover - defensive guard for malformed parser wiring
            self.logger.warning(
                (
                    "review prior comment parse crashed; omitting continuity context "
                    f"(selected_note_id={selection_result.selected_note.id})"
                ),
                extra={
                    "run_id": run_id,
                    "change_request_number": change_request_number,
                    "head_sha": current_head_sha,
                    "selected_note_id": selection_result.selected_note.id,
                },
            )
            return None
        if parse_result.prior_review_pass is None:
            self.logger.warning(
                (
                    "review prior comment parse failed; omitting continuity context "
                    f"[note={selection_result.selected_note.id} "
                    f"reason={selection_result.reason_code}] "
                    f"{parse_result.message}"
                ),
                extra={
                    "run_id": run_id,
                    "change_request_number": change_request_number,
                    "head_sha": current_head_sha,
                    "selected_note_id": selection_result.selected_note.id,
                    "considered_note_count": selection_result.considered_note_count,
                    "author_matched_note_count": selection_result.author_matched_note_count,
                    "machine_safe_note_count": selection_result.machine_safe_note_count,
                    "parseable_note_count": selection_result.parseable_note_count,
                    "current_sha_skipped_count": selection_result.current_sha_skipped_count,
                    "reason_code": selection_result.reason_code,
                },
            )
            return None

        self.logger.info(
            (
                "review prior comment selected "
                f"[note={selection_result.selected_note.id} "
                f"prior={parse_result.prior_review_pass.reviewed_head_sha} "
                f"reason={selection_result.reason_code} "
                f"considered={selection_result.considered_note_count} "
                f"author={selection_result.author_matched_note_count} "
                f"machine={selection_result.machine_safe_note_count} "
                f"parseable={selection_result.parseable_note_count} "
                f"current_sha={selection_result.current_sha_skipped_count}]"
            ),
            extra={
                "run_id": run_id,
                "change_request_number": change_request_number,
                "head_sha": current_head_sha,
                "selected_note_id": selection_result.selected_note.id,
                "considered_note_count": selection_result.considered_note_count,
                "author_matched_note_count": selection_result.author_matched_note_count,
                "machine_safe_note_count": selection_result.machine_safe_note_count,
                "parseable_note_count": selection_result.parseable_note_count,
                "current_sha_skipped_count": selection_result.current_sha_skipped_count,
                "reason_code": selection_result.reason_code,
                "prior_head_sha": parse_result.prior_review_pass.reviewed_head_sha,
            },
        )
        return PriorReviewContext(
            change_request_number=change_request_number,
            passes=[parse_result.prior_review_pass],
        )

    def load_same_sha_review_reference(
        self,
        *,
        run_id: str,
        repository_id: str,
        change_request: ChangeRequestReviewCandidate,
    ) -> PriorReviewPass | None:
        """Return the authoritative existing review reference for one change-request SHA."""
        review_state = self.review_state_service.state.reviews.get(
            f"{change_request.change_request_number}:{change_request.head_sha}"
        )
        if review_state is not None and _is_authoritative_review_classification(
            review_state.status
        ):
            return PriorReviewPass(
                reviewed_head_sha=review_state.head_sha,
                classification=review_state.status,
                findings_count=review_state.findings_count,
                summary=review_state.summary,
                note_url=review_state.note_url,
                findings=[],
            )

        try:
            notes = self.review_client.list_change_request_comments(
                repository_id=repository_id,
                change_request_number=change_request.change_request_number,
            )
        except (ReviewPlatformClientError, httpx.HTTPError, OSError) as exc:
            self.logger.warning(
                "review same-sha lookup via provider comment failed; continuing without reuse",
                extra={
                    "run_id": run_id,
                    "change_request_number": change_request.change_request_number,
                    "head_sha": change_request.head_sha,
                    "error": str(exc),
                },
            )
            return None
        bot_author_username = self._resolve_prior_comment_author_username(
            run_id=run_id,
            change_request_number=change_request.change_request_number,
            current_head_sha=change_request.head_sha,
        )
        if bot_author_username is None:
            if self.review_client.allows_machine_safe_comment_fallback():
                self.logger.warning(
                    "review same-sha comment reuse falling back to machine-safe payload only",
                    extra={
                        "run_id": run_id,
                        "change_request_number": change_request.change_request_number,
                        "head_sha": change_request.head_sha,
                    },
                )
            else:
                self.logger.info(
                    "review same-sha comment reuse disabled because bot username is unresolved",
                    extra={
                        "run_id": run_id,
                        "change_request_number": change_request.change_request_number,
                        "head_sha": change_request.head_sha,
                    },
                )
                return None
        candidate_notes: list[ReviewComment] = []
        for note in notes:
            if bot_author_username is not None and note.author_username != bot_author_username:
                continue
            payload = extract_machine_safe_review_note_payload(note.body)
            if payload is None:
                continue
            reviewed_head_sha = payload.get("reviewed_head_sha")
            classification = payload.get("classification")
            if reviewed_head_sha != change_request.head_sha:
                continue
            if not isinstance(classification, str) or not _is_authoritative_review_classification(
                classification
            ):
                continue
            candidate_notes.append(note)
        if not candidate_notes:
            return None
        selected_note = sorted(
            candidate_notes,
            key=lambda note: ((note.created_at or ""), note.id),
            reverse=True,
        )[0]
        parse_result = self.prior_note_parser.parse_note(
            note=selected_note,
            expected_change_request_number=change_request.change_request_number,
        )
        return parse_result.prior_review_pass


def _is_authoritative_review_classification(classification: str) -> bool:
    """Return whether one review classification is authoritative for same-SHA reuse."""
    return classification in AUTHORITATIVE_REVIEW_CLASSIFICATIONS

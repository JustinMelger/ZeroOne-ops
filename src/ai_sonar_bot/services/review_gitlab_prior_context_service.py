"""GitLab-backed prior review note selection."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient

_MACHINE_SAFE_REVIEW_NOTE_PREFIX = "<!-- ai-sonar-bot:review-note:v1\n"
_MACHINE_SAFE_REVIEW_NOTE_SUFFIX = "\n-->"
_MACHINE_SAFE_REVIEW_NOTE_SCHEMA = "ai-sonar-bot/review-note/v1"
_DEFAULT_BOT_AUTHOR_USERNAME = "ai-sonar-bot"


@dataclass(frozen=True)
class PriorReviewNoteSelectionResult:
    """Capture bounded MR note selection for prior review reconstruction."""

    selected_note: MergeRequestNote | None
    considered_note_count: int
    machine_safe_note_count: int
    message: str


class ReviewGitLabPriorContextService:
    """Fetch and select the latest earlier machine-safe review note on one MR."""

    def __init__(
        self,
        review_client: GitLabReviewClient,
        *,
        bot_author_username: str = _DEFAULT_BOT_AUTHOR_USERNAME,
    ) -> None:
        """Initialize the GitLab-backed prior review note selector."""
        self.review_client = review_client
        self.bot_author_username = bot_author_username

    def select_latest_prior_review_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        current_head_sha: str,
    ) -> PriorReviewNoteSelectionResult:
        """Return the latest earlier machine-safe bot review note for one MR."""
        notes = self.review_client.list_merge_request_notes(
            project_id=project_id,
            merge_request_iid=merge_request_iid,
        )
        considered_notes = [
            note
            for note in notes
            if self._is_machine_safe_bot_review_note(note)
        ]
        candidate_notes = []
        for note in considered_notes:
            payload = _extract_machine_safe_review_note_payload(note.body)
            if payload is None:
                continue
            reviewed_head_sha = payload.get("reviewed_head_sha")
            if not isinstance(reviewed_head_sha, str):
                continue
            if reviewed_head_sha == current_head_sha:
                continue
            candidate_notes.append(note)

        selected_note = None
        if candidate_notes:
            selected_note = sorted(
                candidate_notes,
                key=lambda note: ((note.created_at or ""), note.id),
                reverse=True,
            )[0]

        if selected_note is None:
            return PriorReviewNoteSelectionResult(
                selected_note=None,
                considered_note_count=len(notes),
                machine_safe_note_count=len(considered_notes),
                message=(
                    "No earlier machine-safe bot prior review note found on this merge request."
                ),
            )

        return PriorReviewNoteSelectionResult(
            selected_note=selected_note,
            considered_note_count=len(notes),
            machine_safe_note_count=len(considered_notes),
            message="Selected latest earlier machine-safe bot review note.",
        )

    def _is_machine_safe_bot_review_note(self, note: MergeRequestNote) -> bool:
        """Return whether one MR note is a parseable machine-safe bot review note."""
        if note.author_username != self.bot_author_username:
            return False
        if note.body is None:
            return False
        return _has_machine_safe_review_note_block(note.body)


def _has_machine_safe_review_note_block(body: str) -> bool:
    """Return whether one MR note contains the bounded machine-safe block."""
    return _MACHINE_SAFE_REVIEW_NOTE_PREFIX in body



def _extract_machine_safe_review_note_payload(body: str | None) -> dict[str, object] | None:
    """Extract one machine-safe review note payload when present and valid."""
    if body is None:
        return None
    start = body.find(_MACHINE_SAFE_REVIEW_NOTE_PREFIX)
    if start == -1:
        return None
    start += len(_MACHINE_SAFE_REVIEW_NOTE_PREFIX)
    end = body.find(_MACHINE_SAFE_REVIEW_NOTE_SUFFIX, start)
    if end == -1:
        return None
    try:
        payload = json.loads(body[start:end])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != _MACHINE_SAFE_REVIEW_NOTE_SCHEMA:
        return None
    return payload

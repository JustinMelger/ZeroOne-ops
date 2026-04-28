"""Strict parser for dashboard operator-policy commands."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from zeroone_ops.models.gitlab import GitLabIssueNote

_POLICY_PREFIX = "/zeroone policy"
_SEVERITY_PATTERN = re.compile(
    r"^/zeroone policy severity (?P<verb>enable|disable) (?P<severity>low|medium|high)$"
)
_ISSUE_CLASS_PATTERN = re.compile(
    (
        r"^/zeroone policy issue-class "
        r"(?P<verb>exclude|include) "
        r"(?P<source>[a-z0-9_-]+)\s*/\s*(?P<issue_key>\S+)$"
    )
)
_SHOW_PATTERN = re.compile(r"^/zeroone policy (?P<verb>show|inspect)$")


class DashboardPolicyAction(BaseModel):
    """Represent one accepted operator-policy action."""

    action_type: Literal[
        "show_policy",
        "enable_severity",
        "disable_severity",
        "exclude_issue_class",
        "include_issue_class",
    ]
    raw_command: str
    note_id: int | None = None
    author_username: str | None = None
    severity: Literal["low", "medium", "high"] | None = None
    source: str | None = None
    issue_key: str | None = None


class DashboardPolicyActionParseResult(BaseModel):
    """Describe one policy-command parse outcome."""

    matched_prefix: bool
    accepted: bool
    raw_command: str
    error: str | None = None
    action: DashboardPolicyAction | None = None
    note_id: int | None = None


class DashboardPolicyActionService:
    """Parse bounded dashboard policy commands from issue notes."""

    def parse_note(self, note: GitLabIssueNote) -> DashboardPolicyActionParseResult:
        """Parse one issue note into a typed policy action when valid."""
        command = self._normalize_command(note.body)
        if command is None:
            return DashboardPolicyActionParseResult(
                matched_prefix=False,
                accepted=False,
                raw_command=note.body or "",
                note_id=note.id,
                error=None,
            )
        matched = _SHOW_PATTERN.fullmatch(command)
        if matched is not None:
            return DashboardPolicyActionParseResult(
                matched_prefix=True,
                accepted=True,
                raw_command=command,
                note_id=note.id,
                action=DashboardPolicyAction(
                    action_type="show_policy",
                    raw_command=command,
                    note_id=note.id,
                    author_username=note.author_username,
                ),
            )
        matched = _SEVERITY_PATTERN.fullmatch(command)
        if matched is not None:
            verb = matched.group("verb")
            severity = matched.group("severity")
            return DashboardPolicyActionParseResult(
                matched_prefix=True,
                accepted=True,
                raw_command=command,
                note_id=note.id,
                action=DashboardPolicyAction(
                    action_type=(
                        "enable_severity" if verb == "enable" else "disable_severity"
                    ),
                    raw_command=command,
                    note_id=note.id,
                    author_username=note.author_username,
                    severity=severity,
                ),
            )
        matched = _ISSUE_CLASS_PATTERN.fullmatch(command)
        if matched is not None:
            verb = matched.group("verb")
            return DashboardPolicyActionParseResult(
                matched_prefix=True,
                accepted=True,
                raw_command=command,
                note_id=note.id,
                action=DashboardPolicyAction(
                    action_type=(
                        "exclude_issue_class"
                        if verb == "exclude"
                        else "include_issue_class"
                    ),
                    raw_command=command,
                    note_id=note.id,
                    author_username=note.author_username,
                    source=matched.group("source"),
                    issue_key=matched.group("issue_key"),
                ),
            )
        return DashboardPolicyActionParseResult(
            matched_prefix=True,
            accepted=False,
            raw_command=command,
            note_id=note.id,
            error=(
                "Unsupported policy command. Use `/zeroone policy show`, "
                "`/zeroone policy severity enable|disable <low|medium|high>`, or "
                "`/zeroone policy issue-class exclude|include <source> / <issue_key>`."
            ),
        )

    def parse_notes(self, notes: list[GitLabIssueNote]) -> list[DashboardPolicyActionParseResult]:
        """Parse all issue notes and return matched or ignored outcomes."""
        return [self.parse_note(note) for note in notes]

    def accepted_actions(self, notes: list[GitLabIssueNote]) -> list[DashboardPolicyAction]:
        """Return accepted policy actions in note order."""
        parsed = self.parse_notes(notes)
        return [result.action for result in parsed if result.action is not None]

    def _normalize_command(self, body: str | None) -> str | None:
        """Return one strict single-line command when the note uses the policy prefix."""
        if body is None:
            return None
        stripped = body.strip()
        if not stripped.startswith(_POLICY_PREFIX):
            return None
        if "\n" in stripped:
            return stripped
        return " ".join(stripped.split())

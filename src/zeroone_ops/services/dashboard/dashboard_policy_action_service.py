"""Strict parser for dashboard operator-policy commands."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from zeroone_ops.models.dashboard import (
    DashboardIssueClassPolicyStateEntry,
    DashboardPolicyState,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.gitlab import GitLabIssueNote

_POLICY_PREFIX = "/zeroone policy"
DashboardPolicySeverity = Literal["low", "medium", "high"]
_SEVERITY_PATTERN = re.compile(
    r"^/zeroone policy severity (?P<verb>enable|disable) (?P<severity>low|medium|high)$"
)
_ISSUE_CLASS_PATTERN = re.compile(
    r"^/zeroone policy issue-class "
    r"(?P<verb>exclude|include) "
    r"(?P<source>[a-z0-9_-]+)\s*/\s*(?P<issue_key>\S+)$"
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
    severity: DashboardPolicySeverity | None = None
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
            severity = _severity_literal(matched.group("severity"))
            return DashboardPolicyActionParseResult(
                matched_prefix=True,
                accepted=True,
                raw_command=command,
                note_id=note.id,
                action=DashboardPolicyAction(
                    action_type=("enable_severity" if verb == "enable" else "disable_severity"),
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
                        "exclude_issue_class" if verb == "exclude" else "include_issue_class"
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
        actions = [result.action for result in parsed if result.action is not None]
        return sorted(
            actions,
            key=lambda action: (
                self._note_sort_key(notes, action.note_id),
                action.note_id or 0,
            ),
        )

    def apply_actions(
        self,
        *,
        policy_state: DashboardPolicyState,
        notes: list[GitLabIssueNote],
    ) -> DashboardPolicyState:
        """Return the policy state after replaying accepted dashboard note actions."""
        updated_state = policy_state.model_copy(deep=True)
        notes_by_id = {note.id: note for note in notes}
        for action in self.accepted_actions(notes):
            if action.action_type == "enable_severity":
                updated_state = self._upsert_severity_state(
                    policy_state=updated_state,
                    severity=action.severity,
                    enabled=True,
                    reason=None,
                    note=notes_by_id.get(action.note_id or -1),
                )
            elif action.action_type == "disable_severity":
                updated_state = self._upsert_severity_state(
                    policy_state=updated_state,
                    severity=action.severity,
                    enabled=False,
                    reason="Disabled by dashboard policy action.",
                    note=notes_by_id.get(action.note_id or -1),
                )
            elif action.action_type == "exclude_issue_class":
                updated_state = self._upsert_issue_class_exclusion(
                    policy_state=updated_state,
                    source=action.source,
                    issue_key=action.issue_key,
                    reason="Excluded by dashboard policy action.",
                    note=notes_by_id.get(action.note_id or -1),
                )
            elif action.action_type == "include_issue_class":
                updated_state = self._remove_issue_class_exclusion(
                    policy_state=updated_state,
                    source=action.source,
                    issue_key=action.issue_key,
                )
        return updated_state

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

    def _note_sort_key(self, notes: list[GitLabIssueNote], note_id: int | None) -> tuple[str, int]:
        """Return one deterministic sort key for policy-note replay."""
        note = next((candidate for candidate in notes if candidate.id == note_id), None)
        return ((note.created_at or "") if note is not None else "", note_id or 0)

    def _upsert_severity_state(
        self,
        *,
        policy_state: DashboardPolicyState,
        severity: DashboardPolicySeverity | None,
        enabled: bool,
        reason: str | None,
        note: GitLabIssueNote | None,
    ) -> DashboardPolicyState:
        """Return the updated policy state for one severity command."""
        if severity is None:
            return policy_state
        updated_entry = DashboardSeverityPolicyStateEntry(
            severity=severity,
            enabled=enabled,
            reason=reason,
            updated_at=None,
            updated_by=note.author_username if note is not None else None,
            note_id=note.id if note is not None else None,
        )
        if note is not None and note.created_at:
            from datetime import datetime

            updated_entry.updated_at = datetime.fromisoformat(
                note.created_at.replace("Z", "+00:00")
            )
        severity_entries = list(policy_state.severity_policy)
        for index, entry in enumerate(severity_entries):
            if entry.severity == severity:
                severity_entries[index] = updated_entry
                return policy_state.model_copy(update={"severity_policy": severity_entries})
        severity_entries.append(updated_entry)
        severity_entries.sort(key=lambda entry: ("low", "medium", "high").index(entry.severity))
        return policy_state.model_copy(update={"severity_policy": severity_entries})

    def _upsert_issue_class_exclusion(
        self,
        *,
        policy_state: DashboardPolicyState,
        source: str | None,
        issue_key: str | None,
        reason: str,
        note: GitLabIssueNote | None,
    ) -> DashboardPolicyState:
        """Return the updated policy state for one issue-class exclusion command."""
        if not source or not issue_key:
            return policy_state
        updated_entry = DashboardIssueClassPolicyStateEntry(
            source=source,
            issue_key=issue_key,
            reason=reason,
            updated_at=None,
            updated_by=note.author_username if note is not None else None,
            note_id=note.id if note is not None else None,
        )
        if note is not None and note.created_at:
            from datetime import datetime

            updated_entry.updated_at = datetime.fromisoformat(
                note.created_at.replace("Z", "+00:00")
            )
        entries = list(policy_state.issue_class_exclusions)
        for index, entry in enumerate(entries):
            if entry.source == source and entry.issue_key == issue_key:
                entries[index] = updated_entry
                return policy_state.model_copy(update={"issue_class_exclusions": entries})
        entries.append(updated_entry)
        entries.sort(key=lambda entry: (entry.source, entry.issue_key))
        return policy_state.model_copy(update={"issue_class_exclusions": entries})

    def _remove_issue_class_exclusion(
        self,
        *,
        policy_state: DashboardPolicyState,
        source: str | None,
        issue_key: str | None,
    ) -> DashboardPolicyState:
        """Return the updated policy state for one issue-class include command."""
        if not source or not issue_key:
            return policy_state
        entries = [
            entry
            for entry in policy_state.issue_class_exclusions
            if not (entry.source == source and entry.issue_key == issue_key)
        ]
        return policy_state.model_copy(update={"issue_class_exclusions": entries})


def _severity_literal(value: str) -> DashboardPolicySeverity:
    """Return one validated severity literal from a regex match."""
    if value == "low":
        return "low"
    if value == "medium":
        return "medium"
    if value == "high":
        return "high"
    raise ValueError(f"Unsupported severity literal: {value}")

"""Provider-neutral policy command parsing and replay."""

from __future__ import annotations

import re
from datetime import datetime

from zeroone_ops.models.policy import (
    PolicyAction,
    PolicyActionParseResult,
    PolicyCommentSource,
    PolicyIssueClassStateEntry,
    PolicySeverity,
    PolicySeverityStateEntry,
    PolicyState,
)

_POLICY_PREFIX = "/zeroone policy"
_SEVERITY_PATTERN = re.compile(
    r"^/zeroone policy severity (?P<verb>enable|disable) (?P<severity>low|medium|high)$"
)
_ISSUE_CLASS_PATTERN = re.compile(
    r"^/zeroone policy issue-class "
    r"(?P<verb>exclude|include) "
    r"(?P<source>[a-z0-9_-]+)\s*/\s*(?P<issue_key>\S+)$"
)
_SHOW_PATTERN = re.compile(r"^/zeroone policy (?P<verb>show|inspect)$")
_SEVERITY_ORDER: tuple[PolicySeverity, ...] = ("low", "medium", "high")


class PolicyActionService:
    """Parse bounded policy commands and replay them into canonical state."""

    def __init__(
        self,
        *,
        unsupported_command_hint: str = (
            "Unsupported policy command. Use the strict `/zeroone policy` "
            "forms shown in the command reference."
        ),
        disable_severity_reason: str = "Disabled by policy action.",
        exclude_issue_class_reason: str = "Excluded by policy action.",
    ) -> None:
        """Initialize the policy action service."""
        self.unsupported_command_hint = unsupported_command_hint
        self.disable_severity_reason = disable_severity_reason
        self.exclude_issue_class_reason = exclude_issue_class_reason

    def parse_source(self, source: PolicyCommentSource) -> PolicyActionParseResult:
        """Parse one comment source into a typed policy action when valid."""
        command = self._normalize_command(source.body)
        if command is None:
            return PolicyActionParseResult(
                matched_prefix=False,
                accepted=False,
                raw_command=source.body or "",
                comment_id=source.id,
                error=None,
            )
        matched = _SHOW_PATTERN.fullmatch(command)
        if matched is not None:
            return PolicyActionParseResult(
                matched_prefix=True,
                accepted=True,
                raw_command=command,
                comment_id=source.id,
                action=PolicyAction(
                    action_type="show_policy",
                    raw_command=command,
                    comment_id=source.id,
                    author_username=source.author_username,
                ),
            )
        matched = _SEVERITY_PATTERN.fullmatch(command)
        if matched is not None:
            verb = matched.group("verb")
            severity = _severity_literal(matched.group("severity"))
            return PolicyActionParseResult(
                matched_prefix=True,
                accepted=True,
                raw_command=command,
                comment_id=source.id,
                action=PolicyAction(
                    action_type=("enable_severity" if verb == "enable" else "disable_severity"),
                    raw_command=command,
                    comment_id=source.id,
                    author_username=source.author_username,
                    severity=severity,
                ),
            )
        matched = _ISSUE_CLASS_PATTERN.fullmatch(command)
        if matched is not None:
            verb = matched.group("verb")
            return PolicyActionParseResult(
                matched_prefix=True,
                accepted=True,
                raw_command=command,
                comment_id=source.id,
                action=PolicyAction(
                    action_type=(
                        "exclude_issue_class" if verb == "exclude" else "include_issue_class"
                    ),
                    raw_command=command,
                    comment_id=source.id,
                    author_username=source.author_username,
                    source=matched.group("source"),
                    issue_key=matched.group("issue_key"),
                ),
            )
        return PolicyActionParseResult(
            matched_prefix=True,
            accepted=False,
            raw_command=command,
            comment_id=source.id,
            error=self.unsupported_command_hint,
        )

    def parse_sources(self, sources: list[PolicyCommentSource]) -> list[PolicyActionParseResult]:
        """Parse all sources and return matched or ignored outcomes."""
        return [self.parse_source(source) for source in sources]

    def accepted_actions(self, sources: list[PolicyCommentSource]) -> list[PolicyAction]:
        """Return accepted policy actions in source order."""
        parsed = self.parse_sources(sources)
        actions = [result.action for result in parsed if result.action is not None]
        return sorted(
            actions,
            key=lambda action: (
                self.source_sort_key(sources, action.comment_id),
                action.comment_id or 0,
            ),
        )

    def apply_actions(
        self,
        *,
        policy_state: PolicyState,
        sources: list[PolicyCommentSource],
    ) -> PolicyState:
        """Return the policy state after replaying accepted comment actions."""
        updated_state = policy_state.model_copy(deep=True)
        sources_by_id = {source.id: source for source in sources}
        for action in self.accepted_actions(sources):
            if action.action_type == "enable_severity":
                updated_state = self._upsert_severity_state(
                    policy_state=updated_state,
                    severity=action.severity,
                    enabled=True,
                    reason=None,
                    source=sources_by_id.get(action.comment_id or -1),
                )
            elif action.action_type == "disable_severity":
                updated_state = self._upsert_severity_state(
                    policy_state=updated_state,
                    severity=action.severity,
                    enabled=False,
                    reason=self.disable_severity_reason,
                    source=sources_by_id.get(action.comment_id or -1),
                )
            elif action.action_type == "exclude_issue_class":
                updated_state = self._upsert_issue_class_exclusion(
                    policy_state=updated_state,
                    source_name=action.source,
                    issue_key=action.issue_key,
                    reason=self.exclude_issue_class_reason,
                    source=sources_by_id.get(action.comment_id or -1),
                )
            elif action.action_type == "include_issue_class":
                updated_state = self._remove_issue_class_exclusion(
                    policy_state=updated_state,
                    source_name=action.source,
                    issue_key=action.issue_key,
                )
        return updated_state

    def apply_action(
        self,
        *,
        policy_state: PolicyState,
        action: PolicyAction,
        source: PolicyCommentSource | None,
    ) -> PolicyState:
        """Return the policy state after applying one accepted action."""
        if action.action_type == "enable_severity":
            return self._upsert_severity_state(
                policy_state=policy_state,
                severity=action.severity,
                enabled=True,
                reason=None,
                source=source,
            )
        if action.action_type == "disable_severity":
            return self._upsert_severity_state(
                policy_state=policy_state,
                severity=action.severity,
                enabled=False,
                reason=self.disable_severity_reason,
                source=source,
            )
        if action.action_type == "exclude_issue_class":
            return self._upsert_issue_class_exclusion(
                policy_state=policy_state,
                source_name=action.source,
                issue_key=action.issue_key,
                reason=self.exclude_issue_class_reason,
                source=source,
            )
        if action.action_type == "include_issue_class":
            return self._remove_issue_class_exclusion(
                policy_state=policy_state,
                source_name=action.source,
                issue_key=action.issue_key,
            )
        return policy_state

    def source_sort_key(
        self,
        sources: list[PolicyCommentSource],
        comment_id: int | None,
    ) -> tuple[str, int]:
        """Return one deterministic sort key for policy replay."""
        source = next((candidate for candidate in sources if candidate.id == comment_id), None)
        return ((source.created_at or "") if source is not None else "", comment_id or 0)

    def _normalize_command(self, body: str | None) -> str | None:
        """Return one strict single-line command when the body uses the policy prefix."""
        if body is None:
            return None
        stripped = body.strip()
        if not stripped.startswith(_POLICY_PREFIX):
            return None
        if "\n" in stripped:
            return stripped
        return " ".join(stripped.split())

    def _upsert_severity_state(
        self,
        *,
        policy_state: PolicyState,
        severity: PolicySeverity | None,
        enabled: bool,
        reason: str | None,
        source: PolicyCommentSource | None,
    ) -> PolicyState:
        """Return the updated policy state for one severity command."""
        if severity is None:
            return policy_state
        updated_entry = PolicySeverityStateEntry(
            severity=severity,
            enabled=enabled,
            reason=reason,
            updated_at=None,
            updated_by=source.author_username if source is not None else None,
            comment_id=source.id if source is not None else None,
        )
        if source is not None and source.created_at:
            updated_entry.updated_at = datetime.fromisoformat(
                source.created_at.replace("Z", "+00:00")
            )
        severity_entries = list(policy_state.severity_policy)
        for index, entry in enumerate(severity_entries):
            if entry.severity == severity:
                severity_entries[index] = updated_entry
                return policy_state.model_copy(update={"severity_policy": severity_entries})
        severity_entries.append(updated_entry)
        severity_entries.sort(key=lambda entry: _SEVERITY_ORDER.index(entry.severity))
        return policy_state.model_copy(update={"severity_policy": severity_entries})

    def _upsert_issue_class_exclusion(
        self,
        *,
        policy_state: PolicyState,
        source_name: str | None,
        issue_key: str | None,
        reason: str,
        source: PolicyCommentSource | None,
    ) -> PolicyState:
        """Return the updated policy state for one issue-class exclusion command."""
        if not source_name or not issue_key:
            return policy_state
        updated_entry = PolicyIssueClassStateEntry(
            source=source_name,
            issue_key=issue_key,
            reason=reason,
            updated_at=None,
            updated_by=source.author_username if source is not None else None,
            comment_id=source.id if source is not None else None,
        )
        if source is not None and source.created_at:
            updated_entry.updated_at = datetime.fromisoformat(
                source.created_at.replace("Z", "+00:00")
            )
        entries = list(policy_state.issue_class_exclusions)
        for index, entry in enumerate(entries):
            if entry.source == source_name and entry.issue_key == issue_key:
                entries[index] = updated_entry
                return policy_state.model_copy(update={"issue_class_exclusions": entries})
        entries.append(updated_entry)
        entries.sort(key=lambda entry: (entry.source, entry.issue_key))
        return policy_state.model_copy(update={"issue_class_exclusions": entries})

    def _remove_issue_class_exclusion(
        self,
        *,
        policy_state: PolicyState,
        source_name: str | None,
        issue_key: str | None,
    ) -> PolicyState:
        """Return the updated policy state for one issue-class include command."""
        if not source_name or not issue_key:
            return policy_state
        entries = [
            entry
            for entry in policy_state.issue_class_exclusions
            if not (entry.source == source_name and entry.issue_key == issue_key)
        ]
        return policy_state.model_copy(update={"issue_class_exclusions": entries})


def _severity_literal(value: str) -> PolicySeverity:
    """Return one validated severity literal from a regex match."""
    if value == "low":
        return "low"
    if value == "medium":
        return "medium"
    if value == "high":
        return "high"
    raise ValueError(f"Unsupported severity literal: {value}")

"""Dashboard policy acknowledgement orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.dashboard import DashboardPolicyState
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.services.dashboard.dashboard_policy_action_service import (
    DashboardPolicyAction,
    DashboardPolicyActionParseResult,
    DashboardPolicyActionService,
)


@dataclass(frozen=True)
class DashboardPolicyAcknowledgementResult:
    """Summarize one acknowledgement publishing pass."""

    needed_count: int
    published_count: int
    skipped_existing_count: int
    failed_count: int


class DashboardPolicyAcknowledgementService:
    """Build and publish bounded acknowledgements for policy notes."""

    def __init__(
        self,
        *,
        policy_action_service: DashboardPolicyActionService | None = None,
    ) -> None:
        """Initialize the acknowledgement service."""
        self.policy_action_service = policy_action_service or DashboardPolicyActionService()

    def publish_acknowledgements(
        self,
        *,
        client: GitLabDashboardClient,
        project_id: str,
        issue_iid: int,
        notes: list[GitLabIssueNote],
        parsed_results: list[DashboardPolicyActionParseResult],
        initial_policy_state: DashboardPolicyState,
        dry_run: bool,
    ) -> DashboardPolicyAcknowledgementResult:
        """Publish missing acknowledgements for accepted or rejected prefixed notes."""
        notes_by_id = {note.id: note for note in notes}
        existing_markers = {
            marker
            for note in notes
            for marker in [self._marker_from_body(note.body)]
            if marker is not None
        }
        needed_count = 0
        published_count = 0
        skipped_existing_count = 0
        failed_count = 0
        current_state = initial_policy_state.model_copy(deep=True)

        accepted_results = [
            result for result in parsed_results if result.accepted and result.action is not None
        ]
        accepted_results.sort(
            key=lambda result: self.policy_action_service._note_sort_key(notes, result.note_id)
        )

        effective_change_by_note_id: dict[int, bool] = {}
        for result in accepted_results:
            action = result.action
            if action is None or result.note_id is None:
                continue
            note = notes_by_id.get(result.note_id)
            effective_change = self._effective_change(
                policy_state=current_state,
                action=action,
            )
            effective_change_by_note_id[result.note_id] = effective_change
            current_state = self.policy_action_service.apply_action(
                policy_state=current_state,
                action=action,
                note=note,
            )

        for result in parsed_results:
            if not result.matched_prefix:
                continue
            if result.note_id is None:
                continue
            if not result.accepted and result.error is None:
                continue
            marker = self._marker(note_id=result.note_id, accepted=result.accepted)
            needed_count += 1
            if marker in existing_markers:
                skipped_existing_count += 1
                continue
            body = self._build_body(
                result=result,
                effective_change=effective_change_by_note_id.get(result.note_id),
            )
            if dry_run:
                published_count += 1
                existing_markers.add(marker)
                continue
            try:
                client.create_issue_note(
                    project_id=project_id,
                    issue_iid=issue_iid,
                    body=body,
                )
            except Exception:
                failed_count += 1
                continue
            published_count += 1
            existing_markers.add(marker)

        return DashboardPolicyAcknowledgementResult(
            needed_count=needed_count,
            published_count=published_count,
            skipped_existing_count=skipped_existing_count,
            failed_count=failed_count,
        )

    def _build_body(
        self,
        *,
        result: DashboardPolicyActionParseResult,
        effective_change: bool | None,
    ) -> str:
        """Build one acknowledgement note body."""
        if result.note_id is None:
            raise ValueError("Policy acknowledgement requires a note ID.")
        marker = self._marker(note_id=result.note_id, accepted=result.accepted)
        if result.accepted and result.action is not None:
            status_line = self._accepted_status_line(
                note_id=result.note_id,
                action=result.action,
                effective_change=effective_change,
            )
        else:
            status_line = (
                f"Policy command rejected for note #{result.note_id}. "
                f"{result.error or 'Unsupported policy command.'}"
            )
        return f"{status_line}\n\n<!-- {marker} -->"

    def _accepted_status_line(
        self,
        *,
        note_id: int,
        action: DashboardPolicyAction,
        effective_change: bool | None,
    ) -> str:
        """Build one accepted acknowledgement summary."""
        changed = effective_change is not False
        if action.action_type == "show_policy":
            return (
                f"Policy command accepted for note #{note_id}. "
                "Current dashboard policy is reflected in the dashboard body."
            )
        if action.action_type == "enable_severity" and action.severity is not None:
            if changed:
                return (
                    f"Policy command accepted for note #{note_id}. "
                    f"Enabled severity `{action.severity}`."
                )
            return (
                f"Policy command accepted for note #{note_id}. "
                f"Severity `{action.severity}` was already enabled."
            )
        if action.action_type == "disable_severity" and action.severity is not None:
            if changed:
                return (
                    f"Policy command accepted for note #{note_id}. "
                    f"Disabled severity `{action.severity}`."
                )
            return (
                f"Policy command accepted for note #{note_id}. "
                f"Severity `{action.severity}` was already disabled."
            )
        if (
            action.action_type == "exclude_issue_class"
            and action.source is not None
            and action.issue_key is not None
        ):
            if changed:
                return (
                    f"Policy command accepted for note #{note_id}. "
                    f"Excluded issue class `{action.source} / {action.issue_key}`."
                )
            return (
                f"Policy command accepted for note #{note_id}. "
                f"Issue class `{action.source} / {action.issue_key}` was already excluded."
            )
        if (
            action.action_type == "include_issue_class"
            and action.source is not None
            and action.issue_key is not None
        ):
            if changed:
                return (
                    f"Policy command accepted for note #{note_id}. "
                    f"Included issue class `{action.source} / {action.issue_key}`."
                )
            return (
                f"Policy command accepted for note #{note_id}. "
                f"Issue class `{action.source} / {action.issue_key}` was already included."
            )
        return f"Policy command accepted for note #{note_id}."

    def _effective_change(
        self,
        *,
        policy_state: DashboardPolicyState,
        action: DashboardPolicyAction,
    ) -> bool:
        """Return whether one accepted action changes effective policy state."""
        if action.action_type == "show_policy":
            return False
        if action.action_type in {"enable_severity", "disable_severity"}:
            desired_enabled = action.action_type == "enable_severity"
            return self._severity_enabled(policy_state, action.severity) != desired_enabled
        if action.action_type == "exclude_issue_class":
            return not self._issue_class_excluded(policy_state, action.source, action.issue_key)
        if action.action_type == "include_issue_class":
            return self._issue_class_excluded(policy_state, action.source, action.issue_key)
        return False

    def _severity_enabled(
        self,
        policy_state: DashboardPolicyState,
        severity: str | None,
    ) -> bool | None:
        """Return the current enabled state for one severity, when present."""
        if severity is None:
            return None
        for entry in policy_state.severity_policy:
            if entry.severity == severity:
                return entry.enabled
        return None

    def _issue_class_excluded(
        self,
        policy_state: DashboardPolicyState,
        source: str | None,
        issue_key: str | None,
    ) -> bool:
        """Return whether one issue class is currently excluded."""
        if source is None or issue_key is None:
            return False
        return any(
            entry.source == source and entry.issue_key == issue_key
            for entry in policy_state.issue_class_exclusions
        )

    def _marker(self, *, note_id: int, accepted: bool) -> str:
        """Build one machine-owned acknowledgement marker."""
        outcome = "accepted" if accepted else "rejected"
        return f"zeroone-ops:policy-ack:v1 note={note_id} outcome={outcome}"

    def _marker_from_body(self, body: str | None) -> str | None:
        """Extract one acknowledgement marker from a note body when present."""
        if body is None:
            return None
        start = "<!-- "
        end = " -->"
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith(start) and stripped.endswith(end):
                marker = stripped.removeprefix(start).removesuffix(end)
                if marker.startswith("zeroone-ops:policy-ack:v1 "):
                    return marker
        return None

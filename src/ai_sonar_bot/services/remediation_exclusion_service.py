"""Remediation exclusion policy service."""

from __future__ import annotations

from dataclasses import dataclass

from ai_sonar_bot.models.dashboard import DashboardItem
from ai_sonar_bot.models.state import AppState, RemediationExclusionState
from ai_sonar_bot.services.state_store import StateStore


@dataclass(frozen=True)
class RemediationExclusionMutationResult:
    """Capture one exclusion mutation result."""

    exclusion: RemediationExclusionState | None
    created: bool = False
    replaced: bool = False
    removed: bool = False


class RemediationExclusionService:
    """Manage persisted remediation exclusions in app state."""

    def __init__(self, *, state_store: StateStore | None, state: AppState) -> None:
        """Initialize the remediation exclusion service."""
        self.state_store = state_store
        self.state = state

    def list_exclusions(self) -> list[RemediationExclusionState]:
        """Return exclusions in stable source/key/scope order."""
        return sorted(
            self.state.remediation_exclusions,
            key=lambda item: (item.source, item.issue_key, item.scope or ""),
        )

    def add_exclusion(
        self,
        *,
        source: str,
        issue_key: str,
        reason: str,
        scope: str | None = None,
        updated_by: str | None = None,
    ) -> RemediationExclusionMutationResult:
        """Create or replace one persisted remediation exclusion."""
        exclusion = RemediationExclusionState(
            source=source,
            issue_key=issue_key,
            scope=scope,
            reason=reason,
            updated_by=updated_by,
        )
        index = self._find_index(source=source, issue_key=issue_key, scope=scope)
        if index is None:
            self.state.remediation_exclusions.append(exclusion)
            self._save()
            return RemediationExclusionMutationResult(exclusion=exclusion, created=True)

        self.state.remediation_exclusions[index] = exclusion
        self._save()
        return RemediationExclusionMutationResult(exclusion=exclusion, replaced=True)

    def remove_exclusion(
        self,
        *,
        source: str,
        issue_key: str,
        scope: str | None = None,
    ) -> RemediationExclusionMutationResult:
        """Remove one persisted remediation exclusion when present."""
        index = self._find_index(source=source, issue_key=issue_key, scope=scope)
        if index is None:
            return RemediationExclusionMutationResult(exclusion=None, removed=False)
        exclusion = self.state.remediation_exclusions.pop(index)
        self._save()
        return RemediationExclusionMutationResult(exclusion=exclusion, removed=True)

    def matches_dashboard_item(self, item: DashboardItem) -> bool:
        """Return whether one dashboard item matches a persisted exclusion."""
        item_issue_key = self._dashboard_issue_key(item)
        if item_issue_key is None:
            return False
        for exclusion in self.state.remediation_exclusions:
            if exclusion.source != item.source or exclusion.issue_key != item_issue_key:
                continue
            if exclusion.scope is not None and not self._scope_matches(exclusion, item):
                continue
            return True
        return False

    def _find_index(self, *, source: str, issue_key: str, scope: str | None) -> int | None:
        for index, item in enumerate(self.state.remediation_exclusions):
            if item.source == source and item.issue_key == issue_key and item.scope == scope:
                return index
        return None

    def _save(self) -> None:
        if self.state_store is None:
            raise RuntimeError("Cannot persist remediation exclusions without a state store.")
        self.state_store.save(self.state)

    def _dashboard_issue_key(self, item: DashboardItem) -> str | None:
        """Return the normalized exclusion key for one dashboard item."""
        if item.source == "sonarqube":
            return item.rule
        return None

    def _scope_matches(self, exclusion: RemediationExclusionState, item: DashboardItem) -> bool:
        """Return whether one dashboard item satisfies one exclusion scope."""
        if exclusion.scope is None:
            return True
        if item.file is None:
            return False
        scope = exclusion.scope.rstrip("/")
        file_path = item.file.rstrip("/")
        return file_path == scope or file_path.startswith(f"{scope}/")

"""Build provider-neutral policy state and compact presentation."""

from collections.abc import Sequence

from zeroone_ops.models.policy import (
    PolicyIssueClassExclusionEntry,
    PolicySeverity,
    PolicySeverityEntry,
    PolicySeverityStateEntry,
    PolicyState,
    PolicyView,
)

_SEVERITY_ORDER: tuple[PolicySeverity, ...] = ("low", "medium", "high")
_DEFAULT_ENABLED_SEVERITIES = frozenset({"low", "medium"})


class PolicyViewBuilder:
    """Resolve bootstrap policy and render it without repository or provider access."""

    def __init__(self, *, bootstrap_severities: Sequence[str]) -> None:
        """Copy the configured severity seed without loading external dependencies."""
        self.enabled_severities = (
            frozenset(severity.lower() for severity in bootstrap_severities)
            or _DEFAULT_ENABLED_SEVERITIES
        )

    def resolve_policy_state(self, policy_state: PolicyState | None) -> PolicyState:
        """Copy existing policy, seeding severity rows only when none are present."""
        state = policy_state.model_copy(deep=True) if policy_state is not None else PolicyState()
        if not state.severity_policy:
            state.severity_policy = [
                PolicySeverityStateEntry(
                    severity=severity,
                    enabled=severity in self.enabled_severities,
                    reason=(
                        None
                        if severity in self.enabled_severities
                        else "Disabled by current config baseline."
                    ),
                    updated_by="config_seed",
                )
                for severity in _SEVERITY_ORDER
            ]
        return state

    def build(self, *, policy_state: PolicyState) -> PolicyView:
        """Build a stable compact view from resolved state without changing it."""
        entries = {entry.severity: entry for entry in policy_state.severity_policy}
        return PolicyView(
            severity_policy=[
                PolicySeverityEntry(
                    severity=severity,
                    enabled=entries[severity].enabled if severity in entries else False,
                    reason=entries[severity].reason if severity in entries else None,
                )
                for severity in _SEVERITY_ORDER
            ],
            excluded_issue_classes=[
                PolicyIssueClassExclusionEntry(
                    source=entry.source, issue_key=entry.issue_key, reason=entry.reason
                )
                for entry in policy_state.issue_class_exclusions
            ],
        )

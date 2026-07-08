"""Provider-neutral policy replay orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.policy import PolicyActionParseResult, PolicyCommentSource, PolicyState
from zeroone_ops.services.control_plane.policy_action_service import PolicyActionService


@dataclass(frozen=True)
class PolicyProcessingResult:
    """Summarize one policy replay pass over provider comments."""

    initial_policy_state: PolicyState
    resolved_policy_state: PolicyState
    parsed_results: list[PolicyActionParseResult]
    sources: list[PolicyCommentSource]

    @property
    def source_count(self) -> int:
        """Return the number of provider comments considered."""
        return len(self.sources)

    @property
    def matched_prefix_count(self) -> int:
        """Return the number of comments that matched the policy prefix."""
        return sum(1 for result in self.parsed_results if result.matched_prefix)

    @property
    def accepted_action_count(self) -> int:
        """Return the number of accepted actions."""
        return sum(1 for result in self.parsed_results if result.accepted)

    @property
    def rejected_prefix_count(self) -> int:
        """Return the number of rejected prefixed commands."""
        return sum(
            1
            for result in self.parsed_results
            if result.matched_prefix and not result.accepted
        )


class PolicyProcessingService:
    """Replay provider comments into canonical policy state."""

    def __init__(self, policy_action_service: PolicyActionService | None = None) -> None:
        """Initialize the policy processing service."""
        self.policy_action_service = policy_action_service or PolicyActionService()

    def process(
        self,
        *,
        initial_policy_state: PolicyState,
        sources: list[PolicyCommentSource],
    ) -> PolicyProcessingResult:
        """Replay provider comments into resolved canonical policy state."""
        parsed_results = self.policy_action_service.parse_sources(sources)
        resolved_policy_state = self.policy_action_service.apply_actions(
            policy_state=initial_policy_state,
            sources=sources,
        )
        return PolicyProcessingResult(
            initial_policy_state=initial_policy_state,
            resolved_policy_state=resolved_policy_state,
            parsed_results=parsed_results,
            sources=sources,
        )

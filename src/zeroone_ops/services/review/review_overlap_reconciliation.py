"""Normalize bounded overlap packets into app-owned reconciliation outcomes."""

from __future__ import annotations

from zeroone_ops.models.review import (
    OverlapPacket,
    OverlapReconciliationResult,
    OverlapResolution,
)


class OverlapReconciliationService:
    """Normalize one overlap packet into app-owned reconciliation outcomes."""

    def reconcile(self, *, packet: OverlapPacket) -> OverlapReconciliationResult:
        """Return normalized overlap outcomes for one bounded overlap packet."""
        candidate_indices_by_current: dict[int, list[int]] = {}
        candidate_currents_by_prior: dict[int, list[int]] = {}
        for candidate in packet.candidates:
            candidate_indices_by_current.setdefault(candidate.current_finding_index, []).append(
                candidate.prior_finding_index
            )
            candidate_currents_by_prior.setdefault(candidate.prior_finding_index, []).append(
                candidate.current_finding_index
            )

        resolutions: list[OverlapResolution] = []
        consumed_prior_indices: set[int] = set()
        ambiguous_prior_indices: set[int] = set()

        for current_index, _ in enumerate(packet.current_findings):
            candidate_prior_indices = candidate_indices_by_current.get(current_index, [])
            if not candidate_prior_indices:
                resolutions.append(
                    OverlapResolution(
                        outcome="new_in_this_pass",
                        current_finding_index=current_index,
                    )
                )
                continue

            if len(candidate_prior_indices) == 1:
                prior_index = candidate_prior_indices[0]
                resolutions.append(
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=current_index,
                        prior_finding_index=prior_index,
                        related_prior_finding_indices=[prior_index],
                    )
                )
                consumed_prior_indices.add(prior_index)
                continue

            resolutions.append(
                OverlapResolution(
                    outcome="overlap_ambiguous",
                    current_finding_index=current_index,
                    related_prior_finding_indices=candidate_prior_indices,
                )
            )
            ambiguous_prior_indices.update(candidate_prior_indices)

        for prior_index, _ in enumerate(packet.prior_findings):
            if prior_index in consumed_prior_indices or prior_index in ambiguous_prior_indices:
                continue
            if prior_index in candidate_currents_by_prior:
                continue
            resolutions.append(
                OverlapResolution(
                    outcome="no_longer_present",
                    prior_finding_index=prior_index,
                    related_prior_finding_indices=[prior_index],
                )
            )

        return OverlapReconciliationResult(
            prior_reviewed_head_sha=packet.prior_head_sha,
            resolutions=resolutions,
        )

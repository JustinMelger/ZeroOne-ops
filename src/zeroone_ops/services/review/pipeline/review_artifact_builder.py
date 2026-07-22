"""Review artifact builder."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.review import (
    OverlapReconciliationResult,
    PublishableReviewArtifact,
    ReconciledReviewDecision,
)

_INTERNAL_PIPELINE_RATIONALE_MARKERS = (
    "candidate stage",
    "grounded candidate set",
    "grounded candidate findings",
    "candidate set",
    "candidate findings",
    "precision stage",
    "reconciliation stage",
    "candidate-backed evidence",
    "provided candidate set",
    "supplied candidate set",
)


@dataclass(frozen=True)
class ReviewArtifactBuildResult:
    """Capture the artifact-building outcome for one reconciled review."""

    artifact: PublishableReviewArtifact
    message: str


class ReviewArtifactBuilder:
    """Package reconciled review meaning into a publish-shaped artifact."""

    def build(
        self,
        *,
        reconciled_decision: ReconciledReviewDecision,
        overlap_result: OverlapReconciliationResult | None = None,
    ) -> ReviewArtifactBuildResult:
        """Build one publish-shaped artifact from reconciled review meaning."""
        artifact = PublishableReviewArtifact.from_reconciled_decision(
            reconciled_decision,
            summary=_artifact_summary(
                classification=reconciled_decision.review_classification,
                decision_summary=reconciled_decision.decision_summary,
                overlap_result=overlap_result,
            ),
            review_confidence_reason=_artifact_confidence_reason(
                classification=reconciled_decision.review_classification,
                decision_rationale=reconciled_decision.decision_rationale,
                overlap_result=overlap_result,
            ),
            follow_up_lines=_render_follow_up_lines(
                classification=reconciled_decision.review_classification,
                overlap_result=overlap_result,
            ),
        )
        return ReviewArtifactBuildResult(
            artifact=artifact,
            message=(
                "Built publishable review artifact with "
                f"{len(artifact.findings)} findings and {len(artifact.follow_up_lines)} "
                "follow-up lines."
            ),
        )


def _artifact_summary(
    *,
    classification: str,
    decision_summary: str,
    overlap_result: OverlapReconciliationResult | None,
) -> str:
    """Return the publish-shaped summary line for one review artifact."""
    if classification == "no_findings":
        if overlap_result is not None:
            return "The updates since the last review don't introduce any new actionable concerns."
        return "No actionable findings in this review pass."
    return decision_summary


def _artifact_confidence_reason(
    *,
    classification: str,
    decision_rationale: str,
    overlap_result: OverlapReconciliationResult | None,
) -> str:
    """Return a developer-facing confidence reason for the publish artifact."""
    if classification != "no_findings":
        return decision_rationale

    lowered_rationale = decision_rationale.lower()
    if not any(marker in lowered_rationale for marker in _INTERNAL_PIPELINE_RATIONALE_MARKERS):
        return decision_rationale

    if overlap_result is not None:
        return (
            "The current diff does not show a remaining actionable issue from the "
            "earlier concern, and I did not see concrete evidence of a new "
            "supported-path regression in this pass."
        )

    return (
        "The reviewed changes appear internally consistent, and I did not see "
        "concrete evidence in the visible code of a remaining supported-path "
        "regression or deterministic failure introduced by this change request."
    )


def _render_follow_up_lines(
    *,
    classification: str,
    overlap_result: OverlapReconciliationResult | None,
) -> list[str]:
    """Render light follow-up framing for repeated reviews on the same MR."""
    if overlap_result is None:
        return []

    lines = [
        (
            f"Follow-up review after the earlier bot pass on "
            f"`{overlap_result.prior_reviewed_head_sha}`."
        )
    ]
    lines.extend(
        _render_overlap_summary_lines(
            overlap_result=overlap_result,
            classification=classification,
        )
    )
    return [*lines, ""]


def _counted_phrase(count: int, singular: str, plural: str) -> str:
    """Return singular or count-aware plural wording for overlap summaries."""
    if count == 1:
        return singular
    return f"{count} {plural}"


def _render_overlap_summary_lines(
    *,
    overlap_result: OverlapReconciliationResult,
    classification: str,
) -> list[str]:
    """Render concise follow-up lines from normalized overlap outcomes."""
    still_unresolved = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "still_unresolved"
    ]
    new_in_this_pass = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "new_in_this_pass"
    ]
    no_longer_present = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "no_longer_present"
    ]
    overlap_ambiguous = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "overlap_ambiguous"
    ]

    unresolved_count = len(still_unresolved)
    new_count = len(new_in_this_pass)
    resolved_count = len(no_longer_present)

    lines: list[str] = []
    if classification == "manual_review_only":
        if still_unresolved or overlap_ambiguous:
            lines.append(
                "This pass may still relate to an earlier concern, but the current "
                "review was not confident enough to verify continuity fully."
            )
        return lines

    if classification == "no_findings":
        if no_longer_present:
            lines.append(
                _counted_phrase(
                    resolved_count,
                    "The earlier concern from the last pass no longer appears present.",
                    "earlier concerns from the last pass no longer appear present.",
                )
            )
        if overlap_ambiguous:
            lines.append(
                "This pass may overlap with an earlier concern, but the overlap "
                "is not fully clear from the current changes."
            )
        return lines

    if still_unresolved:
        lines.append(
            _counted_phrase(
                unresolved_count,
                "An earlier concern from the last pass still appears unresolved.",
                "earlier concerns from the last pass still appear unresolved.",
            )
        )
    if no_longer_present and new_in_this_pass:
        resolved_phrase = _counted_phrase(
            resolved_count,
            "One earlier concern no longer appears present",
            "earlier concerns no longer appear present",
        )
        new_phrase = _counted_phrase(new_count, "a new concern", "new concerns")
        lines.append(f"{resolved_phrase}, but this pass also introduces {new_phrase}.")
    elif no_longer_present:
        lines.append(
            _counted_phrase(
                resolved_count,
                "One earlier concern from the last pass no longer appears present.",
                "earlier concerns from the last pass no longer appear present.",
            )
        )
    elif new_in_this_pass:
        new_phrase = _counted_phrase(new_count, "a new concern", "new concerns")
        lines.append(f"This pass also introduces {new_phrase}.")

    if overlap_ambiguous:
        lines.append(
            "This pass may overlap with an earlier concern, but the overlap is "
            "not fully clear from the current changes."
        )
    return lines

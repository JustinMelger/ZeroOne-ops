"""Preserve overview-only evidence without making continuity or resolution decisions."""

from zeroone_ops.models.review import PublishableReviewArtifact, PublishableReviewFinding
from zeroone_ops.models.review_overview import (
    EarlierReviewFinding,
    EarlierReviewFindings,
    ReviewOverviewEnvelope,
)
from zeroone_ops.services.review.publish.review_links import is_browser_url
from zeroone_ops.utils.review_finding_identity import build_review_finding_identity


def finding_visibility_identity(finding: PublishableReviewFinding) -> str:
    """Use established identity only, never semantic or approximate matching."""
    return finding.stable_identity or build_review_finding_identity(finding)


def _has_published_link(finding: PublishableReviewFinding) -> bool:
    """Require a usable durable discussion before omitting overview-only evidence."""
    receipt = finding.inline_comment
    return (
        receipt is not None
        and receipt.status == "published"
        and is_browser_url(receipt.comment_url)
    )


def collect_earlier_findings(
    *, previous: ReviewOverviewEnvelope | None, artifact: PublishableReviewArtifact
) -> EarlierReviewFindings:
    """Carry ten latest absent concerns forward; eviction is retention, not resolution."""
    if previous is None:
        return EarlierReviewFindings()

    concerns = {
        entry.identity: entry.model_copy(deep=True) for entry in previous.earlier_findings.concerns
    }
    # A cursor survives metadata rewrites of older envelopes and prevents re-eviction.
    collected_through = previous.earlier_findings.collected_through_sequence
    snapshots = [
        snapshot
        for snapshot in previous.complete_passes
        if snapshot.sequence > collected_through and snapshot.artifact.findings
    ]
    for snapshot in reversed(snapshots):
        for finding in snapshot.artifact.findings:
            identity = finding_visibility_identity(finding)
            if _has_published_link(finding):
                concerns.pop(identity, None)
                continue
            concerns[identity] = EarlierReviewFinding(
                identity=identity,
                finding=finding.model_copy(deep=True),
                pass_id=snapshot.pass_id,
                head_sha=snapshot.head_sha,
                sequence=snapshot.sequence,
                workflow_url=snapshot.workflow_url,
            )

    for finding in artifact.findings:
        concerns.pop(finding_visibility_identity(finding), None)

    ordered = sorted(concerns.values(), key=lambda concern: (-concern.sequence, concern.identity))
    return EarlierReviewFindings(
        concerns=tuple(ordered[:10]),
        evicted_count=previous.earlier_findings.evicted_count + max(0, len(ordered) - 10),
        collected_through_sequence=max(
            [collected_through, *(snapshot.sequence for snapshot in snapshots)]
        ),
        history_unavailable=previous.earlier_findings.history_unavailable,
    )

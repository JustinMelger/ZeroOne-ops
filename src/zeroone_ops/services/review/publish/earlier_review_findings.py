"""Preserve overview-only evidence without making continuity or resolution decisions."""

from urllib.parse import urlsplit

from zeroone_ops.models.review import PublishableReviewArtifact, PublishableReviewFinding
from zeroone_ops.models.review_overview import (
    EarlierReviewFinding,
    EarlierReviewFindings,
    ReviewOverviewEnvelope,
)
from zeroone_ops.utils.review_finding_identity import build_review_finding_identity


def finding_visibility_identity(finding: PublishableReviewFinding) -> str:
    """Use established identity only, never semantic or approximate matching."""
    return finding.stable_identity or build_review_finding_identity(finding)


def _has_published_link(finding: PublishableReviewFinding) -> bool:
    """Require a usable durable discussion before omitting overview-only evidence."""
    receipt = finding.inline_comment
    if receipt is None or receipt.status != "published" or not receipt.comment_url:
        return False
    url = receipt.comment_url
    if url != url.strip() or any(ord(character) < 32 for character in url):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


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
    )

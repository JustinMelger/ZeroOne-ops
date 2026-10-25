"""Project evidence only onto the uniquely verified, successfully pushed revision."""

from zeroone_ops.services.remediation.change_request_publisher import (
    RemediationChangeRequestPublisher,
)
from zeroone_ops.services.remediation.publication_evidence import replace_publication_evidence
from zeroone_ops.services.shared.projection_payload import validate_batch_payload


def refresh_revision_description(
    *,
    publisher: RemediationChangeRequestPublisher,
    number: int,
    source_branch: str,
    commit_sha: str,
    evidence: str,
    is_batch: bool,
) -> None:
    """Read before writing; a moved/closed request never acquires this revision's evidence."""
    snapshot = publisher.read_description(number)
    request = snapshot.request
    if (
        request.iid != number
        or request.state != "opened"
        or request.source_branch != source_branch
        or request.head_sha != commit_sha
    ):
        raise ValueError("Linked request no longer matches the published revision.")
    description = replace_publication_evidence(snapshot.description, evidence)
    if is_batch:
        validate_batch_payload(description)
    if description != snapshot.description:
        publisher.update_description(number, description)

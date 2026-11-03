"""Normalize the shared presentation fields returned by commit endpoints."""

from zeroone_ops.models.reviewed_commit import ReviewedCommitMetadata
from zeroone_ops.providers.review.platform import ReviewPlatformClientError


def normalize_reviewed_commit(
    *, head_sha: object, message: object, web_url: object
) -> ReviewedCommitMetadata:
    """Discard full message bodies and bound the first-line label at the boundary."""
    if not isinstance(head_sha, str) or not head_sha:
        raise ReviewPlatformClientError("Unexpected reviewed commit identity.")
    if message is not None and not isinstance(message, str):
        raise ReviewPlatformClientError("Unexpected reviewed commit message.")
    title = message.splitlines()[0].strip() if isinstance(message, str) and message else ""
    if len(title) > 300:
        title = title[:297] + "..."
    return ReviewedCommitMetadata(
        head_sha=head_sha,
        title=title or None,
        web_url=web_url if isinstance(web_url, str) else None,
    )

"""Bind review publication identities to their original request and execution."""

from uuid import NAMESPACE_URL, uuid5


def review_pass_identity(
    *, platform: str, repository_id: str, change_request_number: int, head_sha: str, run_id: str
) -> str:
    """Bind a logical pass to its original run and exact repository/request scope."""
    return str(
        uuid5(
            NAMESPACE_URL,
            repr(
                (
                    platform,
                    repository_id,
                    change_request_number,
                    head_sha,
                    run_id,
                )
            ),
        )
    )

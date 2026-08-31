"""Render deterministic GitHub work-item issue bodies."""

from zeroone_ops.services.control_plane.work_items.work_item_renderer import (
    WorkItemRenderer,
    WorkItemRendererVocabulary,
)


class GitHubWorkItemRenderer(WorkItemRenderer):
    """Render authoritative GitHub work-item issues."""

    def __init__(self) -> None:
        """Initialize GitHub pull-request terminology."""
        super().__init__(
            WorkItemRendererVocabulary(
                change_request_heading="Remediation PR",
                no_change_request="No remediation pull request is linked yet.",
                no_projected_review="No remediation PR review has been projected yet.",
                publication_failure="change-request publication failed.",
            )
        )

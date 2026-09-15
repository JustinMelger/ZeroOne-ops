"""Render deterministic GitLab work-item issue bodies."""

from zeroone_ops.services.control_plane.work_items.work_item_renderer import (
    WorkItemRenderer,
    WorkItemRendererVocabulary,
)


class GitLabWorkItemRenderer(WorkItemRenderer):
    """Render authoritative GitLab work-item issues."""

    def __init__(self) -> None:
        """Initialize GitLab merge-request terminology."""
        super().__init__(
            WorkItemRendererVocabulary(
                change_request_heading="Remediation Merge Request",
                no_change_request="No remediation merge request is linked yet.",
                no_projected_review="No remediation merge-request review has been projected yet.",
                publication_failure="merge-request publication failed.",
            )
        )

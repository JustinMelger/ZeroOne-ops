from zeroone_ops.models.work_item import ProjectedReviewState
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)

from .test_support import build_work_item


def test_render_body_includes_projected_review_section_when_present() -> None:
    renderer = GitHubWorkItemRenderer()
    work_item = build_work_item().model_copy(
        update={
            "projected_review": ProjectedReviewState(
                classification="findings_present",
                reviewed_sha="abc123def",
                review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
                follow_up_required=True,
            )
        }
    )

    body = renderer.render_body(work_item)

    assert "## Review Projection" in body
    assert "- Classification: `findings_present`" in body
    assert "- Reviewed SHA: `abc123def`" in body
    assert "- Follow-up required: `yes`" in body

from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)

from .test_support import build_work_item


def test_parse_work_item_state_round_trips_rendered_body() -> None:
    renderer = GitHubWorkItemRenderer()
    parser = GitHubWorkItemParser()

    body = renderer.render_body(build_work_item())
    parsed = parser.parse_work_item_state(body)

    assert parsed is not None
    assert parsed.work_item_id == "work-1"
    assert parsed.identity_key == build_work_item().identity_key
    assert parsed.projected_review is None
    assert parsed.attempt_number == 1
    assert parsed.recovery_events == []

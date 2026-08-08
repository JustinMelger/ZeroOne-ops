import pytest

from zeroone_ops.providers.github_client import GitHubClientError
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


def test_parse_work_item_state_rejects_embedded_state_block() -> None:
    body = GitHubWorkItemRenderer().render_body(build_work_item())
    state_block = body.split("## Machine State\n\n", maxsplit=1)[1]
    body = body.replace("## Status", f"{state_block}\n## Status", 1)

    with pytest.raises(GitHubClientError, match="final renderer-owned block"):
        GitHubWorkItemParser().parse_work_item_state(body)


def test_parse_work_item_state_rejects_content_after_machine_state() -> None:
    body = GitHubWorkItemRenderer().render_body(build_work_item()) + "\nOperator note\n"

    with pytest.raises(GitHubClientError, match="final renderer-owned block"):
        GitHubWorkItemParser().parse_work_item_state(body)

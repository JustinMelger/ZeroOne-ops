from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitHubConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.review import ChangeRequestReviewContext
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.review.pipeline import review_runner
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner
from zeroone_ops.settings import SettingsError


def test_gitlab_issue_mode_skips_legacy_dashboard_review_mirror(tmp_path: Path) -> None:
    runner = ReviewRunner(
        repo_root=tmp_path,
        config=AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(
                control_plane_mode="issues",
                target_branch="main",
                labels=[],
            ),
        ),
        review_client=object(),  # type: ignore[arg-type]
        dashboard_client=object(),  # type: ignore[arg-type]
        review_state_service=object(),  # type: ignore[arg-type]
    )

    assert runner._build_dashboard_updater() is None


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("lookup", ["linked", "absent", "wrong_url", "failure"])
def test_verified_notice_link_does_not_require_semantic_safety(
    tmp_path, monkeypatch, platform, lookup
):
    context = ChangeRequestReviewContext(
        change_request_number=9,
        title="Remediation",
        source_branch="remediation",
        target_branch="main",
        head_sha="sha",
        web_url="https://example.com/pr/9",
        description="Tracking work item: https://untrusted.example/issues/1",
    )
    work_item = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="in_progress",
        summary="Fix",
        source=WorkItemSourceRef(source="ruff", source_item_key="1", repository_scope="org/repo"),
        linked_change_request=ChangeRequestRef(
            number=9,
            web_url="https://other.example/pr/9" if lookup == "wrong_url" else context.web_url,
        ),
    )
    result = (
        None
        if lookup == "absent"
        else SimpleNamespace(
            work_item=work_item, issue=SimpleNamespace(web_url="https://example.com/issues/12")
        )
    )
    service = Mock()
    service.find_open_work_item_by_change_request.return_value = result
    if lookup == "failure":
        service.find_open_work_item_by_change_request.side_effect = SettingsError("Unavailable")
    name = "GitHub" if platform == "github" else "GitLab"
    monkeypatch.setattr(review_runner, f"{name}WorkItemService", lambda client: service)
    monkeypatch.setattr(review_runner, f"{name}WorkItemClient", lambda config: object())
    monkeypatch.setattr(review_runner, f"load_{platform}_connection_config", lambda: object())
    runner = ReviewRunner(
        repo_root=tmp_path,
        config=AppConfig(
            platform=platform,
            base_branch="main",
            github=GitHubConfig(),
            gitlab=GitLabConfig(target_branch="main"),
        ),
        review_client=object(),
        dashboard_client=None,
        review_state_service=object(),
    )
    updated = runner._with_verified_remediation_context(repository_id="org/repo", context=context)
    if lookup == "linked":
        assert updated.remediation_context.verified_work_item_url == "https://example.com/issues/12"
        assert updated.remediation_context.semantic_safety is None
    else:
        assert updated.remediation_context is None

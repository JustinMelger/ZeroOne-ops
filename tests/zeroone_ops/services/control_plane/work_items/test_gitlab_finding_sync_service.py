"""Public GitLab finding-sync composition uses the shared rollout contract."""

from zeroone_ops.models.finding_sync import FindingSyncResult
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncResult,
    GitLabFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)

from .test_batch_finding_sync_coordinator import MemoryIssueClient, finding, policy


def test_public_service_preserves_result_alias_and_configured_batch_limit():
    boundary = GitLabWorkItemService(MemoryIssueClient("gitlab"))
    result = GitLabFindingSyncService(work_item_service=boundary).sync(
        project_id="team/repo",
        findings=[finding(), finding("b")],
        policy_state=policy(),
        max_findings_per_work_item=1,
    )
    assert GitLabFindingSyncResult is FindingSyncResult
    assert result.created_count == result.selected_member_count == 1
    assert result.backlog_only_count == 1

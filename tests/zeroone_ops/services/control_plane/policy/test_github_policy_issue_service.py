from zeroone_ops.models.dashboard import (
    DashboardPolicyState,
    DashboardPolicyView,
    DashboardSeverityPolicyEntry,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.github import GitHubIssueComment, GitHubIssueInfo
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.services.control_plane.policy.github_policy_issue_service import (
    GitHubPolicyIssueProcessResult,
    GitHubPolicyIssueService,
)


class FakePolicyViewBuilder:
    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        if policy_state is not None and policy_state.severity_policy:
            return policy_state
        return DashboardPolicyState(
            severity_policy=[
                DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="high", enabled=False),
            ]
        )

    def build(
        self,
        items: list[object],
        *,
        policy_state: DashboardPolicyState | None = None,
    ) -> DashboardPolicyView:
        del items
        state = self.resolve_policy_state(policy_state)
        return DashboardPolicyView(
            severity_policy=[
                DashboardSeverityPolicyEntry(
                    severity=entry.severity,
                    enabled=entry.enabled,
                    reason=entry.reason,
                )
                for entry in state.severity_policy
            ]
        )


class FakeGitHubPolicyClient:
    def __init__(self, existing_issue: GitHubIssueInfo | None = None) -> None:
        self.existing_issue = existing_issue
        self.created_issue: GitHubIssueInfo | None = None
        self.updated_issue: GitHubIssueInfo | None = None
        self.comments: list[GitHubIssueComment] = []
        self.permissions_by_username: dict[str, str] = {}
        self.permission_error_usernames: set[str] = set()

    def find_open_issue(
        self,
        *,
        repository_id: str,
        title: str,
        labels: list[str] | None = None,
    ) -> GitHubIssueInfo | None:
        del repository_id, title, labels
        return self.existing_issue

    def create_issue(
        self,
        *,
        repository_id: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> GitHubIssueInfo:
        del repository_id, labels
        self.created_issue = GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=title,
            body=body,
        )
        self.existing_issue = self.created_issue
        return self.created_issue

    def update_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        body: str,
    ) -> GitHubIssueInfo:
        del repository_id, issue_number
        assert self.existing_issue is not None
        self.updated_issue = GitHubIssueInfo(
            id=self.existing_issue.id,
            number=self.existing_issue.number,
            web_url=self.existing_issue.web_url,
            title=self.existing_issue.title,
            body=body,
        )
        self.existing_issue = self.updated_issue
        return self.updated_issue

    def list_issue_comments(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> list[GitHubIssueComment]:
        del repository_id, issue_number
        return list(self.comments)

    def get_repository_permission(
        self,
        *,
        repository_id: str,
        username: str,
    ) -> str:
        del repository_id
        if username in self.permission_error_usernames:
            raise GitHubClientError("permission lookup failed")
        return self.permissions_by_username[username]


def test_load_or_create_creates_policy_issue_when_missing() -> None:
    service = GitHubPolicyIssueService(
        FakeGitHubPolicyClient(),
        policy_view_builder=FakePolicyViewBuilder(),
    )

    issue = service.load_or_create(repository_id="octo-org/octo-repo")

    assert issue.title == "ZeroOne Ops Policy"
    assert "Machine-managed repository policy for ZeroOne Ops." in issue.body
    assert "zeroone-policy-state" in issue.body


def test_load_policy_state_uses_seeded_defaults_without_creating_in_dry_run() -> None:
    client = FakeGitHubPolicyClient()
    service = GitHubPolicyIssueService(
        client,
        policy_view_builder=FakePolicyViewBuilder(),
    )

    policy_state = service.load_policy_state(
        repository_id="octo-org/octo-repo",
        persist=False,
    )

    assert [entry.severity for entry in policy_state.severity_policy] == ["low", "medium", "high"]
    assert client.created_issue is None


def test_process_policy_replays_comments_and_reports_counts() -> None:
    existing_issue = GitHubIssueInfo(
        id=10,
        number=11,
        web_url="https://github.example.com/octo-org/octo-repo/issues/11",
        title="ZeroOne Ops Policy",
        body="",
    )
    client = FakeGitHubPolicyClient(existing_issue=existing_issue)
    client.comments = [
        GitHubIssueComment(
            id=12,
            body="/zeroone policy severity enable high",
            author_username="justin",
            created_at="2026-07-08T10:00:00Z",
        ),
        GitHubIssueComment(
            id=13,
            body="/zeroone policy severity maybe high",
            author_username="justin",
            created_at="2026-07-08T10:01:00Z",
        ),
    ]
    client.permissions_by_username["justin"] = "admin"
    service = GitHubPolicyIssueService(
        client,
        policy_view_builder=FakePolicyViewBuilder(),
    )

    result = service.process_policy(repository_id="octo-org/octo-repo", persist=False)

    assert isinstance(result, GitHubPolicyIssueProcessResult)
    assert result.comment_count == 2
    assert result.authorized_comment_count == 2
    assert result.matched_prefix_count == 2
    assert result.accepted_action_count == 1
    assert result.rejected_prefix_count == 1
    assert result.issue_changed is True


def test_process_policy_persists_replayed_state_into_issue_body() -> None:
    service = GitHubPolicyIssueService(
        FakeGitHubPolicyClient(
            existing_issue=GitHubIssueInfo(
                id=10,
                number=11,
                web_url="https://github.example.com/octo-org/octo-repo/issues/11",
                title="ZeroOne Ops Policy",
                body="",
            )
        ),
        policy_view_builder=FakePolicyViewBuilder(),
    )
    client = service.client
    client.comments = [
        GitHubIssueComment(
            id=12,
            body="/zeroone policy severity enable high",
            author_username="justin",
            created_at="2026-07-08T10:00:00Z",
        )
    ]
    client.permissions_by_username["justin"] = "admin"

    result = service.process_policy(repository_id="octo-org/octo-repo", persist=True)

    assert result.issue_changed is True
    assert client.updated_issue is not None
    assert '"note_id": 12' in client.updated_issue.body
    assert "`high` | enabled" in client.updated_issue.body


def test_process_policy_ignores_non_admin_comments() -> None:
    existing_issue = GitHubIssueInfo(
        id=10,
        number=11,
        web_url="https://github.example.com/octo-org/octo-repo/issues/11",
        title="ZeroOne Ops Policy",
        body="",
    )
    client = FakeGitHubPolicyClient(existing_issue=existing_issue)
    client.comments = [
        GitHubIssueComment(
            id=12,
            body="/zeroone policy severity enable high",
            author_username="maintainer",
            created_at="2026-07-08T10:00:00Z",
        )
    ]
    client.permissions_by_username["maintainer"] = "write"
    service = GitHubPolicyIssueService(
        client,
        policy_view_builder=FakePolicyViewBuilder(),
    )

    result = service.process_policy(repository_id="octo-org/octo-repo", persist=False)

    assert result.comment_count == 1
    assert result.authorized_comment_count == 0
    assert result.matched_prefix_count == 0
    assert result.accepted_action_count == 0
    assert result.rejected_prefix_count == 0


def test_process_policy_ignores_comments_with_unresolvable_permission() -> None:
    existing_issue = GitHubIssueInfo(
        id=10,
        number=11,
        web_url="https://github.example.com/octo-org/octo-repo/issues/11",
        title="ZeroOne Ops Policy",
        body="",
    )
    client = FakeGitHubPolicyClient(existing_issue=existing_issue)
    client.comments = [
        GitHubIssueComment(
            id=12,
            body="/zeroone policy severity enable high",
            author_username="ghost-user",
            created_at="2026-07-08T10:00:00Z",
        )
    ]
    client.permission_error_usernames.add("ghost-user")
    service = GitHubPolicyIssueService(
        client,
        policy_view_builder=FakePolicyViewBuilder(),
    )

    result = service.process_policy(repository_id="octo-org/octo-repo", persist=False)

    assert result.comment_count == 1
    assert result.authorized_comment_count == 0
    assert result.matched_prefix_count == 0
    assert result.accepted_action_count == 0
    assert result.rejected_prefix_count == 0

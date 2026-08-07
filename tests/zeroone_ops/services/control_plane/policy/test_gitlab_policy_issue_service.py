from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.models.dashboard import (
    DashboardItem,
    DashboardPolicyState,
    DashboardPolicyView,
    DashboardSeverityPolicyEntry,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.providers.gitlab_policy_client import GitLabPolicyClient
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service import (
    GitLabPolicyIssueProcessResult,
    GitLabPolicyIssueService,
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
        items: list[DashboardItem],
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


class FakeIssueClient:
    def __init__(self, issue: GitLabIssueInfo | None = None) -> None:
        self.issue = issue
        self.notes: list[GitLabIssueNote] = []
        self.access_levels: dict[int, int] = {}
        self.created_issue: GitLabIssueInfo | None = None
        self.updated_issue: GitLabIssueInfo | None = None

    def list_open_issues(self, *, project_id: str, labels: list[str]) -> list[GitLabIssueInfo]:
        del project_id, labels
        return [self.issue] if self.issue is not None else []

    def create_issue(
        self, *, project_id: str, title: str, description: str, labels: list[str]
    ) -> GitLabIssueInfo:
        del project_id
        self.created_issue = _issue(iid=11, title=title, description=description, labels=labels)
        self.issue = self.created_issue
        return self.created_issue

    def update_issue(
        self,
        *,
        project_id: str,
        issue_iid: int,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        del project_id
        self.updated_issue = _issue(
            iid=issue_iid,
            title=title,
            description=description,
            labels=labels,
        )
        self.issue = self.updated_issue
        return self.updated_issue

    def list_issue_notes(self, *, project_id: str, issue_iid: int) -> list[GitLabIssueNote]:
        del project_id, issue_iid
        return list(self.notes)

    def get_project_member_access_level(self, *, project_id: str, user_id: int) -> int:
        del project_id
        return self.access_levels[user_id]


def _issue(
    *,
    iid: int = 10,
    title: str = "ZeroOne Ops Policy",
    description: str = "",
    labels: list[str] | None = None,
) -> GitLabIssueInfo:
    return GitLabIssueInfo(
        id=iid,
        iid=iid,
        web_url=f"https://gitlab.example.com/group/project/-/issues/{iid}",
        title=title,
        description=description,
        labels=labels or ["zeroone-policy"],
    )


def _service(fake: FakeIssueClient) -> GitLabPolicyIssueService:
    client = GitLabPolicyClient(
        GitLabConnectionConfig(url="https://gitlab.example.com", token="token", project_id="1"),
        issue_client=fake,  # type: ignore[arg-type]
    )
    return GitLabPolicyIssueService(client, policy_view_builder=FakePolicyViewBuilder())


def test_load_or_create_creates_gitlab_policy_issue_when_missing() -> None:
    fake = FakeIssueClient()

    issue = _service(fake).load_or_create(project_id="group/project")

    assert issue.title == "ZeroOne Ops Policy"
    assert "Machine-managed repository policy for ZeroOne Ops." in issue.description
    assert fake.created_issue == issue


def test_load_policy_state_does_not_create_issue_when_not_persisting() -> None:
    fake = FakeIssueClient()

    policy_state = _service(fake).load_policy_state(project_id="group/project", persist=False)

    assert [entry.severity for entry in policy_state.severity_policy] == ["low", "medium", "high"]
    assert fake.created_issue is None


def test_process_policy_replays_authorized_notes() -> None:
    fake = FakeIssueClient(_issue())
    fake.notes = [
        GitLabIssueNote(
            id=12,
            body="/zeroone policy severity enable high",
            author_id=1,
            author_username="maintainer",
            created_at="2026-08-07T10:00:00Z",
        ),
        GitLabIssueNote(
            id=13,
            body="/zeroone policy severity disable medium",
            author_id=2,
            author_username="developer",
            created_at="2026-08-07T10:01:00Z",
        ),
    ]
    fake.access_levels = {1: 40, 2: 30}

    result = _service(fake).process_policy(project_id="group/project", persist=False)

    assert isinstance(result, GitLabPolicyIssueProcessResult)
    assert result.note_count == 2
    assert result.authorized_note_count == 1
    assert result.matched_prefix_count == 1
    assert result.accepted_action_count == 1
    assert result.issue_changed is True
    assert result.initial_policy_state is not None
    assert result.initial_policy_state.severity_policy[-1].enabled is False

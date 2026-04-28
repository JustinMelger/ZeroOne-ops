from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardPolicyState,
    DashboardPolicyView,
    DashboardSection,
    DashboardSeverityPolicyEntry,
    empty_sections,
)
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.services.dashboard.dashboard_policy_service import DashboardPolicyService


class FakePolicyViewBuilder:
    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        return policy_state or DashboardPolicyState()

    def build(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState | None = None,
    ) -> DashboardPolicyView:
        del items, policy_state
        return DashboardPolicyView(
            severity_policy=[
                DashboardSeverityPolicyEntry(
                    severity="low",
                    enabled=True,
                )
            ]
        )


def build_document() -> DashboardDocument:
    sections = empty_sections()
    sections[0] = DashboardSection(
        key="open_candidates",
        title="Open Candidates",
        items=[],
    )
    return DashboardDocument(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        sections=sections,
    )


def test_apply_to_document_replays_notes_and_builds_policy_view() -> None:
    service = DashboardPolicyService(policy_view_builder=FakePolicyViewBuilder())

    document = service.apply_to_document(
        build_document(),
        notes=[
            GitLabIssueNote(
                id=12,
                body="/zeroone policy severity disable high",
                author_username="operator",
                created_at="2026-04-28T10:00:00.000Z",
            )
        ],
    )

    assert document.policy_view.severity_policy[0].severity == "low"
    severity_by_name = {entry.severity: entry for entry in document.policy_state.severity_policy}
    assert severity_by_name["high"].enabled is False
    assert severity_by_name["high"].updated_by == "operator"

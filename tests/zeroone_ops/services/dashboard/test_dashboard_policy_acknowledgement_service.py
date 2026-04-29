from zeroone_ops.models.dashboard import DashboardPolicyState, DashboardSeverityPolicyStateEntry
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.services.dashboard.dashboard_policy_acknowledgement_service import (
    DashboardPolicyAcknowledgementService,
)
from zeroone_ops.services.dashboard.dashboard_policy_action_service import (
    DashboardPolicyActionService,
)


class FakeDashboardClient:
    def __init__(self) -> None:
        self.created_bodies: list[str] = []

    def create_issue_note(self, *, project_id: str, issue_iid: int, body: str) -> GitLabIssueNote:
        del project_id, issue_iid
        self.created_bodies.append(body)
        return GitLabIssueNote(id=100 + len(self.created_bodies), body=body)


def test_publish_acknowledgements_creates_accepted_and_rejected_notes() -> None:
    service = DashboardPolicyAcknowledgementService()
    action_service = DashboardPolicyActionService()
    notes = [
        GitLabIssueNote(
            id=12,
            body="/zeroone policy severity disable high",
            author_username="operator",
            created_at="2026-04-29T10:00:00.000Z",
        ),
        GitLabIssueNote(
            id=13,
            body="/zeroone policy severity maybe high",
            author_username="operator",
            created_at="2026-04-29T10:01:00.000Z",
        ),
    ]
    client = FakeDashboardClient()

    result = service.publish_acknowledgements(
        client=client,  # type: ignore[arg-type]
        project_id="123",
        issue_iid=11,
        notes=notes,
        parsed_results=action_service.parse_notes(notes),
        initial_policy_state=DashboardPolicyState(
            severity_policy=[
                DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
            ]
        ),
        dry_run=False,
    )

    assert result.needed_count == 2
    assert result.published_count == 2
    assert result.failed_count == 0
    assert "Disabled severity `high`." in client.created_bodies[0]
    assert "<!-- zeroone-ops:policy-ack:v1 note=12 outcome=accepted -->" in client.created_bodies[0]
    assert "Policy command rejected for note #13." in client.created_bodies[1]
    assert "dashboard legend" in client.created_bodies[1]
    assert "<!-- zeroone-ops:policy-ack:v1 note=13 outcome=rejected -->" in client.created_bodies[1]


def test_publish_acknowledgements_skips_existing_marker() -> None:
    service = DashboardPolicyAcknowledgementService()
    action_service = DashboardPolicyActionService()
    notes = [
        GitLabIssueNote(
            id=12,
            body="/zeroone policy severity disable high",
            author_username="operator",
            created_at="2026-04-29T10:00:00.000Z",
        ),
        GitLabIssueNote(
            id=90,
            body=(
                "Policy command accepted for note #12. Disabled severity `high`.\n\n"
                "<!-- zeroone-ops:policy-ack:v1 note=12 outcome=accepted -->"
            ),
            author_username="ai-sonar-bot",
            created_at="2026-04-29T10:02:00.000Z",
        ),
    ]
    client = FakeDashboardClient()

    result = service.publish_acknowledgements(
        client=client,  # type: ignore[arg-type]
        project_id="123",
        issue_iid=11,
        notes=notes,
        parsed_results=action_service.parse_notes(notes),
        initial_policy_state=DashboardPolicyState(
            severity_policy=[
                DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
            ]
        ),
        dry_run=False,
    )

    assert result.needed_count == 1
    assert result.published_count == 0
    assert result.skipped_existing_count == 1
    assert client.created_bodies == []


def test_publish_acknowledgements_replies_when_command_is_already_satisfied() -> None:
    service = DashboardPolicyAcknowledgementService()
    action_service = DashboardPolicyActionService()
    notes = [
        GitLabIssueNote(
            id=12,
            body="/zeroone policy severity disable high",
            author_username="operator",
            created_at="2026-04-29T10:00:00.000Z",
        )
    ]
    client = FakeDashboardClient()

    result = service.publish_acknowledgements(
        client=client,  # type: ignore[arg-type]
        project_id="123",
        issue_iid=11,
        notes=notes,
        parsed_results=action_service.parse_notes(notes),
        initial_policy_state=DashboardPolicyState(
            severity_policy=[
                DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="high", enabled=False),
            ]
        ),
        dry_run=False,
    )

    assert result.published_count == 1
    assert "Severity `high` was already disabled." in client.created_bodies[0]

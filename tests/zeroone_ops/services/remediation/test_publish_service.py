from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.services.remediation.change_request_publisher import (
    PublishedChangeRequest,
)
from zeroone_ops.services.remediation.publish_service import PublishService


def build_config() -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            bootstrap_severities=["MAJOR"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main", labels=["zeroone-ops"]),
    )


def build_issue() -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="FIXTURE-1",
        source_type="sonarqube",
        source_ref="FIXTURE-1",
        title="python:S2259 in src/service.py",
        status="OPEN",
        message="Fixture issue",
        file_path="src/service.py",
        line=1,
        rule_id="python:S2259",
        severity="MAJOR",
        issue_type="BUG",
        component="sample-project:src/service.py",
        project="sample-project",
    )


class StubBranchManager:
    def push_current_branch(self, *, remote_name: str = "origin") -> str:
        del remote_name
        return "zeroone-ops/fix"


class StubChangeRequestPublisher:
    def __init__(
        self,
        *,
        result: PublishedChangeRequest | None = None,
    ) -> None:
        self.result = result or PublishedChangeRequest(
            info=ChangeRequestInfo(
                iid=17,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
                title="fix: remediate python:S2259 in service.py",
            ),
            action="created",
        )
        self.request = None

    def publish(self, request):  # noqa: ANN001
        self.request = request
        return self.result


def test_publish_service_builds_deterministic_description() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    description = service.build_change_request_description(
        selected_issue=build_issue(),
        change_summary="summary",
    )

    assert description == "\n".join(
        [
            "## Summary",
            "summary",
            "",
            "## Remediation Target",
            "- Source: `SonarQube`",
            "- Issue key: `FIXTURE-1`",
            "- Rule: `python:S2259`",
            "- Severity: `MAJOR`",
            "- Type: `BUG`",
            "- File: `src/service.py`",
            "- Line: `1`",
            "- Message: Fixture issue",
            "",
            "## Notes",
            "- Diff was rendered by the bot from a structured edit proposal.",
        ]
    )


def test_publish_service_uses_generic_profile_for_unknown_source() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    description = service.build_change_request_description(
        selected_issue=RemediationExecutionTarget(
            item_id="pipeline:1",
            source_type="pipeline_failure",
            source_ref="job-1",
            title="pytest failed in src/service.py",
            status="open",
            message="Test suite is failing.",
            file_path="src/service.py",
        ),
        change_summary="summary",
    )

    assert "## Remediation Target" in description
    assert "- Source: `Remediation`" in description
    assert "- Item reference: `job-1`" in description


def test_publish_service_builds_conventional_commit_change_request_title() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    title = service.build_change_request_title(
        selected_issue=build_issue(),
        proposed_title="patch service please",
    )

    assert title == "fix: remediate python:S2259 in service.py"


def test_publish_service_uses_pushed_branch_consistently() -> None:
    publisher = StubChangeRequestPublisher()
    service = PublishService(
        config=build_config(),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert publisher.request is not None
    assert publisher.request.source_branch == "zeroone-ops/fix"
    assert result.branch_name == "zeroone-ops/fix"


def test_publish_service_assigns_created_merge_request_by_configured_username() -> None:
    publisher = StubChangeRequestPublisher()
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(
                target_branch="main",
                labels=["zeroone-ops"],
                merge_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert publisher.request is not None
    assert publisher.request.assignee_username == "justin"
    assert result.change_request_action == "created"


def test_publish_service_assigns_reused_merge_request_by_configured_username() -> None:
    publisher = StubChangeRequestPublisher(
        result=PublishedChangeRequest(
            info=ChangeRequestInfo(
                iid=17,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
                title="fix: remediate python:S2259 in service.py",
            ),
            action="reused",
        )
    )
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(
                target_branch="main",
                labels=["zeroone-ops"],
                merge_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert publisher.request is not None
    assert publisher.request.assignee_username == "justin"
    assert result.change_request_action == "reused"


def test_publish_service_requires_change_request_title() -> None:
    service = PublishService(
        config=build_config(),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_description="summary",
    )

    assert result.error_message == "Publish failed: change request title is required."


def test_publish_service_requires_change_request_description() -> None:
    service = PublishService(
        config=build_config(),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
    )

    assert result.error_message == "Publish failed: change request description is required."

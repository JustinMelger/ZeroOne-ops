from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitHubConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.remediation.change_request_publisher import (
    PublishedChangeRequest,
)
from zeroone_ops.services.remediation.control_plane import RemediationControlPlane
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
    def __init__(self, *, push_error: str | None = None) -> None:
        self.push_error = push_error

    def push_current_branch(self, *, remote_name: str = "origin") -> str:
        del remote_name
        if self.push_error is not None:
            raise RuntimeError(self.push_error)
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
        self.error_message: str | None = None

    def publish(self, request):  # noqa: ANN001
        if self.error_message is not None:
            raise RuntimeError(self.error_message)
        self.request = request
        return self.result


class StubRemediationControlPlane(RemediationControlPlane):
    def __init__(
        self,
        *,
        error_on_call: int | None = None,
        sync_error_message: str | None = None,
        blocked_error_message: str | None = None,
    ) -> None:
        self.calls: list[WorkItemState] = []
        self.error_on_call = error_on_call
        self.sync_error_message = sync_error_message
        self.blocked_error_message = blocked_error_message

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState:
        work_item = WorkItemState(
            work_item_id="work-1",
            kind="remediation",
            status="in_progress",
            source=WorkItemSourceRef(
                source=selected_issue.source_type,
                source_item_key=selected_issue.source_ref,
                repository_scope="octo-org/octo-repo",
            ),
            summary=selected_issue.title,
            severity=selected_issue.severity,
            file_path=selected_issue.file_path,
            line=selected_issue.line,
        )
        self.calls.append(work_item)
        if self.error_on_call == len(self.calls):
            raise RuntimeError("work item sync failed")
        return work_item

    def mark_publish_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        del selected_issue
        if existing_work_item is None:
            return
        self.calls.append(existing_work_item.model_copy(update={"status": "blocked"}))
        if self.blocked_error_message is not None:
            raise RuntimeError(self.blocked_error_message)
        if self.error_on_call == len(self.calls):
            raise RuntimeError("work item sync failed")

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        del selected_issue
        if existing_work_item is None:
            return
        updated_work_item = existing_work_item.model_copy(
            update={
                "status": "in_progress",
                "linked_change_request": ChangeRequestRef(
                    number=published_change_request.iid,
                    web_url=published_change_request.web_url,
                ),
            }
        )
        self.calls.append(updated_work_item)
        if self.sync_error_message is not None:
            raise RuntimeError(self.sync_error_message)
        if self.error_on_call == len(self.calls):
            return


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


def test_publish_service_uses_github_publication_options() -> None:
    publisher = StubChangeRequestPublisher(
        result=PublishedChangeRequest(
            info=ChangeRequestInfo(
                iid=23,
                web_url="https://github.com/octo-org/octo-repo/pull/23",
                title="fix: remediate python:S2259 in service.py",
            ),
            action="created",
        )
    )
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            platform="github",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            github=GitHubConfig(
                labels=["zeroone-ops", "autofix"],
                pull_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
        remediation_control_plane=StubRemediationControlPlane(),
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert publisher.request is not None
    assert publisher.request.labels == ["zeroone-ops", "autofix"]
    assert publisher.request.assignee_username == "justin"
    assert result.change_request_url == "https://github.com/octo-org/octo-repo/pull/23"
    assert result.change_request_action == "created"


def test_publish_service_allows_github_publish_without_github_block() -> None:
    publisher = StubChangeRequestPublisher(
        result=PublishedChangeRequest(
            info=ChangeRequestInfo(
                iid=24,
                web_url="https://github.com/octo-org/octo-repo/pull/24",
                title="fix: remediate python:S2259 in service.py",
            ),
            action="created",
        )
    )
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            platform="github",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
        remediation_control_plane=StubRemediationControlPlane(),
    )

    service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert publisher.request is not None
    assert publisher.request.labels == []
    assert publisher.request.assignee_username is None


def test_publish_service_upserts_github_work_item_before_and_after_publish() -> None:
    publisher = StubChangeRequestPublisher(
        result=PublishedChangeRequest(
            info=ChangeRequestInfo(
                iid=23,
                web_url="https://github.com/octo-org/octo-repo/pull/23",
                title="fix: remediate python:S2259 in service.py",
            ),
            action="created",
        )
    )
    work_item_service = StubRemediationControlPlane()
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            platform="github",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            github=GitHubConfig(
                labels=["zeroone-ops", "autofix"],
                pull_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
        remediation_control_plane=work_item_service,
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert result.change_request_url == "https://github.com/octo-org/octo-repo/pull/23"
    assert len(work_item_service.calls) == 2
    first_call = work_item_service.calls[0]
    second_call = work_item_service.calls[1]
    assert first_call.status == "in_progress"
    assert first_call.linked_change_request is None
    assert second_call.work_item_id == first_call.work_item_id
    assert second_call.linked_change_request is not None
    assert second_call.linked_change_request.number == 23


def test_publish_service_marks_github_work_item_blocked_when_publish_fails() -> None:
    publisher = StubChangeRequestPublisher()
    publisher.error_message = "pull request create failed"
    work_item_service = StubRemediationControlPlane()
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            platform="github",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            github=GitHubConfig(
                labels=["zeroone-ops", "autofix"],
                pull_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
        remediation_control_plane=work_item_service,
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert result.error_message == "Publish failed: pull request create failed"
    assert len(work_item_service.calls) == 2
    assert work_item_service.calls[0].status == "in_progress"
    assert work_item_service.calls[1].status == "blocked"
    assert work_item_service.calls[1].work_item_id == work_item_service.calls[0].work_item_id


def test_publish_service_keeps_success_when_post_publish_work_item_sync_fails() -> None:
    publisher = StubChangeRequestPublisher(
        result=PublishedChangeRequest(
            info=ChangeRequestInfo(
                iid=23,
                web_url="https://github.com/octo-org/octo-repo/pull/23",
                title="fix: remediate python:S2259 in service.py",
            ),
            action="created",
        )
    )
    work_item_service = StubRemediationControlPlane(
        sync_error_message="post-publish work item sync failed"
    )
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            platform="github",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            github=GitHubConfig(
                labels=["zeroone-ops", "autofix"],
                pull_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
        remediation_control_plane=work_item_service,
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert result.error_message is None
    assert result.change_request_url == "https://github.com/octo-org/octo-repo/pull/23"
    assert result.change_request_action == "created"
    assert len(work_item_service.calls) == 2


def test_publish_service_preserves_original_publish_error_when_blocked_cleanup_fails() -> None:
    publisher = StubChangeRequestPublisher()
    publisher.error_message = "pull request create failed"
    work_item_service = StubRemediationControlPlane(blocked_error_message="blocked cleanup failed")
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            platform="github",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            github=GitHubConfig(
                labels=["zeroone-ops", "autofix"],
                pull_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
        change_request_publisher=publisher,
        remediation_control_plane=work_item_service,
    )

    result = service.publish(
        selected_issue=build_issue(),
        change_request_title="ignored",
        change_request_description="summary",
    )

    assert result.error_message == "Publish failed: pull request create failed"
    assert len(work_item_service.calls) == 2
    assert work_item_service.calls[0].status == "in_progress"
    assert work_item_service.calls[1].status == "blocked"


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
